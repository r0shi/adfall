#!/usr/bin/env python3
"""From Ad-ID creatives to watchable video: buyer -> YouTube channel -> upload per creative.

  python3 -m ingest.video                      # channels, then videos, for the top 300 buyers by airings
  python3 -m ingest.video channels --top 300   # find each buyer's own channel (API if YOUTUBE_API_KEY, else yt-dlp)
  python3 -m ingest.video videos   --top 300   # list uploads, match creatives, write creative_video
  python3 -m ingest.video overrides            # (re)apply data/video_overrides.yaml, wins over everything
  python3 -m ingest.video report               # match rates by tier / category / place, for docs/research.md
  --buyers 2,550       restrict to buyer ids     --refresh   ignore the cached listings and dates

What the FCC file gives us is an Ad-ID per aired spot. Ad-IDs identify the advertiser (4-letter prefix) and
the spot (running number), but no public registry resolves them to video. The campaign's own channel
usually carries the TV spot within a few days of its first airing, so: find the channel from the buyer's
names (canonical, FEC committee, office, state), list its ad-length uploads with exact publish dates, and
align creatives (grouped into spot families, see family()) with uploads by first-aired date, duration, order
of release and ad-likeness of the title. Confidence is scored, best and runner-up are stored.

Sources, in order of preference: YouTube Data API v3 (needs YOUTUBE_API_KEY in .env or the environment;
~100 quota units per channel search, 1 per 50 uploads), yt-dlp metadata extraction (keyless; flat listings
give exact durations and approximate dates), and the public watch page's uploadDate for exact dates
(one small GET per ad-length upload, cached in data/video_cache/). Nothing is downloaded.
Logs: data/logs/video-<timestamp>.log (ingest.runlog.Stage). Lock: data/locks/video.lock.
"""
import collections, datetime, json, logging, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from rapidfuzz import fuzz
from . import pg

log = logging.getLogger('ingest.video')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "video_cache")
OVERRIDES = os.path.join(ROOT, "data", "video_overrides.yaml")
UA = "adfall/0.1 (+research; metadata only)"

AD_MIN, AD_MAX = 10, 95                       # seconds: what counts as an ad-length upload
STD_LENGTHS = (10, 15, 30, 45, 60, 90)
NEWSY = re.compile(r"\b(news|tv|wxyz|kcci|who ?13|register|politico|cbs\d*|nbc\d*|abc\d*|fox\d*|cnn|msnbc|c-span|cspan|pbs|npr|tribune|gazette|journal|press|radio|podcast|channel \d|\d+ ?news|iowa pbs|axios|the hill|forum|debate|all political ads)\b", re.I)
CALLSIGN = re.compile(r"\b[KW][A-Z]{2,3}(-?(TV|DT))?\b")       # a station channel: KCCI, WXYZ-TV (case-sensitive)
OFFICE_WORDS = [("gov", "Governor"), ("senate", "Senate"), ("house", "Congress"), ("congress", "Congress"), ("attorney", "Attorney General"),
                ("secretary", "Secretary of State"), ("supreme", "Supreme Court"), ("mayor", "Mayor"), ("treasurer", "Treasurer"), ("auditor", "Auditor"),
                ("lieutenant", "Lt. Governor"), ("commission", "Commission")]
STATE_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"}

# ------------------------------------------------------------------ Ad-ID structure
WEEKDAY_TAIL = re.compile(r"(M|Tu|W|Th|F|Sa|Su)\d{0,2}$")     # a glued tail has at most a 2-digit slot; MADF2602 is a code, not MAD + F2602


def family(ad_id):
    """Spot family key. Several station invoice layouts glue a weekday token and a slot digit onto the
    Ad-ID (RSFI2615000H -> RSFI2615000HTu1, RSFI2615000HW2 ...): 49,563 creatives collapse to ~2,200 real
    spots. The HD suffix (H) and HW1-style variants of the same spot stay in one family too."""
    core = WEEKDAY_TAIL.sub("", ad_id)
    core = re.sub(r"(H|HD|SD|TVH|TVHD)$", "", core)
    return core or ad_id


def family_number(key):
    m = re.search(r"(\d+)$", key)
    return int(m.group(1)) if m else 0


def slug(category, name):
    return f"{category}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


SLUG_SQL = "b.category || '-' || left(trim(both '-' from regexp_replace(lower(b.canonical_name), '[^a-z0-9]+', '-', 'g')), 60)"


def relink(con):
    """buyer_id is reassigned by every entity rebuild; the slug is the stable key. Refresh the convenience column,
    and drop match rows whose Ad-ID no longer exists (a parser fix can collapse or rename creatives)."""
    con.execute(f"UPDATE buyer_channel bc SET buyer_id = b.buyer_id FROM buyer b WHERE {SLUG_SQL} = bc.buyer_slug AND bc.buyer_id IS DISTINCT FROM b.buyer_id")
    n = con.execute("DELETE FROM creative_video v WHERE NOT EXISTS (SELECT 1 FROM creative c WHERE c.ad_id = v.ad_id)").rowcount
    con.commit()
    if n:
        log.info("pruned %d creative_video rows whose Ad-ID is gone", n)


# ------------------------------------------------------------------ small HTTP / cache helpers
def _cache_path(kind, key):
    os.makedirs(os.path.join(CACHE_DIR, kind), exist_ok=True)
    return os.path.join(CACHE_DIR, kind, re.sub(r"[^A-Za-z0-9_@.-]", "_", key) + ".json")


def cached(kind, key, fn, refresh=False, max_age_h=None):
    p = _cache_path(kind, key)
    if not refresh and os.path.exists(p):
        if max_age_h is None or time.time() - os.path.getmtime(p) < max_age_h * 3600:
            return json.load(open(p))
    v = fn()
    json.dump(v, open(p, "w"))
    return v


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def api_key():
    k = os.environ.get("YOUTUBE_API_KEY")
    if k:
        return k
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            m = re.match(r"\s*(?:export\s+)?YOUTUBE_API_KEY\s*=\s*(.*)$", line)      # shell-style `export KEY=...` and quotes are fine
            if m:
                return m.group(1).strip().strip("'\"") or None
    return None


# ------------------------------------------------------------------ YouTube Data API v3 (keyed path)
class ApiQuotaError(RuntimeError):
    """The key is invalid, not enabled for the YouTube Data API, or out of quota: stop the run, do not fall back."""


def api_get(method, **params):
    params["key"] = api_key()
    try:
        return json.loads(http_get("https://www.googleapis.com/youtube/v3/" + method + "?" + urllib.parse.urlencode(params)))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace")).get("error", {})
        except Exception:
            err = {}
        reason = ",".join(x.get("reason", "") for x in err.get("errors", [])) or str(e.code)
        if e.code in (400, 403) and re.search(r"quota|dailyLimit|keyInvalid|badRequest|accessNotConfigured|forbidden|API_KEY|rateLimit", reason + " " + err.get("message", ""), re.I):
            raise ApiQuotaError(f"YouTube Data API refused the request ({e.code} {reason}): {err.get('message', '')[:200]}") from None
        raise


def validate_api_key():
    """One videos.list call (1 quota unit) so a bad key fails before any work."""
    r = api_get("videos", part="id", id="dQw4w9WgXcQ")
    if "items" not in r:
        raise ApiQuotaError(f"unexpected API response: {str(r)[:200]}")


def buyers_with_approx_dates(con, min_share=0.2):
    """Buyer ids whose channel's ad-length uploads mostly lack an exact date: the keyless listing gave only
    "2 months ago" and the watch-page lookup failed (soft block). Read from the listing and date caches."""
    out = set()
    first = dict(con.execute("SELECT buyer_id, MIN(first_aired) FROM creative GROUP BY 1").fetchall())
    for bid, cid in con.execute("SELECT buyer_id, channel_id FROM buyer_channel WHERE source IN ('youtube','override') AND buyer_id IS NOT NULL"):
        p = _cache_path("uploads", cid)
        if not os.path.exists(p) or not first.get(bid):
            continue
        since = (first[bid] - datetime.timedelta(days=60)).isoformat()     # the window channel_uploads() looks at
        ads = [u for u in json.load(open(p)).get("uploads", []) if u.get("duration") and AD_MIN <= u["duration"] <= AD_MAX
               and (not u.get("upload_date") or u["upload_date"] >= since)][:80]
        if not ads:
            continue
        missing = sum(1 for u in ads if not u.get("exact") and not os.path.exists(_cache_path("dates", u["id"])))
        if missing / len(ads) > min_share:
            out.add(bid)
    return out


def iso_duration(s):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def api_search_channels(q):
    r = api_get("search", part="snippet", type="channel", q=q, maxResults=10, regionCode="US")
    return [{"channel_id": it["snippet"]["channelId"], "title": it["snippet"]["title"], "hits": 1} for it in r.get("items", [])]


def api_uploads(channel_id, max_n=400):
    """Long-form uploads only: playlist UULF<id> is the channel's Videos tab without Shorts (UU<id> would include
    them, and Shorts are under 60 s, so they flood the ad-length candidates: 106 of Tom Tiffany's 144 uploads).
    Falls back to the full uploads playlist if a channel has no UULF list."""
    out, token = [], None
    pl = "UULF" + channel_id[2:]
    try:
        api_get("playlistItems", part="id", playlistId=pl, maxResults=1)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        pl = "UU" + channel_id[2:]
    while len(out) < max_n:
        try:
            r = api_get("playlistItems", part="snippet,contentDetails", playlistId=pl, maxResults=50, **({"pageToken": token} if token else {}))
        except urllib.error.HTTPError as e:
            if e.code == 404:                                  # a channel with no public uploads has no uploads playlist
                return out
            raise
        ids = [it["contentDetails"]["videoId"] for it in r.get("items", [])]
        if not ids:
            break
        v = api_get("videos", part="contentDetails,snippet", id=",".join(ids))
        for it in v.get("items", []):
            th = it["snippet"].get("thumbnails", {})
            out.append({"id": it["id"], "title": it["snippet"]["title"], "duration": iso_duration(it["contentDetails"].get("duration")),
                        "upload_date": it["snippet"]["publishedAt"][:10], "exact": True,
                        "thumb": (th.get("high") or th.get("medium") or th.get("default") or {}).get("url")})
        token = r.get("nextPageToken")
        if not token:
            break
    return out


# ------------------------------------------------------------------ yt-dlp (keyless path, metadata only)
_ydl = None


def ydl():
    global _ydl
    if _ydl is None:
        import yt_dlp
        _ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "ignoreerrors": True,
                                 "extractor_args": {"youtubetab": {"approximate_date": [""]}}, "logger": logging.getLogger("yt_dlp")})
    return _ydl


def ytdlp_search(q, n=15):
    """Keyless channel discovery: the channels behind the top video results for a name query."""
    try:
        info = ydl().extract_info(f"ytsearch{n}:{q}", download=False) or {}
    except Exception as e:                                   # network, parse changes: degrade, do not crash the run
        log.warning("ytsearch failed for %r: %s", q, e); return []
    out = []
    for e in info.get("entries") or []:
        if e and e.get("channel_id"):
            out.append({"channel_id": e["channel_id"], "title": e.get("channel") or e.get("uploader") or "", "video_title": e.get("title") or "",
                        "duration": e.get("duration"), "ts": e.get("timestamp")})
    return out


def ytdlp_uploads(channel_id):
    try:
        info = ydl().extract_info(f"https://www.youtube.com/channel/{channel_id}/videos", download=False) or {}
    except Exception as e:
        log.warning("listing failed for %s: %s", channel_id, e); return {"title": None, "handle": None, "uploads": []}
    ups = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        ts = e.get("timestamp")
        th = e.get("thumbnails") or []
        ups.append({"id": e["id"], "title": e.get("title") or "", "duration": e.get("duration"),
                    "upload_date": datetime.date.fromtimestamp(ts).isoformat() if ts else None, "exact": False,
                    "thumb": (th[-1].get("url") if th else None) or f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg", "views": e.get("view_count")})
    return {"title": info.get("channel") or info.get("title"), "handle": info.get("uploader_id"), "followers": info.get("channel_follower_count"), "uploads": ups}


_backoff = {"until": 0.0}


def exact_upload_date(video_id):
    """uploadDate from the public watch page (itemprop meta); one GET, no player; successes cached forever,
    failures never. YouTube answers 429 to bursts: one request per second, and a 90 s pause after a 429."""
    p = _cache_path("dates", video_id)
    if os.path.exists(p):
        return json.load(open(p)).get("upload_date")
    if time.time() < _backoff["until"]:
        return None
    for attempt in range(2):
        try:
            html = http_get(f"https://www.youtube.com/watch?v={video_id}")
        except Exception as e:
            if "429" in str(e):
                log.warning("watch page %s: 429, pausing 90 s", video_id); time.sleep(90 if attempt == 0 else 0)
                if attempt == 1:
                    _backoff["until"] = time.time() + 300; return None
                continue
            log.warning("watch page %s: %s", video_id, e); return None
        m = re.search(r'itemprop="uploadDate" content="([^"]+)"', html) or re.search(r'"uploadDate":"([^"]+)"', html)
        if not m:
            return None
        json.dump({"upload_date": m.group(1)[:10]}, open(p, "w"))
        time.sleep(1.0)
        return m.group(1)[:10]
    return None


# ------------------------------------------------------------------ buyers and their creatives
def load_buyers(con, top=None, ids=None):
    sql = """SELECT b.buyer_id, b.canonical_name, b.category, b.kind, b.party, b.office, b.state, b.fec_committee_id, b.fec_committee_name,
                    SUM(c.airings) airings, COUNT(*) n
             FROM creative c JOIN buyer b USING (buyer_id) GROUP BY 1,2,3,4,5,6,7,8,9 ORDER BY airings DESC"""
    rows = con.execute(sql).fetchall()
    if ids:
        rows = [r for r in rows if r[0] in ids]
    elif top:
        rows = rows[:top]
    keys = ("buyer_id", "name", "category", "kind", "party", "office", "state", "fec_committee_id", "fec_committee_name", "airings", "n")
    out = [dict(zip(keys, r)) for r in rows]
    for b in out:
        b["slug"] = slug(b["category"], b["name"])
    return out


def load_families(con, buyer_id):
    fams = collections.OrderedDict()
    for ad, n, fa, la in con.execute("SELECT ad_id, airings, first_aired, last_aired FROM creative WHERE buyer_id=%s ORDER BY first_aired, ad_id", (buyer_id,)):
        f = fams.setdefault(family(ad), {"key": family(ad), "ids": [], "airings": 0, "first": None, "last": None})
        f["ids"].append(ad); f["airings"] += n or 0
        if fa: f["first"] = min(fa, f["first"] or fa)
        if la: f["last"] = max(la, f["last"] or la)
    # junk filter: some invoice layouts leak program names into the Ad-ID column ("Tennis", "GUNSMOKE", 1 airing each)
    out = [f for f in fams.values() if f["first"] and not re.search(r"[a-z]", f["key"]) and (re.search(r"\d", f["key"]) or f["airings"] >= 3)]
    out.sort(key=lambda f: (f["first"], family_number(f["key"])))
    return out


def dominant_length(con, buyer_id):
    r = con.execute("""SELECT ol.length_sec, SUM(ol.spots) FROM order_line ol JOIN order_ o USING (order_id)
                       WHERE o.buyer_id=%s AND ol.length_sec IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (buyer_id,)).fetchone()
    return r[0] if r else None


# ------------------------------------------------------------------ buyer -> channel
def office_word(office):
    s = (office or "").lower()
    for k, w in OFFICE_WORDS:
        if k in s:
            return w
    return None


def name_variants(b):
    v = [b["name"]]
    if b["fec_committee_name"]:
        v.append(b["fec_committee_name"].title())
    ow = office_word(b["office"])
    if b["kind"] == "candidate":
        if ow: v.append(f"{b['name']} for {ow}")
        if b["state"]: v.append(f"{b['name']} for {STATE_NAMES.get(b['state'], b['state'])}")
    return v


def channel_queries(b):
    ow, st = office_word(b["office"]), STATE_NAMES.get(b["state"] or "", "")
    qs = []
    if b["kind"] == "candidate":
        qs.append(" ".join(x for x in (b["name"], "for", ow or st) if x))
        qs.append(" ".join(x for x in (b["name"], st, ow, "ad") if x))
    else:
        qs.append(b["name"] + " ad")
        if b["fec_committee_name"] and fuzz.token_set_ratio(b["fec_committee_name"], b["name"]) < 90:
            qs.append(b["fec_committee_name"].title())
    return [q for i, q in enumerate(qs) if q and q not in qs[:i]]


CHANNEL_FILLER = {"for", "the", "of", "and", "official", "campaign", "committee", "pac", "inc", "team", "friends", "elect", "vote", "tv", "channel",
                  "governor", "senate", "senator", "congress", "house", "mayor", "justice", "court", "attorney", "general", "state", "us", "u", "s"}


NICKNAMES = [("richard", "rick", "dick", "rich"), ("michael", "mike"), ("robert", "rob", "bob", "bobby"), ("jonathan", "jon"), ("joshua", "josh"), ("thomas", "tom"),
             ("william", "bill", "will"), ("james", "jim", "jimmy"), ("daniel", "dan", "danny"), ("christopher", "chris"), ("matthew", "matt"), ("joseph", "joe"),
             ("anthony", "tony"), ("andrew", "andy", "drew"), ("edward", "ed", "eddie"), ("timothy", "tim"), ("benjamin", "ben"), ("samuel", "sam"), ("nicholas", "nick"),
             ("elizabeth", "liz", "beth"), ("katherine", "kate", "katie", "kathy"), ("jennifer", "jen"), ("patricia", "pat"), ("margaret", "meg", "maggie"), ("deborah", "deb"),
             ("zachary", "zach"), ("abdul", "abdul"), ("stephen", "steve"), ("steven", "steve"), ("gregory", "greg"), ("kenneth", "ken"), ("ronald", "ron"), ("donald", "don"),
             ("charles", "charlie", "chuck"), ("peter", "pete"), ("alexander", "alex"), ("rebecca", "becca", "becky"), ("susan", "sue"), ("victoria", "vicky", "tori")]


def nick_tokens(name):
    toks = set(re.findall(r"[a-z]+", name.lower()))
    for group in NICKNAMES:
        if toks & set(group):
            toks |= set(group)
    return toks


def score_channel(b, title, hits, video_titles):
    """0-1: how likely this channel is the buyer's own. Name similarity is token-set based (so "Perry Johnson for
    Governor" matches "Perry Johnson"), but every token in the channel title that is neither in the buyer's names nor
    campaign filler costs 30% ("North American Mission Board" is not "American Mission")."""
    if not title or NEWSY.search(title) or CALLSIGN.search(title):
        return 0.0, "newsy"
    variants = name_variants(b)
    from .video_google import GENERIC
    distinct = {t for v in variants for t in nick_tokens(v) if len(t) >= 4 and t not in CHANNEL_FILLER and t not in GENERIC}
    flat = re.sub(r"[^a-z0-9]", "", title.lower())
    if distinct and not any(t in flat for t in distinct):
        return 0.0, "no name token in title"                     # "Maga Ky" is not the channel "Ky"
    sim = max(fuzz.token_set_ratio(title, v) for v in variants) / 100
    known = {t for v in variants for t in nick_tokens(v)} | {t for v in variants for t in re.findall(r"[0-9]+", v)} | CHANNEL_FILLER | set(STATE_NAMES.get(b["state"] or "", "").lower().split())
    sig = [t for t in known if len(t) >= 4 and t not in CHANNEL_FILLER]
    extra = [t for t in re.findall(r"[a-z0-9]+", title.lower()) if t not in known and not any(k in t for k in sig)]   # "TrebleForAZ" carries "treble"
    sim *= 0.6 ** len(extra)
    tokens = [t for t in re.findall(r"[a-z]+", b["name"].lower()) if len(t) > 2]
    surname = tokens[-1] if tokens else ""
    if b["kind"] != "candidate":
        surname = b["name"].lower().strip()                     # groups: the whole name has to appear
    in_title = bool(surname) and surname in title.lower()
    mention = sum(1 for t in video_titles if surname and surname in t.lower()) / max(1, len(video_titles)) if video_titles else 0
    conf = 0.55 * sim + 0.2 * min(hits, 4) / 4 + 0.15 * (1 if in_title else 0) + 0.10 * mention
    ev = f"sim={sim:.2f} hits={hits} name_in_title={int(in_title)} mention={mention:.2f}" + (f" extra={'+'.join(extra)}" if extra else "")
    return round(min(conf, 1.0), 3), ev


class SearchBudgetSpent(RuntimeError):
    """This run's allowance of new (uncached) API searches is used up; the rest wait for the next run."""


class SearchBudget:
    """New API searches cost 100 quota units each (cached ones are free); cap them per run."""
    def __init__(self, n=None):
        self.left, self.used = n, 0

    def take(self):
        if self.left is not None and self.left <= 0:
            raise SearchBudgetSpent()
        self.used += 1
        if self.left is not None:
            self.left -= 1


def find_channel(b, refresh=False, budget=None):
    """Returns (channel dict or None, method). Uses the API when a key is configured, else yt-dlp search.
    On the API path the queries run one at a time and stop as soon as one finds a channel that passes,
    since each new search costs 100 units. ApiQuotaError and SearchBudgetSpent propagate to the caller."""
    cands = collections.defaultdict(lambda: {"hits": 0, "title": "", "video_titles": []})
    method = "api-search" if api_key() else "ytdlp-search"
    budget = budget or SearchBudget()

    def pick():
        best = None
        for cid, c in cands.items():
            conf, ev = score_channel(b, c["title"], c["hits"], c["video_titles"])
            if best is None or conf > best[0]:
                best = (conf, cid, c["title"], ev)
        return best

    for q in channel_queries(b):
        key = _cache_path("search", f"{method}-{q}")
        fresh = refresh or not os.path.exists(key) or time.time() - os.path.getmtime(key) >= 24 * 14 * 3600
        if method == "api-search" and fresh:
            budget.take()
        try:
            res = cached("search", f"{method}-{q}", lambda: (api_search_channels(q) if method == "api-search" else ytdlp_search(q)), refresh=refresh, max_age_h=24 * 14)
        except ApiQuotaError:
            raise
        except Exception as e:
            log.warning("search %r failed: %s", q, e); res = []
        for r in res:
            c = cands[r["channel_id"]]; c["hits"] += r.get("hits", 1); c["title"] = c["title"] or r["title"]
            if r.get("video_title"): c["video_titles"].append(r["video_title"])
        if method == "api-search":
            best = pick()
            if best and best[0] >= 0.6:
                break
    best = pick()
    if not best or best[0] < 0.6:
        return None, method
    conf, cid, title, ev = best
    return {"channel_id": cid, "title": title, "channel_url": f"https://www.youtube.com/channel/{cid}", "confidence": conf, "matched_by": f"{method}: {ev}"}, method


def upsert_channel(con, b, ch, source="youtube", uploads=None):
    """b: a buyer dict with slug and buyer_id, or (slug, buyer_id)."""
    sl, bid = (b["slug"], b["buyer_id"]) if isinstance(b, dict) else b
    con.execute("""INSERT INTO buyer_channel (buyer_slug, buyer_id, source, channel_id, channel_url, title, matched_by, confidence, uploads, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (buyer_slug, source) DO UPDATE SET buyer_id=EXCLUDED.buyer_id, channel_id=EXCLUDED.channel_id, channel_url=EXCLUDED.channel_url, title=EXCLUDED.title,
                     matched_by=EXCLUDED.matched_by, confidence=EXCLUDED.confidence, uploads=COALESCE(EXCLUDED.uploads, buyer_channel.uploads), updated_at=now()""",
                (sl, bid, source, ch["channel_id"], ch["channel_url"], ch.get("title"), ch.get("matched_by"), ch.get("confidence"), uploads))


def cmd_channels(con, st, buyers, refresh=False, rescore=False, max_searches=None):
    overrides = load_overrides()
    found = 0
    budget = SearchBudget(max_searches)
    for i, b in enumerate(buyers):
        st.attempt()
        sl = slug(b["category"], b["name"])
        if sl in overrides["channels"]:
            continue                                         # applied by cmd_overrides, which wins
        existing = con.execute("SELECT confidence FROM buyer_channel WHERE buyer_slug=%s AND source='youtube'", (b["slug"],)).fetchone()
        if existing and not (refresh or rescore):
            found += 1; continue
        if api_key() and len(re.sub(r"[^a-z]", "", b["name"].lower())) < 4:
            st.count("channels_skipped_short_name"); continue     # "Jb", "Fox": a 100-unit search would find nothing useful
        try:
            ch, method = find_channel(b, refresh=refresh, budget=budget)
        except (SearchBudgetSpent, ApiQuotaError) as e:
            have = {r[0] for r in con.execute("SELECT buyer_slug FROM buyer_channel WHERE source IN ('youtube','override')")}
            left = sum(1 for x in buyers[i:] if x["slug"] not in have and x["slug"] not in overrides["channels"])
            if isinstance(e, ApiQuotaError):
                st.fail(b["name"], str(e)); log.error("stopping channel search: %s (%d buyers still to search)", e, left)
            else:
                log.info("channels: search budget of %s spent; %d buyers still to search (cached results are reused next run)", max_searches, left)
            st.count("channels_deferred", left); break
        if ch:
            upsert_channel(con, b, ch); con.commit(); found += 1
            log.info("channel  %-40s -> %s (%s) conf=%.2f", b["name"][:40], ch["title"], ch["channel_id"], ch["confidence"])
            st.count("channels_found")
        else:
            con.execute("DELETE FROM buyer_channel WHERE buyer_slug=%s AND source='youtube'", (b["slug"],))
            con.execute("DELETE FROM creative_video WHERE source='youtube' AND ad_id IN (SELECT ad_id FROM creative WHERE buyer_id=%s)", (b["buyer_id"],)); con.commit()
            log.info("channel  %-40s -> none (%s)", b["name"][:40], method)
            st.count("channels_none")
        st.progress(i + 1, len(buyers), every=25, label="channels")
    st.count("api_searches", budget.used)
    log.info("channels: %d of %d buyers have one; %d new API searches (%d quota units)", found, len(buyers), budget.used, 100 * budget.used)


# ------------------------------------------------------------------ creative -> video
def date_score(up, fam):
    if not up.get("upload_date"):
        return 0.0
    d = datetime.date.fromisoformat(up["upload_date"])
    delta = (d - fam["first"]).days                           # upload minus first airing
    if d > fam["last"] + datetime.timedelta(days=5):
        return 0.0
    if up.get("exact"):
        a = abs(delta)
        if -7 <= delta <= 3: return 1.0
        if a <= 7: return 0.85
        if a <= 14: return 0.6
        if a <= 30: return 0.3
        return 0.0
    a = abs(delta)                                            # approximate ("2 months ago"): wide, weak
    return 0.55 if a <= 20 else 0.35 if a <= 45 else 0.0


def duration_score(up, dom):
    """1.0 for the buyer's dominant spot length or a standard TV length (15/30/60, also 10/45/90),
    0.35 for other ad-length uploads (digital cuts: 19 s, 53 s, 65 s), 0 outside the ad range."""
    du = up.get("duration")
    if du is None or not (AD_MIN <= du <= AD_MAX):
        return 0.0
    if dom and abs(du - dom) <= 2:
        return 1.0
    return 1.0 if any(abs(du - L) <= 2 for L in STD_LENGTHS) else 0.35


def adness(up, b):
    t = (up.get("title") or "").lower()
    toks = [x for x in re.findall(r"[a-z]+", b["name"].lower()) if len(x) > 2]
    if re.search(r"\b(ad|spot|tv|:\d\d|\d\ds|commercial)\b", t) or any(x in t for x in toks):
        return 1.0
    return 0.7


def pair_score(up, fam, b, dom):
    ds = date_score(up, fam)
    if ds == 0:
        return 0.0
    return ds * (0.5 + 0.35 * duration_score(up, dom) + 0.15 * adness(up, b))


def align(fams, ups, b, dom):
    """Order-consistent assignment (no crossings) maximising the total pair score; gaps are free.
    Returns {family index: (upload index, score)}."""
    n, m = len(fams), len(ups)
    S = [[pair_score(u, f, b, dom) for u in ups] for f in fams]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cand = [(best[i - 1][j], "u"), (best[i][j - 1], "l")]
            if S[i - 1][j - 1] > 0:
                cand.append((best[i - 1][j - 1] + S[i - 1][j - 1], "d"))
            best[i][j], back[i][j] = max(cand)
    out, i, j = {}, n, m
    while i > 0 and j > 0 and back[i][j]:
        if back[i][j] == "d":
            out[i - 1] = (j - 1, S[i - 1][j - 1]); i -= 1; j -= 1
        elif back[i][j] == "u":
            i -= 1
        else:
            j -= 1
    return out, S


def channel_uploads(channel_id, refresh=False, detail_cap=80, since=None):
    """Ad-length uploads with exact dates where we can get them (API: always; yt-dlp: watch page per video)."""
    if api_key():
        data = cached("uploads", "api-" + channel_id, lambda: {"uploads": api_uploads(channel_id)}, refresh=refresh, max_age_h=24)
        ups = data["uploads"]
        for u in ups:                                         # share exact dates with the keyless path's cache
            p = _cache_path("dates", u["id"])
            if u.get("upload_date") and not os.path.exists(p):
                json.dump({"upload_date": u["upload_date"]}, open(p, "w"))
    else:
        data = cached("uploads", channel_id, lambda: ytdlp_uploads(channel_id), refresh=refresh, max_age_h=24)
        ups = data["uploads"]
    ads = [u for u in ups if u.get("duration") and AD_MIN <= u["duration"] <= AD_MAX]
    if since:                                                  # approximate dates can be a month off; keep a margin
        ads = [u for u in ads if not u.get("upload_date") or datetime.date.fromisoformat(u["upload_date"]) >= since - datetime.timedelta(days=60)]
    for u in [u for u in ads if not u.get("exact")][:detail_cap]:
        d = exact_upload_date(u["id"])
        if d:
            u["upload_date"], u["exact"] = d, True
    ads.sort(key=lambda u: u.get("upload_date") or "9")
    return ads, len(ups), data


def write_matches(con, fam, b, best, runner, ups, channel_title):
    con.execute("DELETE FROM creative_video WHERE source='youtube' AND ad_id = ANY(%s)", (fam["ids"],))
    for rank, (ui, score, conf, signals) in enumerate([best] + ([runner] if runner else []), start=1):
        u = ups[ui]
        notes = f"family {fam['key']} ({len(fam['ids'])} ad-ids, {fam['airings']} airings); channel {channel_title}; pair={score:.2f}"
        for ad in fam["ids"]:
            con.execute("""INSERT INTO creative_video (ad_id, rank, source, video_url, embed_url, thumb_url, title, duration_sec, published_at, confidence, matched_by, notes, updated_at)
                           VALUES (%s,%s,'youtube',%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT (ad_id, rank) DO UPDATE SET source=EXCLUDED.source, video_url=EXCLUDED.video_url, embed_url=EXCLUDED.embed_url, thumb_url=EXCLUDED.thumb_url,
                             title=EXCLUDED.title, duration_sec=EXCLUDED.duration_sec, published_at=EXCLUDED.published_at, confidence=EXCLUDED.confidence,
                             matched_by=EXCLUDED.matched_by, notes=EXCLUDED.notes, updated_at=now()""",
                        (ad, rank, f"https://www.youtube.com/watch?v={u['id']}", f"https://www.youtube-nocookie.com/embed/{u['id']}",
                         f"https://i.ytimg.com/vi/{u['id']}/mqdefault.jpg", u.get("title"), u.get("duration"), u.get("upload_date"),
                         conf, signals, notes))


def match_buyer(con, st, b, ch, refresh=False, detail_cap=80):
    fams = load_families(con, b["buyer_id"])
    if not fams:
        return 0
    dom = dominant_length(con, b["buyer_id"])
    ups, total, data = channel_uploads(ch["channel_id"], refresh=refresh, detail_cap=detail_cap, since=fams[0]["first"])
    con.execute("UPDATE buyer_channel SET uploads=%s, title=COALESCE(%s, title) WHERE buyer_slug=%s AND source='youtube'", (len(ups), data.get("title"), b["slug"]))
    if not ups:
        for f in fams:
            con.execute("DELETE FROM creative_video WHERE source='youtube' AND ad_id = ANY(%s)", (f["ids"],))
        con.commit()
        log.info("videos   %-40s: %d families, no ad-length uploads among %d", b["name"][:40], len(fams), total)
        return 0
    assign, S = align(fams, ups, b, dom)
    exact_share = sum(1 for u in ups if u.get("exact")) / len(ups)
    matched = 0
    for i, f in enumerate(fams):
        row = sorted(((S[i][j], j) for j in range(len(ups)) if S[i][j] > 0), reverse=True)
        best = runner = None
        if i in assign:
            j, s = assign[i]
            second = next((sc for sc, jj in row if jj != j), 0.0)
            gap = s - second
            margin = 1.0 if gap >= 0.2 else 0.85 if gap >= 0.08 else 0.7 if gap > 0.001 else 0.55   # a dead tie (same-day batch upload) stays medium
            conf = s * margin
            if not ups[j].get("exact"):
                conf = min(conf, 0.45)
            if dom and abs((ups[j].get("duration") or 0) - dom) > 2:
                conf = min(conf, 0.6)                        # a digital cut, not the length the station billed
            if len(fams) > 1 and len(ups) > 1:
                conf = min(1.0, conf + 0.05)                 # order-consistent alignment adds a little
            signals = ",".join(x for x, on in (("date", True), ("duration", duration_score(ups[j], dom) >= 1.0), ("order", len(fams) > 1), ("title", adness(ups[j], b) >= 1.0), ("exact-date", bool(ups[j].get("exact")))) if on)
            best = (j, s, round(conf, 3), signals)
            if second > 0:
                jj = next(jj for sc, jj in row if jj != j)
                runner = (jj, second, round(second * 0.6, 3), "runner-up")
            matched += 1
        elif row:                                            # unassigned (the DP preferred a neighbour): keep the best as a low-confidence guess
            s, j = row[0]
            best = (j, s, round(min(s * 0.5, 0.35), 3), "date,unaligned")
        if best:
            write_matches(con, f, b, best, runner, ups, data.get("title") or ch.get("title"))
            st.count("families_matched" if best[2] >= 0.4 else "families_low")
        else:
            con.execute("DELETE FROM creative_video WHERE source='youtube' AND ad_id = ANY(%s)", (f["ids"],))
            st.count("families_unmatched")
    con.commit()
    log.info("videos   %-40s: %d/%d families aligned, %d ad-length uploads (%.0f%% exact dates) of %d",
             b["name"][:40], matched, len(fams), len(ups), 100 * exact_share, total)
    return matched


def cmd_videos(con, st, buyers, refresh=False, detail_cap=80):
    for i, b in enumerate(buyers):
        st.attempt()
        ch = con.execute("""SELECT channel_id, title, source FROM buyer_channel WHERE buyer_slug=%s AND source IN ('youtube','override') ORDER BY (source='override') DESC, confidence DESC NULLS LAST LIMIT 1""", (b["slug"],)).fetchone()
        if not ch:
            st.count("buyers_without_channel"); continue
        try:
            match_buyer(con, st, b, {"channel_id": ch[0], "title": ch[1]}, refresh=refresh, detail_cap=detail_cap)
        except ApiQuotaError as e:
            con.rollback(); st.fail(b["name"], str(e)); log.error("stopping: %s (%d buyers left; rerun later, cached work is kept)", e, len(buyers) - i)
            break
        except Exception as e:
            con.rollback(); st.fail(b["name"], f"{type(e).__name__}: {e}"); log.exception("match failed for %s", b["name"])
        st.progress(i + 1, len(buyers), every=25, label="videos")


# ------------------------------------------------------------------ overrides and link-out sources
def load_overrides():
    """data/video_overrides.yaml. Flat `KEY: url` lines: an Ad-ID (or spot family key) maps to a video,
    a buyer slug (category-name) to a channel. Sectioned `creatives:` / `channels:` maps work too."""
    out = {"creatives": {}, "channels": {}}
    if not os.path.exists(OVERRIDES):
        return out
    import yaml
    doc = yaml.safe_load(open(OVERRIDES)) or {}
    flat = {k: v for k, v in doc.items() if k not in ("creatives", "channels")}
    for k, v in {**flat, **(doc.get("creatives") or {}), **(doc.get("channels") or {})}.items():
        if not v:
            continue
        k = str(k).strip()
        if re.match(r"^(federal|state|local|issue|other)-", k) or k in (doc.get("channels") or {}):
            out["channels"][k] = str(v).strip()                 # a channel url, or "none" to block an automatic pick
        else:
            out["creatives"][k.upper()] = str(v).strip()
    return out


def video_fields(url):
    """(source, video_url, embed_url, thumb_url) for an override URL; only YouTube embeds."""
    m = re.search(r"(?:youtu\.be/|v=|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url)
    if m:
        vid = m.group(1)
        return "youtube", f"https://www.youtube.com/watch?v={vid}", f"https://www.youtube-nocookie.com/embed/{vid}", f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
    if "adstransparency.google.com" in url:
        return "google-ads", url, None, None
    if "ispot.tv" in url:
        return "ispot", url, None, None
    return "override", url, None, None


def resolve_channel_url(url):
    """Channel id for a channel URL or handle (yt-dlp listing, cached)."""
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", url)
    if m:
        return m.group(1), None
    key = url if url.startswith("http") else f"https://www.youtube.com/{url if url.startswith('@') else '@' + url}"
    try:
        info = ydl().extract_info(key.rstrip("/") + "/videos", download=False) or {}
        return info.get("channel_id"), info.get("channel") or info.get("title")
    except Exception as e:
        log.warning("cannot resolve channel %s: %s", url, e); return None, None


def cmd_overrides(con, st):
    ov = load_overrides()
    bslug = {slug(r[1], r[0]): r[2] for r in con.execute("SELECT canonical_name, category, buyer_id FROM buyer")}
    for sl, url in ov["channels"].items():
        bid = bslug.get(sl)
        if not bid:
            st.warn("override channel for unknown buyer slug %s", sl); continue
        if url.lower() in ("none", "null", "no", "-"):
            con.execute("DELETE FROM buyer_channel WHERE buyer_slug=%s AND source IN ('youtube','override')", (sl,))
            con.execute("DELETE FROM creative_video WHERE source='youtube' AND ad_id IN (SELECT ad_id FROM creative WHERE buyer_id=%s)", (bid,))
            st.count("channel_blocked"); continue
        cid, title = resolve_channel_url(url)
        if not cid:
            st.fail(sl, "channel url did not resolve"); continue
        upsert_channel(con, (sl, bid), {"channel_id": cid, "channel_url": f"https://www.youtube.com/channel/{cid}", "title": title, "confidence": 1.0, "matched_by": f"override: {url}"}, source="override")
        st.count("channel_overrides")
    fam_ids = collections.defaultdict(list)
    for (ad,) in con.execute("SELECT ad_id FROM creative"):
        fam_ids[family(ad)].append(ad); fam_ids[ad].append(ad)
    for key, url in ov["creatives"].items():
        ids = fam_ids.get(key) or fam_ids.get(family(key))
        if not ids:
            st.warn("override for unknown Ad-ID %s", key); continue
        source, vurl, eurl, turl = video_fields(url)
        for ad in ids:
            con.execute("DELETE FROM creative_video WHERE ad_id=%s", (ad,))
            con.execute("""INSERT INTO creative_video (ad_id, rank, source, video_url, embed_url, thumb_url, confidence, matched_by, notes)
                           VALUES (%s,1,%s,%s,%s,%s,1.0,'override',%s)""", (ad, source, vurl, eurl, turl, f"data/video_overrides.yaml: {key}"))
        st.count("creative_overrides")
    con.commit()
    log.info("overrides applied: %d channels, %d creatives", len(ov["channels"]), len(ov["creatives"]))


def cmd_google_ads(con, st, buyers, refresh=False):
    """Second source: Google's political ads transparency bundle (see ingest/video_google.py). Link-outs and a cross-check."""
    from . import video_google
    try:
        video_google.run(con, st, buyers, refresh=refresh)
    except Exception as e:                                   # a Google outage must not sink the YouTube run
        con.rollback(); st.fail("google-ads", f"{type(e).__name__}: {e}"); log.exception("google ads step failed")


# ------------------------------------------------------------------ report
def tier(c):
    return "high" if c is not None and c >= 0.7 else "medium" if c is not None and c >= 0.4 else "low"


def cmd_report(con, places=(("Des Moines 50309", "50309"), ("Atlanta 30303", "30303"))):
    q = lambda s, *p: con.execute(s, p).fetchall()
    out = {}
    out["buyers_total"] = q("SELECT COUNT(DISTINCT buyer_id) FROM creative")[0][0]
    out["channels"] = q("SELECT source, COUNT(*) FROM buyer_channel GROUP BY 1")
    out["channels_by_category"] = q(f"""SELECT b.category, COUNT(DISTINCT b.buyer_id) buyers, COUNT(DISTINCT bc.buyer_slug) with_channel,
                                              COUNT(DISTINCT bc.buyer_slug) FILTER (WHERE bc.uploads > 0) with_ad_uploads
                                       FROM buyer b JOIN (SELECT DISTINCT buyer_id FROM creative) c USING (buyer_id)
                                       LEFT JOIN buyer_channel bc ON bc.buyer_slug={SLUG_SQL} AND bc.source IN ('youtube','override') GROUP BY 1 ORDER BY 1""")
    out["families_total"] = len({family(r[0]) for r in q("SELECT ad_id FROM creative")})
    out["creatives_total"], out["airings_total"] = q("SELECT COUNT(*), SUM(airings) FROM creative")[0]
    out["by_tier"] = q("""SELECT CASE WHEN confidence>=0.7 THEN 'high' WHEN confidence>=0.4 THEN 'medium' ELSE 'low' END t, COUNT(*) creatives, SUM(c.airings) airings
                          FROM creative_video v JOIN creative c USING (ad_id) WHERE rank=1 GROUP BY 1 ORDER BY 1""")
    out["by_category"] = q("""SELECT b.category, COUNT(*) creatives, SUM(c.airings) airings,
                                     COUNT(v.ad_id) matched, SUM(c.airings) FILTER (WHERE v.ad_id IS NOT NULL) matched_airings,
                                     COUNT(v.ad_id) FILTER (WHERE v.confidence>=0.7) high, SUM(c.airings) FILTER (WHERE v.confidence>=0.7) high_airings
                              FROM creative c JOIN buyer b USING (buyer_id) LEFT JOIN creative_video v ON v.ad_id=c.ad_id AND v.rank=1 AND v.embed_url IS NOT NULL
                              GROUP BY 1 ORDER BY 1""")
    out["sources"] = q("""SELECT v.source, v.rank, CASE WHEN v.confidence>=0.7 THEN 'high' WHEN v.confidence>=0.4 THEN 'medium' ELSE 'low' END, COUNT(*), SUM(c.airings)
                          FROM creative_video v JOIN creative c USING (ad_id) GROUP BY 1,2,3 ORDER BY 1,2,3""")
    out["google_by_category"] = q("""SELECT b.category, SUM(c.airings) airings,
                                            SUM(c.airings) FILTER (WHERE y.ad_id IS NOT NULL) youtube, SUM(c.airings) FILTER (WHERE g.ad_id IS NOT NULL) google_any,
                                            SUM(c.airings) FILTER (WHERE y.ad_id IS NULL AND g.ad_id IS NOT NULL) google_only,
                                            SUM(c.airings) FILTER (WHERE y.matched_by LIKE '%%google%%') yt_crosschecked
                                     FROM creative c JOIN buyer b USING (buyer_id)
                                     LEFT JOIN creative_video y ON y.ad_id=c.ad_id AND y.rank=1 AND y.source='youtube'
                                     LEFT JOIN (SELECT DISTINCT ad_id FROM creative_video WHERE source='google-ads') g ON g.ad_id=c.ad_id
                                     GROUP BY 1 ORDER BY 1""")
    out["google_advertisers"] = q(f"""SELECT b.category, COUNT(DISTINCT {SLUG_SQL}), COUNT(DISTINCT bc.buyer_slug), COUNT(DISTINCT bc.buyer_slug) FILTER (WHERE bc.matched_by LIKE 'fec%%')
                                      FROM (SELECT buyer_id, SUM(airings) a FROM creative GROUP BY 1 ORDER BY 2 DESC LIMIT 300) t JOIN buyer b USING (buyer_id)
                                      LEFT JOIN buyer_channel bc ON bc.buyer_slug={SLUG_SQL} AND bc.source='google-ads' GROUP BY 1 ORDER BY 1""")
    zips = json.load(open(os.path.join(ROOT, "web", "data", "places.json"))).get("zips", {})
    out["places"] = []
    for label, z in places:
        if z not in zips:
            continue
        lat, lon = zips[z]
        r = q("""WITH facs AS (SELECT facility_id FROM station WHERE contour IS NOT NULL AND ST_Contains(contour, ST_SetSRID(ST_Point(%s,%s),4326)))
                 SELECT COUNT(*) airings, COUNT(*) FILTER (WHERE v.embed_url IS NOT NULL) playable,
                        COUNT(*) FILTER (WHERE v.embed_url IS NOT NULL AND v.confidence>=0.7) high,
                        COUNT(*) FILTER (WHERE v.embed_url IS NOT NULL AND v.confidence>=0.4) med_up,
                        COUNT(*) FILTER (WHERE v.ad_id IS NOT NULL) any_link, COUNT(*) FILTER (WHERE g.ad_id IS NOT NULL) google_seen, (SELECT COUNT(*) FROM facs)
                 FROM spot s JOIN facs USING (facility_id) LEFT JOIN creative_video v ON v.ad_id=s.ad_id AND v.rank=1
                 LEFT JOIN (SELECT DISTINCT ad_id FROM creative_video WHERE source='google-ads') g ON g.ad_id=s.ad_id WHERE s.ad_id IS NOT NULL""", lon, lat)[0]
        out["places"].append((label, *r))
    out["tail"] = q(f"""SELECT b.canonical_name, b.category, SUM(c.airings) a, COUNT(*) n, bool_or(bc.buyer_slug IS NOT NULL) has_channel,
                              COUNT(v.ad_id) matched
                       FROM creative c JOIN buyer b USING (buyer_id) LEFT JOIN buyer_channel bc ON bc.buyer_slug={SLUG_SQL} AND bc.source IN ('youtube','override')
                       LEFT JOIN creative_video v ON v.ad_id=c.ad_id AND v.rank=1
                       GROUP BY 1,2 ORDER BY a DESC""")
    return out


def print_report(r):
    print(f"buyers with creatives: {r['buyers_total']}; creatives {r['creatives_total']} in {r['families_total']} spot families; airings {r['airings_total']}")
    print("channels by source:", r["channels"])
    print("category  buyers  with_channel  with_ad_uploads"); [print("  ", *row) for row in r["channels_by_category"]]
    print("tier  creatives  airings"); [print("  ", *row) for row in r["by_tier"]]
    print("category  creatives  airings  matched  matched_airings  high  high_airings"); [print("  ", *row) for row in r["by_category"]]
    print("source rank tier creatives airings"); [print("  ", *row) for row in r["sources"]]
    print("google advertisers (top 300): category buyers matched by_fec"); [print("  ", *row) for row in r["google_advertisers"]]
    print("category airings youtube google_any google_only yt_crosschecked"); [print("  ", *row) for row in r["google_by_category"]]
    print("place  airings  playable  high  medium+  any_link  google_seen  stations"); [print("  ", *row) for row in r["places"]]
    t = r["tail"]; cum = 0; tot = sum(x[2] for x in t)
    print("tail (buyers ranked by airings: cumulative share, has channel, matched creatives)")
    for i, row in enumerate(t):
        cum += row[2]
        if i < 15 or i in (50, 100, 200, 300, 400, 500) or i == len(t) - 1:
            print(f"  #{i+1:<4} {row[0][:36]:<36} {row[1]:<8} airings={row[2]:<6} n={row[3]:<4} cum={100*cum/tot:5.1f}%  channel={int(row[4])} matched={row[5]}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="all", choices=["all", "channels", "videos", "overrides", "google-ads", "report"])
    ap.add_argument("--top", type=int, default=300, help="buyers by airings (default 300)")
    ap.add_argument("--buyers", help="comma-separated buyer ids")
    ap.add_argument("--refresh", action="store_true", help="ignore cached searches/listings")
    ap.add_argument("--rescore", action="store_true", help="channels: re-pick from the cached searches (after a scoring change)")
    ap.add_argument("--detail-cap", type=int, default=80, help="exact-date lookups per channel (keyless path)")
    ap.add_argument("--max-searches", type=int, help="channels: cap on new API searches this run (100 quota units each)")
    ap.add_argument("--approx", action="store_true", help="only buyers whose YouTube matches rest on approximate dates (rerun them through the API)")
    a = ap.parse_args()
    from .runlog import Stage
    ids = {int(x) for x in a.buyers.split(",")} if a.buyers else None
    if a.cmd == "report":
        with pg.connect() as con:
            print_report(cmd_report(con))
        return
    with Stage("video", args=vars(a), max_fail_rate=0.5) as st, pg.connect() as con:
        if not api_key():
            log.info("no YOUTUBE_API_KEY configured: using yt-dlp metadata + watch-page dates (keyless)")
        elif a.cmd in ("all", "channels", "videos"):
            validate_api_key(); log.info("YOUTUBE_API_KEY ok: using the YouTube Data API v3")
        relink(con)
        if a.approx:
            ids = (ids or set()) | buyers_with_approx_dates(con)
            log.info("--approx: %d buyers with approximate-date matches", len(ids))
        buyers = load_buyers(con, top=None if ids else a.top, ids=ids)
        if a.cmd in ("all", "channels"):
            cmd_channels(con, st, buyers, refresh=a.refresh, rescore=a.rescore, max_searches=a.max_searches)
        if a.cmd in ("all", "videos"):
            cmd_videos(con, st, buyers, refresh=a.refresh, detail_cap=a.detail_cap)
        if a.cmd in ("all", "google-ads"):
            cmd_google_ads(con, st, buyers, refresh=a.refresh)
        if a.cmd in ("all", "overrides", "channels", "videos", "google-ads"):
            cmd_overrides(con, st)
        for k, v in sorted(st.counts.items()):
            log.info("  %s=%s", k, v)


if __name__ == "__main__":
    main()

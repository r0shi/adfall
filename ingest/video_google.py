"""Google political ads (Transparency Report bundle) as a second source for the Ad-ID -> video chain.

  python3 -m ingest.video google-ads          # fetch the bundle if it changed, match advertisers and creatives
  python3 -m ingest.video google-ads --refresh

Source: https://storage.googleapis.com/political-csv/google-political-ads-transparency-bundle.zip, the public
download behind Google's Political Advertising Transparency Report (~313 MB zip, ~3.3 GB of CSV, refreshed
daily; no account, no key). The same tables are in BigQuery as `bigquery-public-data.google_political_ads`.

What it has: every election ad served on Google (YouTube included) with advertiser, type (VIDEO/TEXT/IMAGE),
first and last served dates, impression and spend buckets, geo targeting, and a link to the ad's page in the
Ads Transparency Center. What it lacks: the YouTube video id, so a Google match is a link-out, never an embed.

How it is used, per spot family of a matched buyer:
  - Candidates: the advertiser's VIDEO ads that started serving within +-5 days of the family's first airing and
    whose geo targeting includes a state the family aired in (or that are not geo-targeted to states at all).
  - If the family has a YouTube match: a candidate starting within +-5 days of the upload date is evidence the
    upload is the spot's launch; the YouTube row gains the signal "google" and +0.05 confidence, and the best
    candidate is stored as rank 3 (a "also ran on Google" link).
  - If it has none: the best candidate becomes the rank-1 row (source google-ads, no embed, no thumbnail) with
    confidence 0.55 x date score / sqrt(number of candidates), so a PAC with forty same-week variants reads as a
    guess, a campaign with one launch that week as likely.
Advertisers: FEC committee id from Public_IDs_List (strong), else name match against advertiser and declared
names with guards against containment ("Jackson" is not "Baird for Jackson County").
"""
import collections, csv, datetime, email.utils, io, logging, math, os, re, sys, urllib.request, zipfile
from rapidfuzz import fuzz

log = logging.getLogger("ingest.video")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "google_political_ads")
BUNDLE_URL = "https://storage.googleapis.com/political-csv/google-political-ads-transparency-bundle.zip"
BUNDLE = os.path.join(DIR, "bundle.zip")
CREATIVES = os.path.join(DIR, "creatives_us_video.csv")
ADVERTISERS = os.path.join(DIR, "advertisers_us.csv")
SINCE = "2025-07-01"                       # 2026 cycle; older ads are irrelevant to the invoices
WINDOW = 5                                 # days around first airing / upload


def fetch(refresh=False):
    """Download the bundle when Google has a newer one (conditional GET on Last-Modified), then extract the slices we use."""
    os.makedirs(DIR, exist_ok=True)
    req = urllib.request.Request(BUNDLE_URL, headers={"User-Agent": "tv-wormhole/0.1 (+research)"})
    if os.path.exists(BUNDLE) and not refresh:
        req.add_header("If-Modified-Since", email.utils.formatdate(os.path.getmtime(BUNDLE), usegmt=True))
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(BUNDLE + ".part", "wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
        os.replace(BUNDLE + ".part", BUNDLE)
        log.info("google ads: downloaded bundle (%.0f MB)", os.path.getsize(BUNDLE) / 1e6)
    except urllib.error.HTTPError as e:
        if e.code != 304:
            raise
        log.info("google ads: bundle unchanged since %s", datetime.datetime.fromtimestamp(os.path.getmtime(BUNDLE)).isoformat(timespec="minutes"))
    if refresh or not os.path.exists(CREATIVES) or os.path.getmtime(CREATIVES) < os.path.getmtime(BUNDLE):
        extract()


STATE_ABBR = None


def states_of(geo):
    """'01460,Massachusetts,United States, Georgia,United States, Atlanta GA,Georgia,United States' -> {'MA','GA'}"""
    global STATE_ABBR
    if STATE_ABBR is None:
        from .video import STATE_NAMES
        STATE_ABBR = {v.lower(): k for k, v in STATE_NAMES.items()}
    return {STATE_ABBR[m.strip().lower()] for m in re.findall(r"([A-Za-z .]+),United States", geo or "") if m.strip().lower() in STATE_ABBR}


def extract():
    csv.field_size_limit(sys.maxsize)
    z = zipfile.ZipFile(BUNDLE)
    declared = collections.defaultdict(set)
    with z.open("google-political-ads-advertiser-declared-stats.csv") as f:
        for r in csv.DictReader(io.TextIOWrapper(f, "utf-8")):
            if r["Region"].startswith("US"):
                declared[r["Advertiser_ID"]].add((r["Advertiser_Declared_Name"] or "").strip())
    n_adv = 0
    with z.open("google-political-ads-advertiser-stats.csv") as f, open(ADVERTISERS + ".part", "w", newline="") as out:
        w = csv.writer(out); w.writerow(["advertiser_id", "name", "declared_names", "fec_ids", "public_ids", "total_creatives", "spend_usd"])
        for r in csv.DictReader(io.TextIOWrapper(f, "utf-8")):
            if "US" not in r["Regions"].split(","):
                continue
            fec = re.findall(r"FEC ID (C\d{8})", r["Public_IDs_List"])
            w.writerow([r["Advertiser_ID"], r["Advertiser_Name"], "|".join(sorted(x for x in declared.get(r["Advertiser_ID"], ()) if x)), "|".join(fec),
                        r["Public_IDs_List"], r["Total_Creatives"], r["Spend_USD"]]); n_adv += 1
    n = 0
    with z.open("google-political-ads-creative-stats.csv") as f, open(CREATIVES + ".part", "w", newline="") as out:
        w = csv.writer(out); w.writerow(["ad_id", "ad_url", "advertiser_id", "start", "end", "first_served", "impressions", "spend_min", "spend_max", "states"])
        for r in csv.DictReader(io.TextIOWrapper(f, "utf-8")):
            if r["Ad_Type"] != "VIDEO" or "US" not in r["Regions"].split(",") or r["Date_Range_End"] < SINCE:
                continue
            w.writerow([r["Ad_ID"], r["Ad_URL"], r["Advertiser_ID"], r["Date_Range_Start"], r["Date_Range_End"], r["First_Served_Timestamp"],
                        r["Impressions"], r["Spend_Range_Min_USD"], r["Spend_Range_Max_USD"], "|".join(sorted(states_of(r["Geo_Targeting_Included"])))]); n += 1
    os.replace(ADVERTISERS + ".part", ADVERTISERS); os.replace(CREATIVES + ".part", CREATIVES)
    log.info("google ads: extracted %d US advertisers, %d US video ads since %s", n_adv, n, SINCE)


def load():
    advs, by_fec = {}, collections.defaultdict(list)
    for r in csv.DictReader(open(ADVERTISERS)):
        r["names"] = [r["name"]] + [x for x in r["declared_names"].split("|") if x]
        advs[r["advertiser_id"]] = r
        for f in filter(None, r["fec_ids"].split("|")):
            by_fec[f].append(r["advertiser_id"])
    ads = collections.defaultdict(list)
    for r in csv.DictReader(open(CREATIVES)):
        r["start"] = datetime.date.fromisoformat(r["start"])
        r["states"] = set(filter(None, r["states"].split("|")))
        r["spend_max"] = float(r["spend_max"] or 0)
        ads[r["advertiser_id"]].append(r)
    return advs, by_fec, ads


NORM = re.compile(r"\b(inc|llc|committee|for|the|of|pac|political action|campaign|friends|to elect|elect)\b", re.I)


def norm(s):
    return " ".join(NORM.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).split())


GENERIC = {"us", "u", "s", "senate", "house", "congress", "governor", "governors", "action", "fund", "association", "america", "american", "americans",
           "national", "state", "united", "states", "democratic", "republican", "party", "people", "citizens", "voters", "majority", "network", "project",
           "and", "a", "an", "in", "on", "oh", "super", "reps", "representatives"}


def distinctive(s):
    return [t for t in norm(s).split() if len(t) >= 3 and t not in GENERIC]


def covers(buyer_name, adv_name):
    """Every distinctive token of the buyer's name appears in the advertiser's (prefix match for truncated labels)."""
    bt, at = distinctive(buyer_name), norm(adv_name).split()
    return bool(bt) and all(any(a == t or (len(t) >= 6 and a.startswith(t)) for a in at) for t in bt)


def match_advertisers(b, advs, by_fec, ads):
    """[(advertiser_id, confidence, evidence)] for one buyer. FEC id first; else the best guarded name match."""
    if b.get("fec_committee_id") and b["fec_committee_id"] in by_fec:
        return [(a, 0.95, f"fec {b['fec_committee_id']}") for a in by_fec[b["fec_committee_id"]] if ads.get(a)]
    variants = [b["name"]] + ([b["fec_committee_name"]] if b.get("fec_committee_name") else [])
    bn = {norm(v) for v in variants if norm(v)}
    best = None
    for a, r in advs.items():
        if not ads.get(a):
            continue
        for name in r["names"]:
            an = norm(name)
            if not an:
                continue
            for v in bn:
                ts = fuzz.token_set_ratio(v, an)
                if ts < 92:
                    continue
                srt = fuzz.token_sort_ratio(v, an)
                # containment guard: a one-word buyer ("Jackson") must equal the advertiser's core name;
                # otherwise the sorted-token similarity must stay high too
                if len(v.split()) < 2 and v != an:
                    continue
                if srt < 75 and v != an:
                    continue
                if not covers(v, an):
                    continue
                if b.get("state"):
                    targeted = set().union(*(x["states"] for x in ads[a])) if ads[a] else set()
                    if targeted and b["state"] not in targeted:
                        continue
                score = (ts + srt) / 200
                if not best or score > best[1]:
                    best = (a, score, f"name {name!r} ts={ts:.0f} sort={srt:.0f}")
    return [(best[0], round(0.55 + 0.35 * best[1], 3), best[2])] if best else []


def family_states(con, buyer_id):
    out = collections.defaultdict(set)
    for ad, st in con.execute("""SELECT s.ad_id, t.state FROM spot s JOIN station t USING (facility_id)
                                 WHERE s.buyer_id=%s AND s.ad_id IS NOT NULL GROUP BY 1,2""", (buyer_id,)):
        out[ad].add(st)
    return out


def candidates(gads, day, states):
    out = []
    for g in gads:
        dd = abs((g["start"] - day).days)
        if dd > WINDOW:
            continue
        if g["states"] and states and not (g["states"] & states):
            continue
        out.append((dd, -g["spend_max"], g))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def date_score(dd):
    return 1.0 if dd == 0 else 0.85 if dd <= 2 else 0.6


def run(con, st, buyers, refresh=False):
    from .video import load_families, upsert_channel
    fetch(refresh=refresh)
    advs, by_fec, ads = load()
    yt = {r[0]: (r[1], r[2]) for r in con.execute("SELECT ad_id, published_at, confidence FROM creative_video WHERE rank=1 AND source='youtube'")}
    from .video import load_overrides
    blocked = {k for k, v in load_overrides()["channels"].items() if v.lower() in ("none", "null", "no", "-")}
    for b in buyers:
        matches = [] if b["slug"] in blocked else match_advertisers(b, advs, by_fec, ads)
        fams = load_families(con, b["buyer_id"])
        all_ids = [i for f in fams for i in f["ids"]]
        con.execute("DELETE FROM creative_video WHERE source='google-ads' AND ad_id = ANY(%s)", (all_ids,))
        if not matches:
            con.execute("DELETE FROM buyer_channel WHERE buyer_slug=%s AND source='google-ads'", (b["slug"],)); con.commit()
            continue
        a0, conf, ev = matches[0]
        others = [m[0] for m in matches[1:]]
        upsert_channel(con, b, {"channel_id": a0, "channel_url": f"https://adstransparency.google.com/advertiser/{a0}?region=US&political",
                                "title": advs[a0]["name"], "confidence": conf, "matched_by": ev + (f"; also {','.join(others)}" if others else "")},
                       source="google-ads", uploads=sum(len(ads[m[0]]) for m in matches))
        st.count("google_advertisers")
        gads = [g for m in matches for g in ads[m[0]]]
        fst = family_states(con, b["buyer_id"])
        for f in fams:
            states = set().union(*(fst.get(i, set()) for i in f["ids"]))
            ytrow = next((yt[i] for i in f["ids"] if i in yt), None)
            cands = candidates(gads, f["first"], states)
            if not cands:
                st.count("google_families_none"); continue
            dd, _, g = cands[0]
            n = len(cands)
            note = f"family {f['key']}; {n} Google video ad(s) of {advs[g['advertiser_id']]['name']} started within {WINDOW} d of first airing in {','.join(sorted(states)) or '?'}"
            if ytrow:
                pub, yconf = ytrow
                near_upload = pub and any(abs((c[2]["start"] - pub).days) <= WINDOW for c in cands)
                if near_upload:
                    con.execute("""UPDATE creative_video SET confidence = LEAST(1.0, confidence + 0.05), matched_by = matched_by || ',google'
                                   WHERE rank=1 AND source='youtube' AND ad_id = ANY(%s) AND matched_by NOT LIKE '%%google%%'""", (f["ids"],))
                    st.count("google_crosscheck")
                rank, gconf = 3, round(0.55 * date_score(dd) / math.sqrt(n), 3)
            else:
                rank, gconf = 1, round(0.55 * date_score(dd) / math.sqrt(n), 3)
                st.count("google_linkout")
            for ad in f["ids"]:
                con.execute("""INSERT INTO creative_video (ad_id, rank, source, video_url, embed_url, thumb_url, title, published_at, confidence, matched_by, notes, updated_at)
                               VALUES (%s,%s,'google-ads',%s,NULL,NULL,%s,%s,%s,%s,%s,now())
                               ON CONFLICT (ad_id, rank) DO UPDATE SET source=EXCLUDED.source, video_url=EXCLUDED.video_url, embed_url=NULL, thumb_url=NULL,
                                 title=EXCLUDED.title, published_at=EXCLUDED.published_at, confidence=EXCLUDED.confidence, matched_by=EXCLUDED.matched_by,
                                 notes=EXCLUDED.notes, updated_at=now()""",
                            (ad, rank, g["ad_url"], f"Google video ad {g['ad_id']}", g["start"], gconf, f"google-date,{'geo' if g['states'] else 'untargeted'},candidates={n}", note))
        con.commit()
        log.info("google   %-40s -> %s (%s) %d video ads", b["name"][:40], advs[a0]["name"][:40], ev[:40], len(gads))

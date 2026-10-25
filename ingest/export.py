#!/usr/bin/env python3
"""Export serving artifacts from the marts.

  web/data/spend/<facility>.json, index.json   per-station buyers (what the map reads today)
  web/data/hex/total_r<res>.json                money/ads reaching each cell (for the hex layers)
  data/marts/*.parquet                          every mart, for DuckDB / the next UI / analysis
  web/data/build.json                           build id + timestamp (cache busting)

  python3 -m ingest.export
"""
import collections, datetime, json, logging, os, re, sys
import pyarrow as pa, pyarrow.parquet as pq
from . import pg
from .video import family as spot_family
log = logging.getLogger('ingest.export')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "data")
MARTS = os.path.join(WEB, "marts")          # served by the app for the DuckDB-WASM explore mode
CAT_LABEL = {"federal": "Federal", "state": "State", "local": "Local", "issue": "Non-Candidate Issue Ads", "other": "Other"}


def slug(category, name):
    """Stable buyer id across rebuilds: category + name, e.g. federal-jon-ossoff."""
    return f"{category}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def parquet(con, name, sql, params=None):
    cur = con.execute(sql, params)
    cols = [d.name for d in cur.description]
    rows = cur.fetchall()
    table = pa.Table.from_pylist([dict(zip(cols, r)) for r in rows]) if rows else pa.table({c: [] for c in cols})
    os.makedirs(MARTS, exist_ok=True)
    pq.write_table(table, os.path.join(MARTS, f"{name}.parquet"))
    log.info(f"  {name}.parquet: {len(rows)} rows")


def party_label(p, category):
    """Fold the free-text party from NAB forms to a few labels (mirrors partyLabel in the app)."""
    s = (p or "").strip().lower()
    if not s:
        return "Issue groups" if category == "issue" else "Unknown"
    if re.match(r"^(d|dem|demo|democrat|democratic)", s): return "Democratic"
    if re.match(r"^(r|rep|repub|republican|gop)", s): return "Republican"
    if re.search(r"non.?partisan|^np$|nonpartisan", s): return "Nonpartisan"
    if re.match(r"^(i|ind|independent)", s): return "Independent"
    if "libertarian" in s: return "Libertarian"
    if "green" in s: return "Green"
    return p.strip()


VIDEO_KEYS = ("video_url", "embed_url", "thumb_url", "confidence", "source")


def load_videos(con):
    """creative_video -> ({ad_id: best}, {ad_id: runner-up}); built by ingest.video, overrides already applied there."""
    best, runner = {}, {}
    for ad, rank, source, vurl, eurl, turl, title, dur, pub, conf, mb in con.execute(
            "SELECT ad_id, rank, source, video_url, embed_url, thumb_url, title, duration_sec, published_at, confidence, matched_by FROM creative_video ORDER BY ad_id, rank"):
        d = {"video_url": vurl, "embed_url": eurl, "thumb_url": turl, "title": title, "duration": dur, "published": str(pub) if pub else None,
             "confidence": round(conf, 2) if conf is not None else None, "source": source, "matched_by": mb}
        (best if rank == 1 else runner)[ad] = d
    return best, runner


def video_brief(v):
    """The five fields every creative list carries when a video is matched (nothing when it is not)."""
    return {k: v[k] for k in VIDEO_KEYS} if v else {}


def load_channels(con):
    """buyer_id -> {source: {...}}: the buyer's own channel (youtube/override) and link-out sources (google-ads)."""
    out = collections.defaultdict(dict)
    for bid, source, cid, url, title, conf, ups in con.execute("SELECT buyer_id, source, channel_id, channel_url, title, confidence, uploads FROM buyer_channel"):
        out[bid][source] = {"id": cid, "url": url, "title": title, "confidence": round(conf, 2) if conf is not None else None, "uploads": ups}
    return out


def export_stations(con, year, build):
    os.makedirs(os.path.join(WEB, "spend"), exist_ok=True)
    totals = {r[0]: r for r in con.execute("SELECT facility_id, booked, invoiced, spots_aired, creatives, buyers, docs FROM station_total WHERE docs > 0")}
    parse = {r[0]: (r[1], r[2]) for r in con.execute("""SELECT f.facility_id, COUNT(*) FILTER (WHERE d.parse_status='ok'), COUNT(*)
                                                        FROM opif_file f LEFT JOIN document d USING (file_id) WHERE f.deleted_at IS NULL GROUP BY 1""")}
    index = {}
    for fac, (_, booked, invoiced, spots, creatives, nbuyers, docs) in totals.items():
        rows = con.execute("""SELECT b.canonical_name, b.category, b.kind, b.party, b.office, bs.booked, bs.invoiced, bs.orders, bs.spots_aired, bs.creatives,
                                     (SELECT array_agg(DISTINCT a.name) FROM order_ o JOIN agency a USING (agency_id) WHERE o.facility_id=bs.facility_id AND o.buyer_id=bs.buyer_id) AS agencies,
                                     (SELECT array_agg(DISTINCT o.advertiser_text) FROM order_ o WHERE o.facility_id=bs.facility_id AND o.buyer_id=bs.buyer_id AND o.advertiser_text IS NOT NULL) AS advertisers
                              FROM buyer_station bs JOIN buyer b USING (buyer_id) WHERE bs.facility_id=%s ORDER BY bs.booked DESC NULLS LAST""", (fac,)).fetchall()
        buyers = [{"name": r[0], "slug": slug(r[1], r[0]), "category": CAT_LABEL.get(r[1], r[1]), "kind": r[2], "party": r[3], "office": r[4],
                   "gross": float(r[5] or 0), "invoiced": float(r[6] or 0), "orders": r[7], "spots_aired": r[8], "ad_ids": r[9],
                   "agencies": (r[10] or [])[:5], "advertisers": (r[11] or [])[:3]} for r in rows]
        by_cat, by_party = {}, {}
        for b, r in zip(buyers, rows):
            by_cat[b["category"]] = by_cat.get(b["category"], 0) + b["gross"]
            pl = party_label(r[3], r[1]); by_party[pl] = by_party.get(pl, 0) + b["gross"]
        ok, n = parse.get(fac, (0, docs))
        out = {"fac": fac, "year": year, "generated": build["date"], "build": build["id"], "docs": docs, "parse_status": {"ok": ok},
               "total": float(booked), "invoiced": float(invoiced), "spots_aired": spots, "creatives": creatives,
               "by_category": {k: round(v, 2) for k, v in by_cat.items()}, "by_party": {k: round(v, 2) for k, v in by_party.items()}, "buyers": buyers}
        json.dump(out, open(os.path.join(WEB, "spend", f"{fac}.json"), "w"), separators=(",", ":"))
        index[str(fac)] = {"total": float(booked), "invoiced": float(invoiced), "buyers": nbuyers, "docs": docs,
                           "by_category": out["by_category"], "by_party": out["by_party"], "top": [b["name"] for b in buyers[:3]]}
    json.dump({"year": year, "generated": build["date"], "build": build["id"], "stations": index},
              open(os.path.join(WEB, "spend", "index.json"), "w"), separators=(",", ":"))
    log.info(f"  spend/: {len(index)} stations")


def export_hex(con):
    os.makedirs(os.path.join(WEB, "hex"), exist_ok=True)
    for (res,) in con.execute("SELECT DISTINCT res FROM hex_total ORDER BY 1"):
        rows = con.execute("SELECT h3, booked, invoiced, spots_aired, pop, stations_with_buys FROM hex_total WHERE res=%s", (res,)).fetchall()
        cells = [[r[0], round(float(r[1] or 0)), round(float(r[2] or 0)), round(float(r[3] or 0)), round(float(r[4] or 0)), r[5]] for r in rows]
        json.dump({"res": res, "columns": ["h3", "booked", "invoiced", "spots_aired", "pop", "stations"], "cells": cells},
                  open(os.path.join(WEB, "hex", f"total_r{res}.json"), "w"), separators=(",", ":"))
        log.info(f"  hex/total_r{res}.json: {len(cells)} cells")


def export_buyers(con):
    rows = con.execute("""SELECT b.buyer_id, b.canonical_name, b.category, b.kind, b.party, b.office,
                                 COALESCE(SUM(bs.booked),0), COALESCE(SUM(bs.invoiced),0), COALESCE(SUM(bs.orders),0), COALESCE(SUM(bs.spots_aired),0),
                                 COUNT(DISTINCT bs.facility_id), array_agg(DISTINCT s.state), array_agg(bs.facility_id),
                                 b.fec_candidate_id, b.fec_committee_id, b.fec_committee_name, b.identity_method, b.raw_labels, b.district
                          FROM buyer b JOIN buyer_station bs USING (buyer_id) JOIN station s USING (facility_id)
                          GROUP BY 1,2,3,4,5,6,14,15,16,17,18,19 ORDER BY 7 DESC""").fetchall()
    out = [{"id": r[0], "slug": slug(r[2], r[1]), "name": r[1], "category": CAT_LABEL.get(r[2], r[2]), "kind": r[3], "party": r[4], "office": r[5],
            "booked": float(r[6]), "invoiced": float(r[7]), "orders": int(r[8]), "spots_aired": int(r[9]), "stations": r[10],
            "states": sorted(x for x in r[11] if x), "facs": r[12],
            "fec_candidate_id": r[13], "fec_committee_id": r[14], "fec_committee_name": r[15], "method": r[16], "labels": r[17], "district": r[18]} for r in rows]
    json.dump({"buyers": out}, open(os.path.join(WEB, "buyers.json"), "w"), separators=(",", ":"))
    log.info(f"  buyers.json: {len(out)} buyers")


def export_creatives(con):
    os.makedirs(os.path.join(WEB, "creatives"), exist_ok=True)
    rows = con.execute("""SELECT c.ad_id, c.prefix, c.airings, c.first_aired, c.last_aired, b.canonical_name, b.category, b.buyer_id,
                                 jsonb_object_agg(x.facility_id, x.n)
                          FROM creative c LEFT JOIN buyer b ON b.buyer_id = c.buyer_id
                          JOIN (SELECT ad_id, facility_id, COUNT(*) n FROM spot GROUP BY 1,2) x ON x.ad_id = c.ad_id
                          GROUP BY 1,2,3,4,5,6,7,8 ORDER BY c.airings DESC""").fetchall()
    videos, _ = load_videos(con)
    out = [{"ad_id": r[0], "prefix": r[1], "family": spot_family(r[0]), "airings": r[2], "first": str(r[3]), "last": str(r[4]), "buyer": r[5], "category": CAT_LABEL.get(r[6], r[6]),
            "buyer_id": r[7], "facs": r[8], **video_brief(videos.get(r[0]))} for r in rows]       # facs: {facility_id: airings}; family: Ad-ID without the per-airing tail
    log.info(f"  creatives/all.json: {sum(1 for c in out if c.get('video_url'))} with a video match")
    json.dump({"creatives": out}, open(os.path.join(WEB, "creatives", "all.json"), "w"), separators=(",", ":"))
    log.info(f"  creatives/all.json: {len(out)} creatives")


def export_details(con):
    """web/data/buyers/<slug>.json and web/data/stations/<fac>.json: everything a detail page needs."""
    os.makedirs(os.path.join(WEB, "buyers"), exist_ok=True); os.makedirs(os.path.join(WEB, "stations"), exist_ok=True)
    st = {r[0]: {"fac": r[0], "call": r[1], "city": r[2], "state": r[3], "group": r[4], "newson": r[5], "slug": r[6]}
          for r in con.execute("SELECT facility_id, call, city, state, station_group, newson_id, public_file_slug FROM station")}
    weekly = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0]))
    for fac, bid, day, booked, invoiced, spots in con.execute("SELECT facility_id, buyer_id, date_trunc('week', day)::date, booked, invoiced, spots_aired FROM spend_daily"):
        w = weekly[(fac, bid)][str(day)]; w[0] += float(booked or 0); w[1] += float(invoiced or 0); w[2] += int(spots or 0)
    def series(keys):
        acc = collections.defaultdict(lambda: [0.0, 0.0, 0])
        for k in keys:
            for wk, v in weekly.get(k, {}).items():
                a = acc[wk]; a[0] += v[0]; a[1] += v[1]; a[2] += v[2]
        return [{"week": wk, "booked": round(v[0]), "invoiced": round(v[1]), "spots": v[2]} for wk, v in sorted(acc.items())]
    creatives = collections.defaultdict(list)       # by (fac, buyer_id)
    for ad, fac, bid, n, first, last in con.execute("SELECT ad_id, facility_id, buyer_id, COUNT(*), MIN(aired_on), MAX(aired_on) FROM spot WHERE ad_id IS NOT NULL GROUP BY 1,2,3"):
        creatives[(fac, bid)].append({"ad_id": ad, "airings": n, "first": str(first), "last": str(last)})
    videos, _ = load_videos(con)
    channels = load_channels(con)
    daypart = collections.defaultdict(lambda: [[0] * 24 for _ in range(7)])   # (fac, bid) -> [weekday Mon=0][hour]
    for fac, bid, dow, t, n in con.execute("""SELECT facility_id, buyer_id, EXTRACT(ISODOW FROM aired_on)::int - 1, aired_time, COUNT(*)
                                             FROM spot WHERE aired_time IS NOT NULL GROUP BY 1,2,3,4"""):
        m = re.match(r"\s*(\d{1,2}):\d\d\s*([AP])M", t or "", re.I)
        if m:
            daypart[(fac, bid)][dow][int(m.group(1)) % 12 + (12 if m.group(2).upper() == "P" else 0)] += n
    def grid(keys):
        g = [[0] * 24 for _ in range(7)]
        for k in keys:
            d = daypart.get(k)
            if d:
                for i in range(7):
                    for h in range(24):
                        g[i][h] += d[i][h]
        return g if any(any(r) for r in g) else None
    buyers = con.execute("""SELECT b.buyer_id, b.canonical_name, b.category, b.kind, b.party, b.office, b.district, b.state,
                                   b.fec_candidate_id, b.fec_committee_id, b.fec_committee_name, b.identity_method,
                                   (SELECT array_agg(DISTINCT alias) FROM buyer_alias a WHERE a.buyer_id=b.buyer_id AND a.source='folder') labels
                            FROM buyer b WHERE EXISTS (SELECT 1 FROM buyer_station bs WHERE bs.buyer_id=b.buyer_id)""").fetchall()
    bs_rows = collections.defaultdict(list)
    for r in con.execute("""SELECT bs.buyer_id, bs.facility_id, bs.booked, bs.invoiced, bs.orders, bs.spots_aired, bs.creatives,
                                   (SELECT array_agg(DISTINCT a.name) FROM order_ o JOIN agency a USING (agency_id) WHERE o.facility_id=bs.facility_id AND o.buyer_id=bs.buyer_id)
                            FROM buyer_station bs"""):
        bs_rows[r[0]].append(r)
    n = 0
    for b in buyers:
        bid = b[0]; rows = bs_rows.get(bid, [])
        stations = sorted(({"fac": r[1], "call": st[r[1]]["call"], "city": st[r[1]]["city"], "state": st[r[1]]["state"], "group": st[r[1]]["group"],
                            "booked": float(r[2] or 0), "invoiced": float(r[3] or 0), "orders": r[4], "spots_aired": r[5], "creatives": r[6], "agencies": (r[7] or [])[:4]}
                           for r in rows), key=lambda x: -x["booked"])
        cr = collections.defaultdict(lambda: {"airings": 0, "stations": set(), "first": "9", "last": "0"})
        for r in rows:
            for c in creatives.get((r[1], bid), []):
                e = cr[c["ad_id"]]; e["airings"] += c["airings"]; e["stations"].add(st[r[1]]["call"]); e["first"] = min(e["first"], c["first"]); e["last"] = max(e["last"], c["last"])
        out = {"slug": slug(b[2], b[1]), "name": b[1], "category": CAT_LABEL.get(b[2], b[2]), "kind": b[3], "party": b[4], "office": b[5], "district": b[6], "state": b[7],
               "fec_candidate_id": b[8], "fec_committee_id": b[9], "fec_committee_name": b[10], "method": b[11], "labels": sorted(b[12] or []),
               "booked": round(sum(s_["booked"] for s_ in stations)), "invoiced": round(sum(s_["invoiced"] for s_ in stations)),
               "stations": stations, "weekly": series([(r[1], bid) for r in rows]), "daypart": grid([(r[1], bid) for r in rows]),
               "creatives": sorted(({"ad_id": k, "family": spot_family(k), "airings": v["airings"], "stations": sorted(v["stations"]), "first": v["first"], "last": v["last"], **video_brief(videos.get(k))} for k, v in cr.items()), key=lambda x: -x["airings"])[:60],
               "agencies": sorted({a for s_ in stations for a in s_["agencies"]}),
               "channel": channels.get(bid, {}).get("override") or channels.get(bid, {}).get("youtube"),
               "links": {src: ch["url"] for src, ch in channels.get(bid, {}).items() if src not in ("youtube", "override")}}
        json.dump(out, open(os.path.join(WEB, "buyers", out["slug"] + ".json"), "w"), separators=(",", ":")); n += 1
    log.info(f"  buyers/: {n} detail files")
    bname = {b[0]: (b[1], b[2]) for b in buyers}
    m = 0
    for fac, info in st.items():
        rows = [r for bid in bs_rows for r in bs_rows[bid] if r[1] == fac]
        if not rows:
            continue
        cr = collections.defaultdict(lambda: {"airings": 0, "buyer": None, "slug": None, "category": None, "first": "9", "last": "0"})
        for r in rows:
            for c in creatives.get((fac, r[0]), []):
                e = cr[c["ad_id"]]; e["airings"] += c["airings"]; e["buyer"], cat = bname.get(r[0], (None, None)); e["slug"] = slug(cat, e["buyer"]) if e["buyer"] else None
                e["category"] = CAT_LABEL.get(cat, cat); e["first"] = min(e["first"], c["first"]); e["last"] = max(e["last"], c["last"])
        out = {**info, "weekly": series([(fac, r[0]) for r in rows]), "daypart": grid([(fac, r[0]) for r in rows]),
               "creatives": sorted(({"ad_id": k, "family": spot_family(k), **v, **video_brief(videos.get(k))} for k, v in cr.items()), key=lambda x: -x["airings"])[:80]}
        json.dump(out, open(os.path.join(WEB, "stations", f"{fac}.json"), "w"), separators=(",", ":")); m += 1
    log.info(f"  stations/: {m} detail files")


def export_creative_pages(con):
    """web/data/creatives/<ad_id>.json: airings by station, by day and by hour for one creative."""
    os.makedirs(os.path.join(WEB, "creatives", "id"), exist_ok=True)
    st = {r[0]: (r[1], r[2]) for r in con.execute("SELECT facility_id, call, state FROM station")}
    rows = con.execute("""SELECT s.ad_id, s.facility_id, s.aired_on, s.aired_time, s.buyer_id FROM spot s WHERE s.ad_id IS NOT NULL ORDER BY 1""").fetchall()
    bname = {r[0]: (r[1], r[2]) for r in con.execute("SELECT buyer_id, canonical_name, category FROM buyer")}
    videos, runners = load_videos(con)
    by = collections.defaultdict(lambda: {"by_station": collections.Counter(), "by_day": collections.Counter(), "by_hour": [0] * 24, "buyers": collections.Counter()})
    for ad, fac, day, t, bid in rows:
        e = by[ad]; e["by_station"][fac] += 1; e["by_day"][str(day)] += 1; e["buyers"][bid] += 1
        m = re.match(r"\s*(\d{1,2}):\d\d\s*([AP])M", t or "", re.I)
        if m:
            h = int(m.group(1)) % 12 + (12 if m.group(2).upper() == "P" else 0); e["by_hour"][h] += 1
    for ad, e in by.items():
        bid = e["buyers"].most_common(1)[0][0]
        name, cat = bname.get(bid, (None, None))
        out = {"ad_id": ad, "prefix": ad[:4], "buyer": name, "slug": slug(cat, name) if name else None, "category": CAT_LABEL.get(cat, cat),
               "airings": sum(e["by_station"].values()), "first": min(e["by_day"]), "last": max(e["by_day"]),
               "by_station": sorted(({"fac": f, "call": st[f][0], "state": st[f][1], "airings": n} for f, n in e["by_station"].items()), key=lambda x: -x["airings"]),
               "by_day": sorted(e["by_day"].items()), "by_hour": e["by_hour"], "family": spot_family(ad)}
        v = videos.get(ad)
        if v:
            out.update({k: v[k] for k in VIDEO_KEYS}, video_title=v["title"], video_duration=v["duration"], video_published=v["published"], matched_by=v["matched_by"],
                       runner_up=({k: runners[ad][k] for k in ("video_url", "thumb_url", "title", "confidence")} if ad in runners else None))
        json.dump(out, open(os.path.join(WEB, "creatives", "id", f"{ad}.json"), "w"), separators=(",", ":"))
    log.info(f"  creatives/id/: {len(by)} files")


SOURCES = [
    {"name": "FCC Online Public Inspection File (OPIF) API", "url": "https://publicfiles.fcc.gov/developer/", "what": "every political-file document each station uploads: folder listing, change feed, and the PDFs",
     "terms": "https://www.fcc.gov/developer/api-terms-of-service"},
    {"name": "FCC TV Query", "url": "https://www.fcc.gov/media/radio/tvq-tv-query", "what": "licensed full-power and Class A stations: call sign, community, transmitter, licensee, application IDs"},
    {"name": "FCC TV service contour data", "url": "https://www.fcc.gov/media/television/tv-service-contour-data-points", "what": "predicted F(50,90) service contours, 360 points per station, updated daily"},
    {"name": "NewsON", "url": "https://www.newson.us/", "what": "free live and on-demand local newscast streams; station IDs collected from its public search"},
    {"name": "FEC bulk candidate and committee master files", "url": "https://www.fec.gov/data/browse-data/?tab=bulk-data", "what": "federal candidates and committees for the cycle, used to resolve buyer identity"},
    {"name": "Census cartographic boundary files (counties)", "url": "https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html", "what": "county polygons"},
    {"name": "Census county population estimates (2024 vintage)", "url": "https://www.census.gov/programs-surveys/popest.html", "what": "county population, spread into H3 cells by area share"},
    {"name": "Census Gazetteer ZCTA and place files", "url": "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html", "what": "ZIP and city search without an external geocoder"},
    {"name": "H3", "url": "https://h3geo.org/", "what": "hexagonal cells used for density layers"},
    {"name": "OpenFreeMap / OpenMapTiles / OpenStreetMap", "url": "https://openfreemap.org/", "what": "basemap tiles"},
    {"name": "Nominatim (OpenStreetMap)", "url": "https://nominatim.org/", "what": "fallback geocoder for street addresses only"},
]


def export_methods(con):
    """web/data/methods.json: everything the About page states as fact, computed from the live database."""
    import importlib
    q = lambda sql, *p: con.execute(sql, p).fetchall()
    kinds = {f"{k}/{st}": n for k, st, n in q("SELECT kind, parse_status, COUNT(*) FROM document GROUP BY 1,2")}
    templates = {t or "unknown": n for t, n in q("SELECT template, COUNT(*) FROM document WHERE kind IN ('order','invoice') GROUP BY 1")}
    groups = [{"group": g or "other", "stations": n, "docs": d} for g, n, d in q("""SELECT s.station_group, COUNT(DISTINCT s.facility_id), COUNT(f.file_id) FROM station s JOIN opif_file f USING (facility_id)
                                                                                 WHERE f.deleted_at IS NULL GROUP BY 1 ORDER BY 3 DESC""")]
    identity = {m or "raw": [n, int(l or 0)] for m, n, l in q("SELECT identity_method, COUNT(*), SUM(raw_labels) FROM buyer WHERE EXISTS (SELECT 1 FROM buyer_station bs WHERE bs.buyer_id=buyer.buyer_id) GROUP BY 1")}
    hexes = {str(r): n for r, n in q("SELECT res, COUNT(*) FROM hex GROUP BY 1 ORDER BY 1")}
    modules = {}
    for m in ("crawl", "update", "ocr", "parse", "validate", "load_pg", "entities", "identity", "geo", "export", "tiles", "places", "status", "coverage", "batch", "runlog"):
        try:
            modules[m] = (importlib.import_module(f"ingest.{m}").__doc__ or "").strip()
        except Exception as e:
            modules[m] = f"(no description: {e})"
    runs = {}
    for stage, status, started, ended, counts, failures, error, log_path in q("""SELECT DISTINCT ON (stage) stage, status, started, ended, counts, failures, error, log_path
                                                                              FROM pipeline_run WHERE stage NOT IN ('batch_state') ORDER BY stage, started DESC"""):
        runs[stage] = {"status": status, "started": str(started), "ended": str(ended) if ended else None, "counts": counts, "failures": failures, "error": error, "log": log_path}
    batches = [{"state": b, "status": st_, "started": str(s0), "ended": str(e0) if e0 else None} for b, st_, s0, e0 in
               q("SELECT DISTINCT ON (batch) batch, status, started, ended FROM pipeline_run WHERE stage='batch_state' ORDER BY batch, started DESC")]
    templates_by_kind = {f"{k}/{t or 'unrecognized'}": n for k, t, n in q("SELECT kind, template, COUNT(*) FROM document GROUP BY 1,2 ORDER BY 3 DESC")}
    ocr_engines = {e or "legacy-tesseract": n for e, n in q("SELECT ocr_engine, COUNT(*) FROM document WHERE source='ocr' GROUP BY 1")}
    listing = {st_: n for st_, n in q("SELECT status, COUNT(*) FROM opif_listing GROUP BY 1")}
    coverage = None
    try:
        from .coverage import report as coverage_report
        from . import db as _db
        cov = coverage_report(_db.connect())
        coverage = {"national_counts_as_of": cov["national_counts_as_of"], "total": cov["total"],
                    "by_state": {st_: {y: {k: v for k, v in d.items() if k in ("stations", "stations_with_docs", "stations_crawled", "docs_national", "docs_downloaded", "docs_ok")} for y, d in yrs.items()} for st_, yrs in cov["by_state"].items()},
                    "stations_not_yet_crawled_2026": len([m for m in cov["missing"] if m[1] == "2026"])}
    except Exception as e:
        coverage = {"error": str(e)[:200]}
    out = {
        "generated": datetime.date.today().isoformat(),
        "pipeline": {"last_runs": runs, "batches": batches, "listing": listing, "ocr_engines": ocr_engines, "templates": templates_by_kind,
                     "parser_version": __import__("ingest.parse", fromlist=["PARSER_VERSION"]).PARSER_VERSION,
                     "stages": "crawl -> parse -> ocr -> parse --only-failed -> load_pg -> entities -> identity -> entities -> marts -> geo -> export -> tiles",
                     "logs": "data/logs/<stage>-<timestamp>.log; `make status` summarises; every stage records a pipeline_run row"},
        "coverage": coverage,
        "stations": {"licensed": q("SELECT COUNT(*) FROM station")[0][0], "with_documents": q("SELECT COUNT(DISTINCT facility_id) FROM opif_file WHERE deleted_at IS NULL")[0][0],
                     "states": sorted(x for (x,) in q("SELECT DISTINCT s.state FROM station s JOIN opif_file f USING (facility_id) WHERE f.deleted_at IS NULL") if x),
                     "with_streams": q("SELECT COUNT(*) FROM station WHERE newson_id IS NOT NULL")[0][0], "by_group": groups},
        "documents": {"total": q("SELECT COUNT(*) FROM opif_file WHERE deleted_at IS NULL")[0][0], "parsed": q("SELECT COUNT(*) FROM document")[0][0], "by_kind_status": kinds,
                      "templates": templates, "ocr": q("SELECT COUNT(*) FROM document WHERE source='ocr'")[0][0],
                      "first_upload": str(q("SELECT MIN(fcc_created_at)::date FROM opif_file")[0][0]), "last_upload": str(q("SELECT MAX(fcc_created_at)::date FROM opif_file")[0][0])},
        "entities": {"orders": q("SELECT COUNT(*) FROM order_")[0][0], "orders_with_lines": q("SELECT COUNT(DISTINCT order_id) FROM order_line")[0][0], "invoices": q("SELECT COUNT(*) FROM invoice")[0][0],
                     "invoices_linked": q("SELECT COUNT(*) FROM invoice WHERE order_id IS NOT NULL")[0][0], "spots": q("SELECT COUNT(*) FROM spot")[0][0], "creatives": q("SELECT COUNT(*) FROM creative")[0][0],
                     "buyers": sum(v[0] for v in identity.values()), "identity": identity, "manual_overrides": sum(1 for l in open(os.path.join(ROOT, "data", "buyer_overrides.yaml")) if ":" in l and not l.startswith("#")) if os.path.exists(os.path.join(ROOT, "data", "buyer_overrides.yaml")) else 0},
        "money": {"booked": float(q("SELECT COALESCE(SUM(gross),0) FROM order_ WHERE status='booked'")[0][0]), "invoiced": float(q("SELECT COALESCE(SUM(gross),0) FROM invoice")[0][0]),
                  "first_day": str(q("SELECT MIN(day) FROM spend_daily")[0][0]), "last_day": str(q("SELECT MAX(day) FROM spend_daily")[0][0])},
        "geography": {"counties": q("SELECT COUNT(*) FROM county")[0][0], "hex_cells": hexes, "coverage_rows": q("SELECT COUNT(*) FROM station_hex")[0][0]},
        "sources": SOURCES, "modules": modules,
        "fcc_notice": "This product uses the FCC Data API but is not endorsed or certified by the FCC.",
    }
    json.dump(out, open(os.path.join(WEB, "methods.json"), "w"), indent=1)
    log.info("  methods.json")


def export_weights(con, res=5):
    """web/data/hex/weights_r<res>.json: each active station's population-share weights over cells, so the
    client can compose a frame for any day/week/cumulative window from station_daily (value_cell = sum_s v_s * w_s,cell)."""
    cells, idx = [], {}
    stations = {}
    rows = con.execute("""SELECT sh.facility_id, sh.h3, COALESCE(h.pop,0)*sh.coverage_share AS w
                          FROM station_hex sh JOIN hex h USING (h3)
                          WHERE h.res = %s AND sh.facility_id IN (SELECT DISTINCT facility_id FROM station_daily)""", (res,)).fetchall()
    sums = collections.Counter()
    for fac, h, w in rows:
        sums[fac] += float(w or 0)
    for fac, h, w in rows:
        w = float(w or 0)
        if w <= 0 or sums[fac] <= 0:
            continue
        if h not in idx:
            idx[h] = len(cells); cells.append(h)
        stations.setdefault(fac, []).append([idx[h], round(w / sums[fac], 5)])
    out = {"res": res, "cells": cells, "stations": stations}
    json.dump(out, open(os.path.join(WEB, "hex", f"weights_r{res}.json"), "w"), separators=(",", ":"))
    log.info(f"  hex/weights_r{res}.json: {len(cells)} cells, {len(stations)} stations, {sum(len(v) for v in stations.values())} weights")


def export_time(con):
    rows = con.execute("SELECT facility_id, day, booked, invoiced, spots_aired FROM station_daily ORDER BY 1,2").fetchall()
    json.dump({"columns": ["fac", "day", "booked", "invoiced", "spots_aired"],
               "rows": [[r[0], str(r[1]), round(float(r[2])), round(float(r[3])), int(r[4])] for r in rows]},
              open(os.path.join(WEB, "station_daily.json"), "w"), separators=(",", ":"))
    log.info(f"  station_daily.json: {len(rows)} rows")
    rows = con.execute("""
        WITH w AS (SELECT sh.facility_id, sh.h3, COALESCE(h.pop,0)*sh.coverage_share AS w, SUM(COALESCE(h.pop,0)*sh.coverage_share) OVER (PARTITION BY sh.facility_id) wsum
                   FROM station_hex sh JOIN hex h USING (h3) WHERE h.res = 5),
             sd AS (SELECT facility_id, date_trunc('week', day)::date AS week, SUM(booked) booked, SUM(invoiced) invoiced, SUM(spots_aired) spots_aired
                    FROM station_daily GROUP BY 1,2)
        SELECT sd.week, w.h3, SUM(sd.booked*w.w/NULLIF(w.wsum,0)), SUM(sd.invoiced*w.w/NULLIF(w.wsum,0)), SUM(sd.spots_aired*w.w/NULLIF(w.wsum,0)), MAX(h.pop)
        FROM sd JOIN w USING (facility_id) JOIN hex h ON h.h3 = w.h3 GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    weeks = {}
    for week, h3, b, i, sp, pop in rows:
        weeks.setdefault(str(week), []).append([h3, round(float(b or 0)), round(float(i or 0)), round(float(sp or 0), 1), round(float(pop or 0))])
    json.dump({"res": 5, "columns": ["h3", "booked", "invoiced", "spots_aired", "pop"], "weeks": weeks},
              open(os.path.join(WEB, "hex", "weekly_r5.json"), "w"), separators=(",", ":"))
    log.info(f"  hex/weekly_r5.json: {len(weeks)} weeks, {len(rows)} rows")


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--only", help="comma-separated subset: methods,stations,hex,buyers,creatives,time,details,pages,parquet")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    want = lambda k: only is None or k in only
    year = 2026
    build = {"id": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "date": datetime.date.today().isoformat()}
    from .runlog import Stage
    with Stage("export", args=vars(a)) as st, pg.connect() as con:
        if want("methods"):
            export_methods(con)
        if want("weights"):
            export_weights(con)
        if want("stations"): export_stations(con, year, build)
        if want("hex"): export_hex(con)
        if want("buyers"): export_buyers(con)
        if want("creatives"): export_creatives(con)
        if want("time"): export_time(con)
        if want("details"): export_details(con)
        if want("pages"): export_creative_pages(con)
        if not want("parquet"):
            json.dump(build, open(os.path.join(WEB, "build.json"), "w")); print(f"build {build['id']}", file=sys.stderr); return
        parquet(con, "station", "SELECT facility_id, call, service, city, state, licensee, station_group, newson_id, public_file_slug, ST_Y(tx) lat, ST_X(tx) lon FROM station")
        parquet(con, "buyer", "SELECT * FROM buyer")
        parquet(con, "buyer_station", "SELECT * FROM buyer_station")
        parquet(con, "station_total", "SELECT * FROM station_total")
        parquet(con, "station_daily", "SELECT * FROM station_daily")
        parquet(con, "spend_daily", "SELECT * FROM spend_daily")
        parquet(con, "hex", "SELECT h3, res, pop FROM hex")
        parquet(con, "station_hex", "SELECT * FROM station_hex")
        parquet(con, "hex_total", "SELECT * FROM hex_total")
        parquet(con, "creative", "SELECT * FROM creative")
        parquet(con, "creative_video", "SELECT ad_id, rank, source, video_url, embed_url, thumb_url, title, duration_sec, published_at, confidence, matched_by FROM creative_video")
        parquet(con, "buyer_channel", "SELECT buyer_id, source, channel_id, channel_url, title, matched_by, confidence, uploads FROM buyer_channel")
        parquet(con, "order_", "SELECT order_id, facility_id, order_no, buyer_id, agency_id, advertiser_text, product, flight_start, flight_end, status, gross, net, spots FROM order_")
        parquet(con, "agency", "SELECT * FROM agency")
        parquet(con, "spot", "SELECT spot_id, invoice_id, facility_id, buyer_id, aired_on, aired_time, ad_id FROM spot")
        # weekly frames at the national resolution: time comes from station_daily, space from station_hex
        parquet(con, "hex_weekly_r5", """
            WITH w AS (SELECT sh.facility_id, sh.h3, h.pop*sh.coverage_share AS w, SUM(h.pop*sh.coverage_share) OVER (PARTITION BY sh.facility_id) wsum
                       FROM station_hex sh JOIN hex h USING (h3) WHERE h.res = 5),
                 sd AS (SELECT facility_id, date_trunc('week', day)::date AS week, SUM(booked) booked, SUM(invoiced) invoiced, SUM(spots_aired) spots_aired
                        FROM station_daily GROUP BY 1,2)
            SELECT w.h3, sd.week, SUM(sd.booked*w.w/NULLIF(w.wsum,0)) booked, SUM(sd.invoiced*w.w/NULLIF(w.wsum,0)) invoiced,
                   SUM(sd.spots_aired*w.w/NULLIF(w.wsum,0)) spots_aired
            FROM sd JOIN w USING (facility_id) GROUP BY 1,2""")
        json.dump(build, open(os.path.join(WEB, "build.json"), "w"))
    log.info(f"build {build['id']}")


if __name__ == "__main__":
    main()

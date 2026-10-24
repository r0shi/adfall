#!/usr/bin/env python3
"""Export serving artifacts from the marts.

  web/data/spend/<facility>.json, index.json   per-station buyers (what the map reads today)
  web/data/hex/total_r<res>.json                money/ads reaching each cell (for the hex layers)
  data/marts/*.parquet                          every mart, for DuckDB / the next UI / analysis
  web/data/build.json                           build id + timestamp (cache busting)

  python3 -m ingest.export
"""
import collections, datetime, json, os, re, sys
import pyarrow as pa, pyarrow.parquet as pq
from . import pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "data")
MARTS = os.path.join(ROOT, "data", "marts")
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
    print(f"  {name}.parquet: {len(rows)} rows", file=sys.stderr)


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
        by_cat = {}
        for b in buyers:
            by_cat[b["category"]] = by_cat.get(b["category"], 0) + b["gross"]
        ok, n = parse.get(fac, (0, docs))
        out = {"fac": fac, "year": year, "generated": build["date"], "build": build["id"], "docs": docs, "parse_status": {"ok": ok},
               "total": float(booked), "invoiced": float(invoiced), "spots_aired": spots, "creatives": creatives,
               "by_category": {k: round(v, 2) for k, v in by_cat.items()}, "buyers": buyers}
        json.dump(out, open(os.path.join(WEB, "spend", f"{fac}.json"), "w"), separators=(",", ":"))
        index[str(fac)] = {"total": float(booked), "invoiced": float(invoiced), "buyers": nbuyers, "docs": docs,
                           "by_category": out["by_category"], "top": [b["name"] for b in buyers[:3]]}
    json.dump({"year": year, "generated": build["date"], "build": build["id"], "stations": index},
              open(os.path.join(WEB, "spend", "index.json"), "w"), separators=(",", ":"))
    print(f"  spend/: {len(index)} stations", file=sys.stderr)


def export_hex(con):
    os.makedirs(os.path.join(WEB, "hex"), exist_ok=True)
    for (res,) in con.execute("SELECT DISTINCT res FROM hex_total ORDER BY 1"):
        rows = con.execute("SELECT h3, booked, invoiced, spots_aired, pop, stations_with_buys FROM hex_total WHERE res=%s", (res,)).fetchall()
        cells = [[r[0], round(float(r[1] or 0)), round(float(r[2] or 0)), round(float(r[3] or 0)), round(float(r[4] or 0)), r[5]] for r in rows]
        json.dump({"res": res, "columns": ["h3", "booked", "invoiced", "spots_aired", "pop", "stations"], "cells": cells},
                  open(os.path.join(WEB, "hex", f"total_r{res}.json"), "w"), separators=(",", ":"))
        print(f"  hex/total_r{res}.json: {len(cells)} cells", file=sys.stderr)


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
    print(f"  buyers.json: {len(out)} buyers", file=sys.stderr)


def export_creatives(con):
    os.makedirs(os.path.join(WEB, "creatives"), exist_ok=True)
    rows = con.execute("""SELECT c.ad_id, c.prefix, c.airings, c.first_aired, c.last_aired, b.canonical_name, b.category, b.buyer_id,
                                 jsonb_object_agg(x.facility_id, x.n)
                          FROM creative c LEFT JOIN buyer b ON b.buyer_id = c.buyer_id
                          JOIN (SELECT ad_id, facility_id, COUNT(*) n FROM spot GROUP BY 1,2) x ON x.ad_id = c.ad_id
                          GROUP BY 1,2,3,4,5,6,7,8 ORDER BY c.airings DESC""").fetchall()
    out = [{"ad_id": r[0], "prefix": r[1], "airings": r[2], "first": str(r[3]), "last": str(r[4]), "buyer": r[5], "category": CAT_LABEL.get(r[6], r[6]),
            "buyer_id": r[7], "facs": r[8]} for r in rows]       # facs: {facility_id: airings}
    json.dump({"creatives": out}, open(os.path.join(WEB, "creatives", "all.json"), "w"), separators=(",", ":"))
    print(f"  creatives/all.json: {len(out)} creatives", file=sys.stderr)


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
               "stations": stations, "weekly": series([(r[1], bid) for r in rows]),
               "creatives": sorted(({"ad_id": k, "airings": v["airings"], "stations": sorted(v["stations"]), "first": v["first"], "last": v["last"]} for k, v in cr.items()), key=lambda x: -x["airings"])[:60],
               "agencies": sorted({a for s_ in stations for a in s_["agencies"]})}
        json.dump(out, open(os.path.join(WEB, "buyers", out["slug"] + ".json"), "w"), separators=(",", ":")); n += 1
    print(f"  buyers/: {n} detail files", file=sys.stderr)
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
        out = {**info, "weekly": series([(fac, r[0]) for r in rows]),
               "creatives": sorted(({"ad_id": k, **v} for k, v in cr.items()), key=lambda x: -x["airings"])[:80]}
        json.dump(out, open(os.path.join(WEB, "stations", f"{fac}.json"), "w"), separators=(",", ":")); m += 1
    print(f"  stations/: {m} detail files", file=sys.stderr)


def export_time(con):
    rows = con.execute("SELECT facility_id, day, booked, invoiced, spots_aired FROM station_daily ORDER BY 1,2").fetchall()
    json.dump({"columns": ["fac", "day", "booked", "invoiced", "spots_aired"],
               "rows": [[r[0], str(r[1]), round(float(r[2])), round(float(r[3])), int(r[4])] for r in rows]},
              open(os.path.join(WEB, "station_daily.json"), "w"), separators=(",", ":"))
    print(f"  station_daily.json: {len(rows)} rows", file=sys.stderr)
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
    print(f"  hex/weekly_r5.json: {len(weeks)} weeks, {len(rows)} rows", file=sys.stderr)


def main():
    year = 2026
    build = {"id": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "date": datetime.date.today().isoformat()}
    with pg.connect() as con:
        export_stations(con, year, build)
        export_hex(con)
        export_buyers(con)
        export_creatives(con)
        export_time(con)
        export_details(con)
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
    print(f"build {build['id']}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Export serving artifacts from the marts.

  web/data/spend/<facility>.json, index.json   per-station buyers (what the map reads today)
  web/data/hex/total_r<res>.json                money/ads reaching each cell (for the hex layers)
  data/marts/*.parquet                          every mart, for DuckDB / the next UI / analysis
  web/data/build.json                           build id + timestamp (cache busting)

  python3 -m ingest.export
"""
import datetime, json, os, sys
import pyarrow as pa, pyarrow.parquet as pq
from . import pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "data")
MARTS = os.path.join(ROOT, "data", "marts")
CAT_LABEL = {"federal": "Federal", "state": "State", "local": "Local", "issue": "Non-Candidate Issue Ads", "other": "Other"}


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
        buyers = [{"name": r[0], "category": CAT_LABEL.get(r[1], r[1]), "kind": r[2], "party": r[3], "office": r[4],
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


def main():
    year = 2026
    build = {"id": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "date": datetime.date.today().isoformat()}
    with pg.connect() as con:
        export_stations(con, year, build)
        export_hex(con)
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

#!/usr/bin/env python3
"""Vector tiles (PMTiles) for the map: hex money layers and station contours, via tippecanoe.

  python3 -m ingest.tiles        -> web/data/tiles/hex5.pmtiles, hex7.pmtiles, hex8.pmtiles, contours.pmtiles, meta.json

Res 8 exists only in metro cells (ingest.geo METRO_DENSITY), so every res-7 cell whose children exist at res 8
carries fine=1: above the switch zoom the app draws hex8 plus the hex7 cells without that flag, a seamless mosaic
with no double painting. Res-8 features are emitted for every cell, money or not, so the mosaic has no holes.

$ per person and $ per spot are in-market (market_metrics): contours overlap across TV markets, but a household
watches one market's stations, so summing every covering station double counts fringe areas ($/person) and blends
one market's prices into another's ($/spot). With no DMA table, a market is the stations whose transmitters sit within
MARKET_EPS_M of each other; each cell belongs to the nearest market that reaches it and has a station with a political
file (MARKET_MIN_DOCS, which skips public-TV satellites), and each station's money is spread over its in-market people.
A station's price per spot comes only from invoices whose spot lines were parsed in full (the invoice's own spot count
matches, or it states none), at least MARKET_MIN_SPOTS of them: station totals mix invoices with and without spot lines.
"""
import json, logging, os, subprocess, sys, tempfile, time
import h3
from . import pg
from .runlog import Stage
log = logging.getLogger('ingest.tiles')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "data", "tiles")
ZOOMS = {5: ("3", "8"), 7: ("6", "10"), 8: ("9", "13")}       # res -> (minzoom, maxzoom)
MARKET_EPS_M = 30000      # transmitters chained within 30 km form one market (antenna farms; keeps Baltimore and DC apart)
MARKET_MIN_DOCS = 10      # a market a cell can belong to has a station with this many political-file documents
MARKET_MIN_SPOTS = 100    # a station prices a spot only from at least this many fully parsed invoice spot lines


def markets(con):
    """Temp tables mk (station -> market, transmitter point), mkc (market -> sells political time) and price (station ->
    gross $ and spots over its fully parsed invoices). Returns (markets, selling markets)."""
    con.execute("""CREATE TEMP TABLE mk AS SELECT facility_id, ST_Transform(tx, 5070) AS p,
                     ST_ClusterDBSCAN(ST_Transform(tx, 5070), eps := %s, minpoints := 1) OVER () AS market
                   FROM station WHERE tx IS NOT NULL""", (MARKET_EPS_M,))
    con.execute("""CREATE TEMP TABLE mkc AS SELECT mk.market, bool_or(COALESCE(st.docs, 0) >= %s) AS sells
                   FROM mk LEFT JOIN station_total st USING (facility_id) GROUP BY 1""", (MARKET_MIN_DOCS,))
    con.execute("""CREATE TEMP TABLE price AS
                   WITH sp AS (SELECT invoice_id, count(*) AS n FROM spot GROUP BY 1)
                   SELECT i.facility_id, SUM(i.gross) AS g, SUM(sp.n) AS n FROM invoice i JOIN sp USING (invoice_id)
                   WHERE i.gross > 0 AND (i.spots IS NULL OR i.spots = sp.n) GROUP BY 1 HAVING SUM(sp.n) >= %s""", (MARKET_MIN_SPOTS,))
    return con.execute("SELECT count(*), count(*) FILTER (WHERE sells) FROM mkc").fetchone()


def market_metrics(con, res):
    """h3 -> (in-market booked $ per person, in-market invoiced $ per aired spot or None) for one resolution.
    Res 8 is normalised by the station's res-7 in-market reach, as hex_total does, so the two agree. The price is the
    market's priced stations reaching the cell pooled: their invoice dollars over their spots."""
    con.execute(f"""CREATE TEMP TABLE cm{res} AS
        WITH c AS (SELECT h3, ST_Transform(ST_Centroid(geom), 5070) AS p FROM hex WHERE res = %s)
        SELECT DISTINCT ON (sh.h3) sh.h3, mk.market
        FROM station_hex sh JOIN mk USING (facility_id) JOIN c USING (h3) JOIN mkc USING (market)
        WHERE sh.res = %s ORDER BY sh.h3, mkc.sells DESC, ST_Distance(c.p, mk.p)""", (res, res))
    con.execute(f"""CREATE TEMP TABLE inw{res} AS
        SELECT sh.facility_id, sh.h3, sh.coverage_share AS cov, COALESCE(h.pop, 0) * sh.coverage_share AS w
        FROM station_hex sh JOIN hex h USING (h3) JOIN cm{res} cm USING (h3)
        JOIN mk ON mk.facility_id = sh.facility_id AND mk.market = cm.market WHERE sh.res = %s""", (res,))
    con.execute(f"CREATE TEMP TABLE reach{res} AS SELECT facility_id, SUM(w) AS r FROM inw{res} GROUP BY 1")
    has7 = res == 8 and con.execute("SELECT to_regclass('pg_temp.reach7')").fetchone()[0]
    reach = (f"(SELECT facility_id, COALESCE(r7.r, r8.r) AS r FROM reach8 r8 LEFT JOIN reach7 r7 USING (facility_id))" if has7 else f"reach{res}")
    out = {}
    for h, pp, inv, spots in con.execute(f"""
        SELECT i.h3, SUM(st.booked * i.cov / NULLIF(r.r, 0)), SUM(pr.g), SUM(pr.n)
        FROM inw{res} i JOIN {reach} r USING (facility_id) JOIN station_total st USING (facility_id)
        LEFT JOIN price pr USING (facility_id) GROUP BY 1"""):
        out[h] = (float(pp or 0), float(inv) / float(spots) if spots else None)
    return out


def hex_features(con, res, fh, fine_parents=(), mm=None):
    maxima = {"booked": 0, "invoiced": 0, "spots": 0, "pp": 0, "ps": 0, "stations": 0}
    vals = {k: [] for k in maxima}
    n = 0
    complete = res == max(ZOOMS)             # finest res: every cell is a feature, so the mosaic has no holes
    sql = ("SELECT h.h3, t.booked, t.invoiced, t.spots_aired, h.pop, t.stations_with_buys FROM hex h LEFT JOIN hex_total t USING (h3) WHERE h.res=%s" if complete
           else "SELECT h3, booked, invoiced, spots_aired, pop, stations_with_buys FROM hex_total WHERE res=%s")
    for h, booked, invoiced, spots, pop, stations in con.execute(sql, (res,)):
        booked, invoiced, spots, pop = float(booked or 0), float(invoiced or 0), float(spots or 0), float(pop or 0)
        if not complete and booked <= 0 and spots <= 0:
            continue
        pp, ps = (mm or {}).get(h, (0, None))
        props = {"h3": h, "booked": round(booked), "invoiced": round(invoiced), "spots": round(spots), "pop": round(pop), "stations": stations or 0,
                 "pp": round(pp, 2)}
        if ps:
            props["ps"] = round(ps)                # absent where no in-market station reports airings: the map leaves it blank
        if h in fine_parents:
            props["fine"] = 1
        ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(h)]; ring.append(ring[0])
        fh.write(json.dumps({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}) + "\n")
        for k in vals:
            if k in props:
                vals[k].append(props[k])
        n += 1
    for k, v in vals.items():
        v.sort(); maxima[k] = v[int(len(v) * 0.985)] if v else 1       # 98.5th percentile, same as the JSON layer used
    return n, maxima


def contour_features(fh):
    d = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))
    for s in d["stations"]:
        coords = [[[[lon, lat] for lat, lon in poly]] for poly in s["polys"]]
        fh.write(json.dumps({"type": "Feature", "properties": {"fac": s["fac"], "call": s["call"], "state": s["state"], "svc": s["svc"]},
                             "geometry": {"type": "MultiPolygon", "coordinates": coords}}) + "\n")
    return len(d["stations"])


def tippecanoe(src, dest, layer, zmin, zmax, extra=()):
    cmd = ["tippecanoe", "-o", dest, "--force", "-l", layer, "-Z", zmin, "-z", zmax, "--no-feature-limit", "--no-tile-size-limit",
           "--detect-shared-borders", "--simplification=4", "--quiet", *extra, src]
    subprocess.run(cmd, check=True)


def main():
    with Stage('tiles') as st:
        build(st)


def build(st):
    os.makedirs(OUT, exist_ok=True)
    meta = {"hex": {}}
    with pg.connect() as con, tempfile.TemporaryDirectory() as td:
        n_mk, n_sell = markets(con)
        meta["markets"] = {"eps_km": MARKET_EPS_M / 1000, "min_docs": MARKET_MIN_DOCS, "min_spots": MARKET_MIN_SPOTS, "markets": n_mk, "selling": n_sell}
        log.info(f"  {n_mk} transmitter markets, {n_sell} with political files")
        # res-7 cells whose seven children exist at res 8 (ingest.geo "metro" scope)
        fine_parents = {h3.cell_to_parent(h, 7) for (h,) in con.execute("SELECT h3 FROM hex WHERE res = 8")}
        for res, (zmin, zmax) in ZOOMS.items():
            if not con.execute("SELECT 1 FROM hex WHERE res = %s LIMIT 1", (res,)).fetchone():
                log.info(f"  res {res}: no cells in hex yet (run ingest.geo); skipped"); continue
            t0 = time.time()
            src = os.path.join(td, f"hex{res}.json")
            mm = market_metrics(con, res)
            with open(src, "w") as fh:
                n, maxima = hex_features(con, res, fh, fine_parents if res == 7 else (), mm)
            tippecanoe(src, os.path.join(OUT, f"hex{res}.pmtiles"), f"hex{res}", zmin, zmax)
            st.count(f"hex{res}_cells", n)
            size = os.path.getsize(os.path.join(OUT, f"hex{res}.pmtiles"))
            meta["hex"][str(res)] = {"cells": n, "max": maxima, "minzoom": int(zmin), "maxzoom": int(zmax), "bytes": size, "fine_parents": len(fine_parents) if res == 7 else None}
            log.info(f"  hex{res}.pmtiles: {n} cells, {size/1e6:.1f} MB, {time.time()-t0:.0f}s")
        src = os.path.join(td, "contours.json")
        with open(src, "w") as fh:
            n = contour_features(fh)
        tippecanoe(src, os.path.join(OUT, "contours.pmtiles"), "contours", "3", "10", ("--coalesce-densest-as-needed",))
        log.info(f"  contours.pmtiles: {n} stations, {os.path.getsize(os.path.join(OUT, 'contours.pmtiles'))/1e6:.1f} MB")
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"))


if __name__ == "__main__":
    main()

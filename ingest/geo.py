#!/usr/bin/env python3
"""Geography: counties with population, H3 cells with population, and station coverage shares.

  python3 -m ingest.geo            # everything (downloads Census files to data/geo on first run)

Resolutions come from HEX_RES. Coarse resolutions are built nationwide; fine ones only inside
the contours of stations that have political files loaded ("active"), so the fine layers grow
with the crawl. Adding a resolution is a one-line change here plus a rerun.
"""
import io, json, logging, os, sys, time, urllib.request, zipfile
import h3, shapefile
from shapely.geometry import shape
from . import pg
from .runlog import Stage
log = logging.getLogger('ingest.geo')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "data", "geo")
HEX_RES = {5: "national", 7: "active"}         # res -> scope
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
POP_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv"  # no API key needed
UA = "tv-wormhole/0.1 (research prototype)"


def fetch(url, dest):
    if not os.path.exists(dest):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as fh:
            fh.write(r.read())
    return dest


def load_counties(con):
    os.makedirs(GEO, exist_ok=True)
    z = zipfile.ZipFile(fetch(COUNTY_URL, os.path.join(GEO, "cb_2023_us_county_500k.zip")))
    names = {os.path.splitext(n)[1]: n for n in z.namelist()}
    rd = shapefile.Reader(shp=io.BytesIO(z.read(names[".shp"])), dbf=io.BytesIO(z.read(names[".dbf"])), shx=io.BytesIO(z.read(names[".shx"])))
    import csv
    pop = {}
    with open(fetch(POP_URL, os.path.join(GEO, "co-est2024-alldata.csv")), encoding="latin-1") as fh:
        for row in csv.DictReader(fh):
            if row["SUMLEV"] == "050":                       # county rows (040 = state totals)
                pop[row["STATE"] + row["COUNTY"]] = int(row["POPESTIMATE2024"])
    rows = []
    for sr in rd.iterShapeRecords():
        rec = sr.record.as_dict()
        g = shape(sr.shape.__geo_interface__)
        if g.geom_type == "Polygon":
            from shapely.geometry import MultiPolygon
            g = MultiPolygon([g])
        rows.append((rec["GEOID"], rec["NAME"], rec["STUSPS"], pop.get(rec["GEOID"]), g.wkt))
    with con.cursor() as cur:
        cur.execute("TRUNCATE county")
        cur.executemany("INSERT INTO county(geoid,name,state,pop,geom) VALUES (%s,%s,%s,%s,ST_Multi(ST_MakeValid(ST_GeomFromText(%s,4326))))", rows)
    con.commit()
    log.info(f"counties: {len(rows)} (with population: {sum(1 for r in rows if r[3])})")


def contour_cells(polys, res):
    cells = set()
    for poly in polys:                           # poly = [[lat, lon], ...]
        try:
            cells |= set(h3.geo_to_cells(h3.LatLngPoly([(la, lo) for la, lo in poly]), res))
        except Exception as e:
            log.info(f"  skip polygon: {e}")
    return cells


def build_hexes(con):
    stations = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))["stations"]
    active = {r[0] for r in con.execute("SELECT DISTINCT facility_id FROM opif_file")}
    cells = {}
    for res, scope in HEX_RES.items():
        for s in stations:
            if scope == "active" and s["fac"] not in active:
                continue
            for c in contour_cells(s["polys"], res):
                cells[c] = res
        log.info(f"res {res} ({scope}): {sum(1 for r in cells.values() if r == res)} cells")
    with con.cursor() as cur:
        cur.execute("TRUNCATE hex, station_hex")
        cur.execute("CREATE TEMP TABLE t_hex (h3 text, res smallint, wkt text) ON COMMIT DROP")
        with cur.copy("COPY t_hex (h3, res, wkt) FROM STDIN") as cp:
            for c, res in cells.items():
                ring = ",".join(f"{lo} {la}" for la, lo in h3.cell_to_boundary(c))
                first = h3.cell_to_boundary(c)[0]
                cp.write_row((c, res, f"POLYGON(({ring},{first[1]} {first[0]}))"))
        cur.execute("INSERT INTO hex(h3,res,geom) SELECT h3, res, ST_GeomFromText(wkt,4326) FROM t_hex")
        t0 = time.time()
        cur.execute("""UPDATE hex h SET pop = x.pop FROM (
                         SELECT h.h3, SUM(c.pop * ST_Area(ST_Intersection(h.geom, c.geom)) / NULLIF(ST_Area(c.geom), 0)) AS pop
                         FROM hex h JOIN county c ON ST_Intersects(h.geom, c.geom) WHERE c.pop IS NOT NULL GROUP BY h.h3) x
                       WHERE x.h3 = h.h3""")
        log.info(f"hex population allocated in {time.time()-t0:.0f}s")
        t0 = time.time()
        cur.execute("""INSERT INTO station_hex(facility_id,h3,res,coverage_share)
                       SELECT s.facility_id, h.h3, h.res,
                              LEAST(1.0, ST_Area(ST_Intersection(h.geom, s.contour)) / NULLIF(ST_Area(h.geom), 0))
                       FROM station s JOIN hex h ON ST_Intersects(h.geom, s.contour)
                       WHERE h.res = ANY(%s) OR s.facility_id = ANY(%s)""",
                    ([r for r, sc in HEX_RES.items() if sc == "national"], list(active)))
        log.info(f"station_hex built in {time.time()-t0:.0f}s")
    con.commit()
    with con.cursor() as cur:
        for t in ("hex", "station_hex"):
            log.info(f"  {t}: {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")


def main():
    with Stage('geo') as st, pg.connect() as con:
        load_counties(con)
        build_hexes(con)
        for t in ('county', 'hex', 'station_hex'):
            st.count(t, con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])


if __name__ == "__main__":
    main()

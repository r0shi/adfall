#!/usr/bin/env python3
"""Geography: counties (names, 2024 population), Census tracts (population), H3 cells with population, and station coverage shares.

  python3 -m ingest.geo            # everything (downloads Census files to data/geo on first run)

Resolutions come from HEX_RES. Res 5 ("national") is built inside every station's contour; res 7 ("active")
only inside the contours of stations that have political files loaded, so it grows with the crawl; res 8
("metro") is the seven children of every res-7 cell whose population density is at least METRO_DENSITY
people per km², so the finest cells exist where people are dense enough for a 0.7 km² cell to mean something.
Cell population is the sum over intersecting Census tracts of tract population × (overlap area / tract area);
tract population is the ACS 2019-2023 five-year total (B01003) rescaled inside each county so the tracts sum
to the county's 2024 estimate. Coverage shares are contour∩cell area / cell area per station and cell.
"""
import csv, io, json, logging, os, sys, time, urllib.request, zipfile
import h3, shapefile
from shapely.geometry import shape, MultiPolygon
from . import pg
from .runlog import Stage
log = logging.getLogger('ingest.geo')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "data", "geo")
HEX_RES = {5: "national", 7: "active", 8: "metro"}         # res -> scope
METRO_DENSITY = 150            # people per km² of a res-7 cell (tract-derived) for its children to exist at res 8 (~500k cells on 2026-10-26)
METRO_TARGET = 500_000         # logged only: the density that would give this many res-8 cells, to retune METRO_DENSITY
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
POP_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv"  # no API key needed
TRACT_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_tract_500k.zip"
ACS_URL = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-b01003.dat"  # B01003 for every geography, no key
UA = "adfall/0.1 (research prototype)"


def fetch(url, dest):
    if not os.path.exists(dest):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as fh:
            fh.write(r.read())
    return dest


def shp_reader(zip_path):
    z = zipfile.ZipFile(zip_path)
    names = {os.path.splitext(n)[1]: n for n in z.namelist()}
    return shapefile.Reader(shp=io.BytesIO(z.read(names[".shp"])), dbf=io.BytesIO(z.read(names[".dbf"])), shx=io.BytesIO(z.read(names[".shx"])))


def load_counties(con):
    os.makedirs(GEO, exist_ok=True)
    rd = shp_reader(fetch(COUNTY_URL, os.path.join(GEO, "cb_2023_us_county_500k.zip")))
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
            g = MultiPolygon([g])
        rows.append((rec["GEOID"], rec["NAME"], rec["STUSPS"], pop.get(rec["GEOID"]), g.wkt))
    with con.cursor() as cur:
        cur.execute("TRUNCATE county")
        cur.executemany("INSERT INTO county(geoid,name,state,pop,geom) VALUES (%s,%s,%s,%s,ST_Multi(ST_MakeValid(ST_GeomFromText(%s,4326))))", rows)
    con.commit()
    log.info(f"counties: {len(rows)} (with population: {sum(1 for r in rows if r[3])}); 2024 estimate total {sum(r[3] or 0 for r in rows):,}")


def load_tracts(con):
    """Census tracts with population. ACS 5-year totals are a 2019-2023 period estimate (332.4M nationally), the county
    table carries the 2024 vintage estimate (340.1M); each tract keeps its ACS share of its county, applied to the
    county's 2024 total, so the tract layer sums to the county layer wherever a county has an estimate."""
    acs = {}
    with open(fetch(ACS_URL, os.path.join(GEO, "acsdt5y2023-b01003.dat"))) as fh:
        for line in fh:
            geo, est, _m = line.rstrip("\n").split("|")
            if geo.startswith("1400000US"):                   # summary level 140 = tract
                acs[geo[9:]] = max(0, int(est)) if est.lstrip("-").isdigit() else 0
    county_pop = {g: p for g, p in con.execute("SELECT geoid, pop FROM county WHERE pop IS NOT NULL")}
    acs_by_county = {}
    for g, p in acs.items():
        acs_by_county[g[:5]] = acs_by_county.get(g[:5], 0) + p
    factor = {c: county_pop[c] / s for c, s in acs_by_county.items() if c in county_pop and s > 0}
    rd = shp_reader(fetch(TRACT_URL, os.path.join(GEO, "cb_2023_us_tract_500k.zip")))
    n = 0
    with con.cursor() as cur:
        cur.execute("TRUNCATE tract")
        cur.execute("CREATE TEMP TABLE t_tract (geoid text, state text, county text, name text, pop_acs int, pop float8, aland bigint, wkb text)")
        with cur.copy("COPY t_tract FROM STDIN") as cp:
            for sr in rd.iterShapeRecords():
                rec = sr.record.as_dict()
                g = shape(sr.shape.__geo_interface__)
                if g.geom_type == "Polygon":
                    g = MultiPolygon([g])
                geoid = rec["GEOID"]
                p = acs.get(geoid, 0)
                cp.write_row((geoid, rec["STUSPS"], geoid[:5], rec["NAMELSAD"], p, p * factor.get(geoid[:5], 1.0), int(rec["ALAND"]), g.wkb_hex))
                n += 1
        cur.execute("""INSERT INTO tract(geoid,state,county,name,pop_acs,pop,aland,geom)
                       SELECT geoid, state, county, name, pop_acs, pop, aland, ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromWKB(decode(wkb,'hex')),4326))) FROM t_tract""")
        cur.execute("DROP TABLE t_tract")
        cur.execute("ANALYZE tract")
        acs_total, scaled_total, county_total = cur.execute("SELECT SUM(pop_acs), SUM(pop), (SELECT SUM(pop) FROM county) FROM tract").fetchone()
    con.commit()
    log.info(f"tracts: {n:,} ({len(acs):,} with ACS rows); ACS 2019-2023 total {acs_total:,}; rescaled to county 2024 estimates: {scaled_total:,.0f} vs counties {county_total:,}")


def contour_cells(polys, res):
    cells = set()
    for poly in polys:                           # poly = [[lat, lon], ...]
        try:
            cells |= set(h3.geo_to_cells(h3.LatLngPoly([(la, lo) for la, lo in poly]), res))
        except Exception as e:
            log.info(f"  skip polygon: {e}")
    return cells


def insert_cells(cur, cells):
    """cells: {h3: res}. Appends to hex (geometry from the H3 boundary)."""
    cur.execute("CREATE TEMP TABLE t_hex (h3 text, res smallint, wkt text)")
    with cur.copy("COPY t_hex (h3, res, wkt) FROM STDIN") as cp:
        for c, res in cells.items():
            b = h3.cell_to_boundary(c)
            ring = ",".join(f"{lo} {la}" for la, lo in b)
            cp.write_row((c, res, f"POLYGON(({ring},{b[0][1]} {b[0][0]}))"))
    cur.execute("INSERT INTO hex(h3,res,geom) SELECT h3, res, ST_GeomFromText(wkt,4326) FROM t_hex")
    cur.execute("DROP TABLE t_hex")


# share of tract t that lies inside cell h (whole tracts inside a cell count fully; a cell inside one tract takes the
# tract's density × its area; only the straddling pairs pay for a polygon intersection)
TRACT_SHARE = """CASE WHEN ST_Contains(h.geom, t.geom) THEN 1.0
                      WHEN ST_Contains(t.geom, h.geom) THEN ST_Area(h.geom) / NULLIF(ST_Area(t.geom), 0)
                      ELSE ST_Area(ST_Intersection(h.geom, t.geom)) / NULLIF(ST_Area(t.geom), 0) END"""


def allocate_population(cur, res_list):
    """hex.pop = Σ over intersecting tracts of tract pop × TRACT_SHARE. Cells touching no populated tract stay NULL."""
    t0 = time.time()
    cur.execute("ANALYZE hex")
    cur.execute(f"""CREATE TEMP TABLE t_pop AS
                    SELECT h.h3, SUM(t.pop * {TRACT_SHARE}) AS pop
                    FROM hex h JOIN tract t ON ST_Intersects(h.geom, t.geom)
                    WHERE t.pop > 0 AND h.res = ANY(%s) GROUP BY h.h3""", (list(res_list),))
    cur.execute("UPDATE hex h SET pop = t.pop FROM t_pop t WHERE t.h3 = h.h3")
    cur.execute("DROP TABLE t_pop")
    for res in res_list:
        n, tot = cur.execute("SELECT COUNT(*), COALESCE(SUM(pop), 0) FROM hex WHERE res = %s", (res,)).fetchone()
        log.info(f"  res {res}: {n:,} cells, tract-derived population {tot:,.0f}")
    log.info(f"population allocated for res {list(res_list)} in {time.time()-t0:.0f}s")


def county_check(cur):
    """The old county-area spread at res 5, for the log: the tract-based national total must stay within 1% of it.
    Compared over the counties that have a 2024 estimate (Puerto Rico has tracts and ACS counts but no estimate, so its
    tracts keep their ACS value and are left out of this comparison)."""
    t0 = time.time()
    (county_based,) = cur.execute("""SELECT SUM(x.pop) FROM (
                                       SELECT h.h3, SUM(c.pop * ST_Area(ST_Intersection(h.geom, c.geom)) / NULLIF(ST_Area(c.geom), 0)) AS pop
                                       FROM hex h JOIN county c ON ST_Intersects(h.geom, c.geom) WHERE c.pop IS NOT NULL AND h.res = 5 GROUP BY h.h3) x""").fetchone()
    (tract_based,) = cur.execute(f"""SELECT SUM(x.pop) FROM (
                                       SELECT h.h3, SUM(t.pop * {TRACT_SHARE}) AS pop
                                       FROM hex h JOIN tract t ON ST_Intersects(h.geom, t.geom) JOIN county c ON c.geoid = t.county
                                       WHERE c.pop IS NOT NULL AND t.pop > 0 AND h.res = 5 GROUP BY h.h3) x""").fetchone()
    (all_tracts,) = cur.execute("SELECT SUM(pop) FROM hex WHERE res = 5").fetchone()
    diff = abs(tract_based - county_based) / county_based if county_based else 0
    msg = (f"res 5 national population over counties with a 2024 estimate: tract-based {tract_based:,.0f} vs county-based {county_based:,.0f} "
           f"({diff:.2%} apart; {all_tracts:,.0f} with every tract; {time.time()-t0:.0f}s)")
    if diff > 0.01:
        log.warning(msg)
    else:
        log.info(msg)
    return county_based, tract_based, diff


def build_hexes(con, st=None):
    stations = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))["stations"]
    active = {r[0] for r in con.execute("SELECT DISTINCT facility_id FROM opif_file")}
    cells = {}
    for res, scope in HEX_RES.items():
        if scope == "metro":
            continue                                   # derived from res-7 density below
        for s in stations:
            if scope == "active" and s["fac"] not in active:
                continue
            for c in contour_cells(s["polys"], res):
                cells[c] = res
        log.info(f"res {res} ({scope}): {sum(1 for r in cells.values() if r == res)} cells")
    with con.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 6")
        cur.execute("SET LOCAL work_mem = '256MB'")
        cur.execute("TRUNCATE hex, station_hex")
        insert_cells(cur, cells)
        allocate_population(cur, [r for r, sc in HEX_RES.items() if sc != "metro"])
        county_based, tract_based, diff = county_check(cur)
        # metro: res-8 children of dense res-7 cells
        metro_res = [r for r, sc in HEX_RES.items() if sc == "metro"]
        if metro_res:
            (res8,) = metro_res
            parents = [h for (h,) in cur.execute("SELECT h3 FROM hex WHERE res = 7 AND pop / (ST_Area(geom::geography) / 1e6) >= %s", (METRO_DENSITY,))]
            (at_target,) = cur.execute("SELECT pop / (ST_Area(geom::geography) / 1e6) AS d FROM hex WHERE res = 7 AND pop > 0 ORDER BY d DESC OFFSET %s LIMIT 1", (METRO_TARGET // 7,)).fetchone() or (None,)
            children = {c: res8 for p in parents for c in h3.cell_to_children(p, res8)}
            extra = f" (a threshold of {at_target:,.0f}/km² would give {METRO_TARGET:,})" if at_target else ""
            log.info(f"res {res8} (metro): {len(parents):,} res-7 cells at >= {METRO_DENSITY} people/km² -> {len(children):,} cells{extra}")
            insert_cells(cur, children)
            allocate_population(cur, [res8])
            if st:
                st.count("metro_density", METRO_DENSITY); st.count("metro_parents", len(parents))
        t0 = time.time()
        cur.execute("""INSERT INTO station_hex(facility_id,h3,res,coverage_share)
                       SELECT s.facility_id, h.h3, h.res,
                              CASE WHEN ST_Contains(s.contour, h.geom) THEN 1.0
                                   ELSE LEAST(1.0, ST_Area(ST_Intersection(h.geom, s.contour)) / NULLIF(ST_Area(h.geom), 0)) END
                       FROM station s JOIN hex h ON ST_Intersects(h.geom, s.contour)
                       WHERE h.res = ANY(%s) OR s.facility_id = ANY(%s)""",
                    ([r for r, sc in HEX_RES.items() if sc == "national"], list(active)))
        log.info(f"station_hex built in {time.time()-t0:.0f}s")
    con.commit()
    if st:
        st.count("pop_res5_county_based", round(county_based)); st.count("pop_res5_tract_based", round(tract_based))
    with con.cursor() as cur:
        for t in ("hex", "station_hex"):
            log.info(f"  {t}: {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:,}")


def main():
    with Stage('geo') as st, pg.connect() as con:
        for name, fn in (("counties", load_counties), ("tracts", load_tracts), ("hexes", lambda c: build_hexes(c, st))):
            t0 = time.time(); fn(con); log.info(f"{name}: {time.time()-t0:.0f}s"); st.count(f"{name}_seconds", round(time.time() - t0))
        for t in ('county', 'tract', 'hex', 'station_hex'):
            st.count(t, con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
        for res, n in con.execute('SELECT res, COUNT(*) FROM hex GROUP BY 1 ORDER BY 1'):
            st.count(f"hex_r{res}", n)


if __name__ == "__main__":
    main()

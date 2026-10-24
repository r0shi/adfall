#!/usr/bin/env python3
"""Load stations (web/data/stations.json) and the crawl store (data/political.sqlite) into Postgres.

Idempotent: rows are upserted by primary key. Run after every crawl/parse.
  python3 -m ingest.load_pg [--db data/political.sqlite]
"""
import argparse, datetime, json, os, re, sqlite3, sys
from . import pg, db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUPS = [  # licensee pattern -> station group
    (r"hearst", "Hearst"), (r"tegna|pacific and southern|sander|king broadcasting", "Tegna"),
    (r"nexstar|tribune|mission broadcasting|white knight", "Nexstar"), (r"sinclair|\bkdsm\b|chesapeake|cunningham|deerfield", "Sinclair"),
    (r"gray ", "Gray"), (r"scripps", "Scripps"), (r"\bcbs\b|viacom|paramount", "CBS"), (r"nbc|comcast|telemundo", "NBCUniversal"),
    (r"fox television|new world communications|fox tv", "Fox"), (r"abc|disney|american broadcasting", "ABC"),
    (r"cox media|georgia television", "Cox"), (r"graham media", "Graham"), (r"hubbard", "Hubbard"), (r"meredith", "Meredith"),
    (r"allen media|allen ", "Allen Media"), (r"ion television|ion media", "Ion"), (r"univision|televisa", "Univision"),
    (r"entravision", "Entravision"), (r"weigel", "Weigel"), (r"public broadcasting|educational|board of education|university|regents|state of|commission", "Public"),
    (r"trinity|christian|ministries|daystar|religious|catholic|church", "Religious"),
]


def station_group(licensee):
    l = (licensee or "").lower()
    for rx, g in GROUPS:
        if re.search(rx, l):
            return g
    return None


def wkt_multipolygon(polys):
    rings = []
    for poly in polys:
        pts = ",".join(f"{lon} {lat}" for lat, lon in poly)
        rings.append(f"(({pts}))")
    return "MULTIPOLYGON(" + ",".join(rings) + ")"


def load_stations(con):
    d = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))
    rows = []
    for s in d["stations"]:
        rows.append((s["fac"], s["call"], s["svc"], s["city"], s["state"], s["licensee"], station_group(s["licensee"]),
                     s["rf"], s["vchan"], f"POINT({s['tx'][1]} {s['tx'][0]})", wkt_multipolygon(s["polys"]),
                     (s.get("newson") or {}).get("id"), s["slug"]))
    with con.cursor() as cur:
        cur.executemany("""INSERT INTO station(facility_id,call,service,city,state,licensee,station_group,rf_channel,virtual_channel,tx,contour,newson_id,public_file_slug)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),ST_Multi(ST_MakeValid(ST_GeomFromText(%s,4326))),%s,%s)
            ON CONFLICT (facility_id) DO UPDATE SET call=EXCLUDED.call, service=EXCLUDED.service, city=EXCLUDED.city, state=EXCLUDED.state,
              licensee=EXCLUDED.licensee, station_group=EXCLUDED.station_group, rf_channel=EXCLUDED.rf_channel, virtual_channel=EXCLUDED.virtual_channel,
              tx=EXCLUDED.tx, contour=EXCLUDED.contour, newson_id=EXCLUDED.newson_id, public_file_slug=EXCLUDED.public_file_slug, updated_at=now()""", rows)
    con.commit()
    print(f"stations: {len(rows)}", file=sys.stderr)


def load_files(con, sqlite_path):
    sq = sqlite3.connect(sqlite_path); sq.row_factory = sqlite3.Row
    known = {r[0] for r in con.execute("SELECT facility_id FROM station")}
    files = [r for r in sq.execute("SELECT * FROM files") if r["facility_id"] in known]
    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE t_files (LIKE opif_file INCLUDING DEFAULTS) ON COMMIT DROP")
        with cur.copy("COPY t_files(file_id,facility_id,year,folder_path,file_name,size_bytes,fcc_created_at,downloaded_at,deleted_at,local_path) FROM STDIN") as cp:
            for r in files:
                cp.write_row((r["file_manager_id"], r["facility_id"], r["year"], r["folder_path"], r["file_name"], r["file_size"], r["create_ts"],
                              datetime.datetime.now() if r["downloaded"] else None, datetime.datetime.now() if r["deleted"] else None, r["local_path"]))
        cur.execute("""INSERT INTO opif_file SELECT * FROM t_files
                       ON CONFLICT (file_id) DO UPDATE SET folder_path=EXCLUDED.folder_path, file_name=EXCLUDED.file_name, size_bytes=EXCLUDED.size_bytes,
                         downloaded_at=COALESCE(opif_file.downloaded_at, EXCLUDED.downloaded_at), deleted_at=EXCLUDED.deleted_at, local_path=EXCLUDED.local_path""")
        docs = [r for r in sq.execute("SELECT d.*, f.facility_id FROM docs d JOIN files f USING(file_manager_id)") if r["facility_id"] in known]
        cur.execute("CREATE TEMP TABLE t_docs (LIKE document INCLUDING DEFAULTS) ON COMMIT DROP")
        with cur.copy("COPY t_docs(file_id,kind,template,source,parse_status,parser_version,raw) FROM STDIN") as cp:
            for r in docs:
                fields = json.loads(r["fields"] or "{}")
                raw = {k: r[k] for k in ("order_no", "revision", "invoice_no", "advertiser", "agency", "product", "flight_start", "flight_end",
                                         "print_date", "gross", "net", "spots")}
                raw["ad_ids"] = json.loads(r["ad_ids"] or "[]"); raw["fields"] = fields
                cp.write_row((r["file_manager_id"], r["kind"], fields.get("template"), fields.get("source"), r["parse_status"], r["parser_version"], json.dumps(raw)))
        cur.execute("""INSERT INTO document SELECT * FROM t_docs
                       ON CONFLICT (file_id) DO UPDATE SET kind=EXCLUDED.kind, template=EXCLUDED.template, source=EXCLUDED.source,
                         parse_status=EXCLUDED.parse_status, parser_version=EXCLUDED.parser_version, parsed_at=now(), raw=EXCLUDED.raw""")
    con.commit()
    print(f"opif_file: {len(files)}  document: {len(docs)}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=db.DEFAULT_DB)
    ap.add_argument("--skip-stations", action="store_true")
    a = ap.parse_args()
    with pg.connect() as con:
        if not a.skip_stations:
            load_stations(con)
        load_files(con, a.db)


if __name__ == "__main__":
    main()

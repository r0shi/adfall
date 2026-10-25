#!/usr/bin/env python3
"""Pipeline status: what has been listed, downloaded, OCR'd, parsed and loaded, per station and overall,
which stages are running or failed last, and what is stuck.

  python3 -m ingest.status                 # overall + per-stage last runs + problem list
  python3 -m ingest.status --stations      # add a per-station table (sorted by pending work)
  python3 -m ingest.status --state PA      # per-station table for one state
  python3 -m ingest.status --json          # machine-readable (used by ingest.batch and the About page export)
Reads SQLite only (never blocks a running stage: WAL mode) plus the lock files; Postgres counts are
included when it is reachable.
"""
import argparse, collections, datetime, json, os, sys
from . import db
from .runlog import run_db, lock_holder, last_runs, LOCK_DIR, ROOT

STAGES = ["crawl", "update", "ocr", "parse", "load_pg", "entities", "identity", "geo", "marts", "export", "tiles", "batch"]


def overall(con):
    o = {}
    r = con.execute("""SELECT COUNT(*), SUM(downloaded), SUM(deleted), SUM(downloaded=0 AND deleted=0),
                              SUM(downloaded=0 AND deleted=0 AND download_attempts>=5), COUNT(DISTINCT facility_id), SUM(local_size)
                       FROM files""").fetchone()
    o["files"] = {"listed": r[0], "downloaded": r[1] or 0, "deleted": r[2] or 0, "pending": r[3] or 0, "given_up": r[4] or 0, "stations": r[5], "gb_on_disk": round((r[6] or 0) / 1e9, 2)}
    o["listing"] = dict(con.execute("SELECT status, COUNT(*) FROM listing GROUP BY 1").fetchall())
    o["by_year"] = {str(y): {"listed": n, "downloaded": d or 0} for y, n, d in con.execute("SELECT year, COUNT(*), SUM(downloaded) FROM files WHERE deleted=0 GROUP BY 1")}
    r = con.execute("""SELECT COUNT(*), SUM(parse_status='ok'), SUM(parse_status='partial'), SUM(parse_status='failed'), SUM(parse_status='unrecognized'),
                              SUM(json_extract(fields,'$.needs_ocr')=1), SUM(error IS NOT NULL), SUM(json_extract(fields,'$.source')='ocr') FROM docs""").fetchone()
    o["docs"] = {"parsed": r[0], "ok": r[1] or 0, "partial": r[2] or 0, "failed": r[3] or 0, "unrecognized": r[4] or 0, "needs_ocr": r[5] or 0, "parser_crashes": r[6] or 0, "from_ocr": r[7] or 0}
    o["docs"]["unparsed_downloads"] = con.execute("SELECT COUNT(*) FROM files f WHERE downloaded=1 AND deleted=0 AND NOT EXISTS (SELECT 1 FROM docs d WHERE d.file_manager_id=f.file_manager_id)").fetchone()[0]
    o["kinds"] = {}
    for k, t, s, n in con.execute("SELECT kind, json_extract(fields,'$.template'), parse_status, COUNT(*) FROM docs GROUP BY 1,2,3 ORDER BY 4 DESC"):
        o["kinds"][f"{k}/{t or '-'}/{s}"] = n
    r = con.execute("SELECT COUNT(*), SUM(status='ok'), SUM(status='failed'), SUM(status='failed' AND attempts>=3), SUM(pages_done), SUM(seconds) FROM ocr").fetchone()
    o["ocr"] = {"attempted": r[0], "ok": r[1] or 0, "failed": r[2] or 0, "given_up": r[3] or 0, "pages": r[4] or 0, "cpu_hours": round((r[5] or 0) / 3600, 2)}
    o["ocr"]["pending"] = con.execute("""SELECT COUNT(*) FROM docs d LEFT JOIN ocr o USING(file_manager_id) WHERE json_extract(d.fields,'$.needs_ocr')=1
                                         AND (o.status IS NULL OR (o.status='failed' AND o.attempts<3))""").fetchone()[0]
    o["ocr"]["engines"] = dict(con.execute("SELECT engine, COUNT(*) FROM ocr WHERE status='ok' GROUP BY 1").fetchall())
    o["last_history_sync"] = (con.execute("SELECT value FROM meta WHERE key='last_history_sync'").fetchone() or [None])[0]
    return o


def pg_counts():
    try:
        from . import pg
        with pg.connect() as con:
            q = lambda s: con.execute(s).fetchone()[0]
            return {"opif_file": q("SELECT COUNT(*) FROM opif_file"), "document": q("SELECT COUNT(*) FROM document"), "orders": q("SELECT COUNT(*) FROM order_"),
                    "invoices": q("SELECT COUNT(*) FROM invoice"), "spots": q("SELECT COUNT(*) FROM spot"), "buyers": q("SELECT COUNT(*) FROM buyer"),
                    "entities_built_at": (con.execute("SELECT value FROM meta WHERE key='entities_built_at'").fetchone() or [None])[0]}
    except Exception as e:
        return {"error": str(e)[:200]}


def stages(con):
    runs = last_runs(con, 3)
    out = {}
    for s in STAGES:
        rs = runs.get(s, [])
        out[s] = {"running": lock_holder(s), "last": rs[0] if rs else None, "last_ok": next((r for r in rs if r["status"] == "ok"), None),
                  "failed_last": bool(rs) and rs[0]["status"] in ("failed", "killed")}
    return out


def per_station(con, state=None, pg_groups=None):
    rows = con.execute("""SELECT f.facility_id, COUNT(*) listed, SUM(f.downloaded) dl, SUM(f.downloaded=0 AND f.deleted=0) pend,
                                 SUM(f.downloaded=0 AND f.deleted=0 AND f.download_attempts>=5) gave_up,
                                 SUM(d.parse_status='ok') ok, SUM(d.parse_status='partial') partial, SUM(d.parse_status='failed') failed, SUM(d.kind='other') other,
                                 SUM(json_extract(d.fields,'$.needs_ocr')=1 AND o.status IS NULL) ocr_pend, SUM(o.status='ok') ocrd,
                                 SUM(f.downloaded=1 AND d.file_manager_id IS NULL) unparsed, MAX(f.downloaded_at), MAX(d.parsed_at)
                          FROM files f LEFT JOIN docs d USING(file_manager_id) LEFT JOIN ocr o USING(file_manager_id)
                          WHERE f.deleted=0 GROUP BY 1""").fetchall()
    listing = {(r[0], r[1]): (r[2], r[3]) for r in con.execute("SELECT facility_id, year, status, error FROM listing")}
    out = []
    for r in rows:
        info = (pg_groups or {}).get(r[0], {})
        if state and info.get("state") != state:
            continue
        ls = [f"{y}:{s}" for (f, y), (s, e) in listing.items() if f == r[0]]
        out.append({"fac": r[0], "call": info.get("call"), "state": info.get("state"), "group": info.get("group"), "listed": r[1], "downloaded": r[2] or 0, "pending": r[3] or 0,
                    "given_up": r[4] or 0, "ok": r[5] or 0, "partial": r[6] or 0, "failed": r[7] or 0, "other": r[8] or 0, "ocr_pending": r[9] or 0, "ocrd": r[10] or 0,
                    "unparsed": r[11] or 0, "last_download": r[12], "last_parse": r[13], "listing": ",".join(sorted(ls))})
    return out


def station_info():
    try:
        from . import pg
        with pg.connect() as con:
            return {r[0]: {"call": r[1], "state": r[2], "group": r[3]} for r in con.execute("SELECT facility_id, call, state, station_group FROM station")}
    except Exception:
        d = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))
        return {s["fac"]: {"call": s["call"], "state": s["state"], "group": None} for s in d["stations"]}


def fmt_run(r):
    if not r:
        return "never run"
    c = json.loads(r["counts"] or "{}")
    keys = [k for k in ("files_listed", "downloads_ok", "downloads_failed", "ok", "failed", "queued", "needs_ocr", "crashes", "opif_file", "document", "orders", "buyers") if k in c]
    s = f"{r['status']:7s} {r['started'][:16]} -> {(r['ended'] or '')[11:16] or '...':5s} " + " ".join(f"{k}={c[k]}" for k in keys)
    if r["failures"]:
        s += f" failures={r['failures']}"
    if r["error"]:
        s += f"  error: {r['error'][:90]}"
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", action="store_true", help="per-station table")
    ap.add_argument("--state")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    run_db(a.db).close()
    o = overall(con)
    st = stages(con)
    pgc = pg_counts()
    info = station_info() if (a.stations or a.state or a.json) else None
    if a.json:
        print(json.dumps({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "overall": o, "postgres": pgc,
                          "stages": {k: {"running": v["running"], "failed_last": v["failed_last"], "last": v["last"]} for k, v in st.items()},
                          "stations": per_station(con, a.state, info) if (a.stations or a.state) else None}, indent=1, default=str))
        return
    f, d, k, oc = o["files"], o["docs"], o["kinds"], o["ocr"]
    print(f"TV Wormhole pipeline status   {datetime.datetime.now():%Y-%m-%d %H:%M}   db={os.path.relpath(a.db, ROOT)}")
    print(f"  stations with files {f['stations']}   files listed {f['listed']:,}  downloaded {f['downloaded']:,} ({f['gb_on_disk']} GB)  pending {f['pending']:,}  given up {f['given_up']:,}  deleted {f['deleted']:,}")
    print(f"  listings: " + "  ".join(f"{s}={n}" for s, n in o["listing"].items()) + f"   by year: " + "  ".join(f"{y}: {v['downloaded']:,}/{v['listed']:,}" for y, v in o["by_year"].items()))
    print(f"  parsed {d['parsed']:,}  ok {d['ok']:,} ({100*d['ok']/max(1,d['parsed']):.1f}%)  partial {d['partial']:,}  failed {d['failed']:,}  unrecognized {d['unrecognized']:,}  unparsed downloads {d['unparsed_downloads']:,}  parser crashes {d['parser_crashes']:,}")
    print(f"  OCR: needed {d['needs_ocr'] + d['from_ocr']:,}  done {oc['ok']:,} ({oc['pages']:,} pages, {oc['cpu_hours']} cpu-h, engines {oc['engines']})  pending {oc['pending']:,}  failed {oc['failed']:,} (given up {oc['given_up']:,})")
    print(f"  last history sync: {o['last_history_sync']}   postgres: " + (f"opif_file {pgc['opif_file']:,}  document {pgc['document']:,}  orders {pgc['orders']:,}  invoices {pgc['invoices']:,}  spots {pgc['spots']:,}  buyers {pgc['buyers']:,}  entities built {pgc['entities_built_at']}" if "error" not in pgc else f"unreachable ({pgc['error']})"))
    print("\n  documents by kind / template / status:")
    for key, n in sorted(k.items(), key=lambda x: -x[1])[:28]:
        print(f"    {n:7,}  {key}")
    print("\n  stages (lock = running now; last run):")
    for s, v in st.items():
        flag = "RUNNING " if v["running"] else ("FAILED  " if v["failed_last"] else "        ")
        print(f"    {flag}{s:9s} {fmt_run(v['last'])}")
    problems = []
    if f["given_up"]:
        problems.append(f"{f['given_up']} downloads gave up after 5 attempts (crawl --retry-given-up)")
    if oc["given_up"]:
        problems.append(f"{oc['given_up']} documents failed OCR 3 times (ocr --retry-given-up)")
    if d["parser_crashes"]:
        problems.append(f"{d['parser_crashes']} documents crashed the parser (see docs.error)")
    bad_listing = con.execute("SELECT facility_id, year, status, error FROM listing WHERE status IN ('partial','failed')").fetchall()
    if bad_listing:
        problems.append(f"{len(bad_listing)} station-years with incomplete listings: " + ", ".join(f"{r[0]}/{r[1]}" for r in bad_listing[:8]))
    for s, v in st.items():
        if v["failed_last"]:
            problems.append(f"stage {s} {v['last']['status']} on its last run: {v['last']['error'] or ''} (log {v['last']['log_path']})")
    stale = [r for r in con.execute("SELECT stage, pid, started FROM pipeline_run WHERE status='running'") if not lock_holder(r[0])]
    for r in stale:
        problems.append(f"stage {r[0]} run from {r[1]} is marked running but holds no lock (died?); it will be marked killed on the stage's next run")
    print("\n  problems:" if problems else "\n  problems: none")
    for p in problems:
        print(f"    - {p}")
    if a.stations or a.state:
        rows = per_station(con, a.state, info)
        rows.sort(key=lambda r: (-(r["pending"] + r["ocr_pending"] + r["unparsed"]), -r["listed"]))
        print(f"\n  per station ({len(rows)}; sorted by pending work):")
        print(f"    {'fac':>6} {'call':8} {'st':2} {'group':12} {'listed':>6} {'dl':>6} {'pend':>5} {'ok':>6} {'part':>5} {'fail':>5} {'other':>5} {'ocr?':>5} {'ocrd':>5} {'unp':>4}  listing")
        for r in rows:
            print(f"    {r['fac']:>6} {(r['call'] or '?'):8} {(r['state'] or '?'):2} {(r['group'] or '?')[:12]:12} {r['listed']:>6} {r['downloaded']:>6} {r['pending']:>5} {r['ok']:>6} {r['partial']:>5} {r['failed']:>5} {r['other']:>5} {r['ocr_pending']:>5} {r['ocrd']:>5} {r['unparsed']:>4}  {r['listing']}")


if __name__ == "__main__":
    main()

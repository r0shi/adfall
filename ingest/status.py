#!/usr/bin/env python3
"""Pipeline status: what has been listed, downloaded, OCR'd, parsed and built into entities, per station and
overall, which stages are running or failed last, and what is stuck.

  python3 -m ingest.status                 # overall + per-stage last runs + problem list
  python3 -m ingest.status --stations      # add a per-station table (sorted by pending work)
  python3 -m ingest.status --state PA      # per-station table for one state
  python3 -m ingest.status --json          # machine-readable (used by ingest.batch and the About page export)
Reads Postgres (plain SELECTs; never blocks a running stage) plus the lock files in data/locks/.
"""
import argparse, datetime, json, os, sys
from . import db
from .runlog import lock_holder, last_runs, pid_alive, LOCK_DIR, ROOT

STAGES = ["crawl", "update", "ocr", "parse", "stations", "entities", "identity", "geo", "marts", "export", "tiles", "batch"]


def overall(con):
    o = {}
    r = con.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE downloaded), COUNT(*) FILTER (WHERE deleted_at IS NOT NULL),
                              COUNT(*) FILTER (WHERE NOT downloaded AND deleted_at IS NULL),
                              COUNT(*) FILTER (WHERE NOT downloaded AND deleted_at IS NULL AND download_attempts>=5), COUNT(DISTINCT facility_id), SUM(local_size)::bigint
                       FROM opif_file""").fetchone()
    o["files"] = {"listed": r[0], "downloaded": r[1] or 0, "deleted": r[2] or 0, "pending": r[3] or 0, "given_up": r[4] or 0, "stations": r[5], "gb_on_disk": round((r[6] or 0) / 1e9, 2)}
    o["listing"] = dict(con.execute("SELECT status, COUNT(*) FROM opif_listing GROUP BY 1 ORDER BY 1").fetchall())
    o["by_year"] = {str(y): {"listed": n, "downloaded": d or 0} for y, n, d in con.execute("SELECT year, COUNT(*), COUNT(*) FILTER (WHERE downloaded) FROM opif_file WHERE deleted_at IS NULL GROUP BY 1 ORDER BY 1")}
    r = con.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE parse_status='ok'), COUNT(*) FILTER (WHERE parse_status='partial'), COUNT(*) FILTER (WHERE parse_status='failed'),
                              COUNT(*) FILTER (WHERE parse_status='unrecognized'), COUNT(*) FILTER (WHERE needs_ocr), COUNT(*) FILTER (WHERE error IS NOT NULL),
                              COUNT(*) FILTER (WHERE source='ocr') FROM document""").fetchone()
    o["docs"] = {"parsed": r[0], "ok": r[1] or 0, "partial": r[2] or 0, "failed": r[3] or 0, "unrecognized": r[4] or 0, "needs_ocr": r[5] or 0, "parser_crashes": r[6] or 0, "from_ocr": r[7] or 0}
    o["docs"]["unparsed_downloads"] = con.execute("SELECT COUNT(*) FROM opif_file f WHERE downloaded AND deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM document d WHERE d.file_id=f.file_id)").fetchone()[0]
    o["kinds"] = {}
    for k, t, s, n in con.execute("SELECT kind, template, parse_status, COUNT(*) FROM document GROUP BY 1,2,3 ORDER BY 4 DESC"):
        o["kinds"][f"{k}/{t or '-'}/{s}"] = n
    r = con.execute("""SELECT COUNT(*), COUNT(*) FILTER (WHERE status='ok'), COUNT(*) FILTER (WHERE status='failed'), COUNT(*) FILTER (WHERE status='failed' AND attempts>=3),
                              SUM(pages_done)::bigint, SUM(seconds)::float FROM ocr""").fetchone()
    o["ocr"] = {"attempted": r[0], "ok": r[1] or 0, "failed": r[2] or 0, "given_up": r[3] or 0, "pages": r[4] or 0, "cpu_hours": round((r[5] or 0) / 3600, 2)}
    o["ocr"]["pending"] = con.execute("""SELECT COUNT(*) FROM document d LEFT JOIN ocr o USING (file_id) WHERE d.needs_ocr
                                         AND (o.status IS NULL OR (o.status='failed' AND o.attempts<3))""").fetchone()[0]
    o["ocr"]["engines"] = dict(con.execute("SELECT engine, COUNT(*) FROM ocr WHERE status='ok' GROUP BY 1 ORDER BY 1").fetchall())
    o["last_history_sync"] = (con.execute("SELECT value FROM meta WHERE key='last_history_sync'").fetchone() or [None])[0]
    return o


def pg_counts(con):
    try:
        q = lambda s: con.execute(s).fetchone()[0]
        return {"opif_file": q("SELECT COUNT(*) FROM opif_file"), "document": q("SELECT COUNT(*) FROM document"), "orders": q("SELECT COUNT(*) FROM order_"),
                "invoices": q("SELECT COUNT(*) FROM invoice"), "spots": q("SELECT COUNT(*) FROM spot"), "buyers": q("SELECT COUNT(*) FROM buyer"),
                "entities_built_at": (con.execute("SELECT value FROM meta WHERE key='entities_built_at'").fetchone() or [None])[0]}
    except Exception as e:
        con.rollback()
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
    rows = con.execute("""SELECT f.facility_id, COUNT(*) listed, COUNT(*) FILTER (WHERE f.downloaded) dl, COUNT(*) FILTER (WHERE NOT f.downloaded) pend,
                                 COUNT(*) FILTER (WHERE NOT f.downloaded AND f.download_attempts>=5) gave_up,
                                 COUNT(*) FILTER (WHERE d.parse_status='ok') ok, COUNT(*) FILTER (WHERE d.parse_status='partial') partial,
                                 COUNT(*) FILTER (WHERE d.parse_status='failed') failed, COUNT(*) FILTER (WHERE d.kind='other') other,
                                 COUNT(*) FILTER (WHERE d.needs_ocr AND o.status IS NULL) ocr_pend, COUNT(*) FILTER (WHERE o.status='ok') ocrd,
                                 COUNT(*) FILTER (WHERE f.downloaded AND d.file_id IS NULL) unparsed, MAX(f.downloaded_at), MAX(d.parsed_at)
                          FROM opif_file f LEFT JOIN document d USING (file_id) LEFT JOIN ocr o USING (file_id)
                          WHERE f.deleted_at IS NULL GROUP BY 1""").fetchall()
    listing = {(r[0], r[1]): (r[2], r[3]) for r in con.execute("SELECT facility_id, year, status, error FROM opif_listing")}
    out = []
    for r in rows:
        info = (pg_groups or {}).get(r[0], {})
        if state and info.get("state") != state:
            continue
        ls = [f"{y}:{s}" for (f, y), (s, e) in listing.items() if f == r[0]]
        out.append({"fac": r[0], "call": info.get("call"), "state": info.get("state"), "group": info.get("group"), "listed": r[1], "downloaded": r[2] or 0, "pending": r[3] or 0,
                    "given_up": r[4] or 0, "ok": r[5] or 0, "partial": r[6] or 0, "failed": r[7] or 0, "other": r[8] or 0, "ocr_pending": r[9] or 0, "ocrd": r[10] or 0,
                    "unparsed": r[11] or 0, "last_download": local(r[12]), "last_parse": local(r[13]), "listing": ",".join(sorted(ls))})
    return out


def station_info(con):
    return {r[0]: {"call": r[1], "state": r[2], "group": r[3]} for r in con.execute("SELECT facility_id, call, state, station_group FROM station")}


def local(ts):
    """timestamptz -> local ISO string (seconds), or None."""
    return ts.astimezone().isoformat(timespec="seconds") if ts else None


def fmt_run(r):
    if not r:
        return "never run"
    c = r["counts"] or {}
    keys = [k for k in ("files_listed", "downloads_ok", "downloads_failed", "ok", "failed", "queued", "needs_ocr", "crashes", "opif_file", "document", "orders", "buyers") if k in c]
    s = f"{r['status']:7s} {local(r['started'])[:16]} -> {(local(r['ended']) or '')[11:16] or '...':5s} " + " ".join(f"{k}={c[k]}" for k in keys)
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
    a = ap.parse_args(argv)
    con = db.connect()
    o = overall(con)
    st = stages(con)
    pgc = pg_counts(con)
    info = station_info(con) if (a.stations or a.state or a.json) else None
    if a.json:
        runs = {k: {"running": v["running"], "failed_last": v["failed_last"], "last": v["last"]} for k, v in st.items()}
        print(json.dumps({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "overall": o, "postgres": pgc, "stages": runs,
                          "stations": per_station(con, a.state, info) if (a.stations or a.state) else None}, indent=1, default=str))
        return
    f, d, k, oc = o["files"], o["docs"], o["kinds"], o["ocr"]
    print(f"TV Wormhole pipeline status   {datetime.datetime.now():%Y-%m-%d %H:%M}   db={db.dbname()}")
    print(f"  stations with files {f['stations']}   files listed {f['listed']:,}  downloaded {f['downloaded']:,} ({f['gb_on_disk']} GB)  pending {f['pending']:,}  given up {f['given_up']:,}  deleted {f['deleted']:,}")
    print(f"  listings: " + "  ".join(f"{s}={n}" for s, n in o["listing"].items()) + f"   by year: " + "  ".join(f"{y}: {v['downloaded']:,}/{v['listed']:,}" for y, v in o["by_year"].items()))
    print(f"  parsed {d['parsed']:,}  ok {d['ok']:,} ({100*d['ok']/max(1,d['parsed']):.1f}%)  partial {d['partial']:,}  failed {d['failed']:,}  unrecognized {d['unrecognized']:,}  unparsed downloads {d['unparsed_downloads']:,}  parser crashes {d['parser_crashes']:,}")
    print(f"  OCR: needed {d['needs_ocr'] + d['from_ocr']:,}  done {oc['ok']:,} ({oc['pages']:,} pages, {oc['cpu_hours']} cpu-h, engines {oc['engines']})  pending {oc['pending']:,}  failed {oc['failed']:,} (given up {oc['given_up']:,})")
    print(f"  last history sync: {o['last_history_sync']}   entities: " + (f"orders {pgc['orders']:,}  invoices {pgc['invoices']:,}  spots {pgc['spots']:,}  buyers {pgc['buyers']:,}  built {pgc['entities_built_at']}" if "error" not in pgc else f"unreadable ({pgc['error']})"))
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
        problems.append(f"{d['parser_crashes']} documents crashed the parser (see document.error)")
    bad_listing = con.execute("SELECT facility_id, year, status, error FROM opif_listing WHERE status IN ('partial','failed') ORDER BY 1,2").fetchall()
    if bad_listing:
        problems.append(f"{len(bad_listing)} station-years with incomplete listings: " + ", ".join(f"{r[0]}/{r[1]}" for r in bad_listing[:8]))
    for s, v in st.items():
        if v["failed_last"]:
            problems.append(f"stage {s} {v['last']['status']} on its last run: {v['last']['error'] or ''} (log {v['last']['log_path']})")
    for r in con.execute("SELECT stage, pid, started FROM pipeline_run WHERE status='running' ORDER BY run_id"):
        if not lock_holder(r[0]) and not pid_alive(r[1]):
            problems.append(f"stage {r[0]} run from pid {r[1]} is marked running but its process is gone (died?); it will be marked killed on the stage's next run")
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
    con.close()


if __name__ == "__main__":
    main()

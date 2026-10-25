#!/usr/bin/env python3
"""One-off: copy the old SQLite crawl store (data/political.sqlite) into Postgres, which is now the only store.

  python3 -m ingest.migrate_sqlite                       # data/political.sqlite -> DATABASE_URL
  python3 -m ingest.migrate_sqlite --sqlite path.sqlite

Idempotent: every table is upserted by its key, so it can be rerun after the last SQLite-writing stage has
finished (the national crawl of 2026-10-24 kept writing SQLite until the switch). Copies
  files        -> opif_file     (crawl state: downloaded, local_size, sha256, attempts, errors)
  docs         -> document      (raw = {order_no, ..., ad_ids, fields}; template/source/ocr_engine as columns)
  listing      -> opif_listing
  ocr          -> ocr
  pipeline_run -> pipeline_run  (same run_id where the row is the same run; a new id if it collides with a run
                                 written here since; the sequence is moved past the maximum)
  meta         -> meta
SQLite timestamps are local wall-clock text; they are stored as timestamptz in the local zone. Files for
facility ids missing from `station` cannot be stored (foreign key) and are reported as failures. Ends with a
row-count comparison per table and exits non-zero if Postgres has fewer rows than SQLite (for known stations).
"""
import argparse, datetime, json, logging, os, sqlite3, sys
from . import db
from .runlog import Stage

log = logging.getLogger("ingest.migrate_sqlite")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SQLITE = os.path.join(ROOT, "data", "political.sqlite")


def ts(s):
    """SQLite ISO text (local, naive, or with an offset) -> aware datetime; None stays None."""
    if not s:
        return None
    d = datetime.datetime.fromisoformat(s)
    return d.astimezone() if d.tzinfo is None else d


def copy_files(con, sq, st, known):
    rows = sq.execute("SELECT * FROM files").fetchall()
    unknown = [r for r in rows if r["facility_id"] not in known]
    for fac in sorted({r["facility_id"] for r in unknown}):
        st.fail(fac, f"{sum(1 for r in unknown if r['facility_id'] == fac)} files: station not in the station table (make stations), not copied")
    rows = [r for r in rows if r["facility_id"] in known]
    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE t_files (LIKE opif_file INCLUDING DEFAULTS) ON COMMIT DROP")
        cols = "file_id,facility_id,year,folder_path,file_name,size_bytes,fcc_created_at,downloaded,downloaded_at,deleted_at,sha256,local_path,local_size,download_attempts,download_error"
        with cur.copy(f"COPY t_files({cols}) FROM STDIN") as cp:
            for r in rows:
                dl = bool(r["downloaded"])
                cp.write_row((r["file_manager_id"], r["facility_id"], r["year"], r["folder_path"], r["file_name"], r["file_size"], r["create_ts"],
                              dl, ts(r["downloaded_at"]) if dl else None, db.now() if r["deleted"] else None,
                              r["sha256"], r["local_path"], r["local_size"], r["download_attempts"] or 0, r["download_error"]))
        cur.execute(f"""INSERT INTO opif_file({cols}) SELECT {cols} FROM t_files
                        ON CONFLICT (file_id) DO UPDATE SET folder_path=EXCLUDED.folder_path, file_name=EXCLUDED.file_name, size_bytes=EXCLUDED.size_bytes,
                          fcc_created_at=COALESCE(EXCLUDED.fcc_created_at, opif_file.fcc_created_at), downloaded=EXCLUDED.downloaded,
                          downloaded_at=CASE WHEN EXCLUDED.downloaded THEN COALESCE(EXCLUDED.downloaded_at, opif_file.downloaded_at, now()) ELSE opif_file.downloaded_at END,
                          deleted_at=CASE WHEN EXCLUDED.deleted_at IS NULL THEN NULL ELSE COALESCE(opif_file.deleted_at, EXCLUDED.deleted_at) END,
                          sha256=COALESCE(EXCLUDED.sha256, opif_file.sha256), local_path=COALESCE(EXCLUDED.local_path, opif_file.local_path),
                          local_size=COALESCE(EXCLUDED.local_size, opif_file.local_size),
                          download_attempts=EXCLUDED.download_attempts, download_error=EXCLUDED.download_error""")
        # rows downloaded before downloaded_at existed were loaded with a timestamp of the mirroring; keep that, never NULL
        cur.execute("UPDATE opif_file SET downloaded_at=now() WHERE downloaded AND downloaded_at IS NULL")
    con.commit()
    st.count("files", len(rows)); st.count("files_unknown_station", len(unknown))
    log.info("files -> opif_file: %d copied, %d skipped (unknown station)", len(rows), len(unknown))


def copy_docs(con, sq, st, known):
    engine = {r[0]: r[1] for r in sq.execute("SELECT file_manager_id, engine FROM ocr WHERE status='ok'")}
    rows = [r for r in sq.execute("SELECT d.*, f.facility_id FROM docs d JOIN files f USING(file_manager_id)") if r["facility_id"] in known]
    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE t_docs (file_id text, kind text, template text, source text, parse_status text, parser_version integer, parsed_at timestamptz, raw jsonb, ocr_engine text, error text) ON COMMIT DROP")
        with cur.copy("COPY t_docs(file_id,kind,template,source,parse_status,parser_version,parsed_at,raw,ocr_engine,error) FROM STDIN") as cp:
            for r in rows:
                fields = json.loads(r["fields"] or "{}")
                raw = {k: r[k] for k in ("order_no", "revision", "invoice_no", "advertiser", "agency", "product", "flight_start", "flight_end",
                                         "print_date", "gross", "net", "spots")}
                raw["ad_ids"] = json.loads(r["ad_ids"] or "[]"); raw["fields"] = fields
                src = fields.get("source")
                cp.write_row((r["file_manager_id"], r["kind"], fields.get("template"), src, r["parse_status"], r["parser_version"],
                              ts(r["parsed_at"]) or db.now(), json.dumps(raw), engine.get(r["file_manager_id"]) if src == "ocr" else None, r["error"]))
        cur.execute("""INSERT INTO document(file_id,kind,template,source,parse_status,parser_version,parsed_at,raw,ocr_engine,error)
                       SELECT file_id,kind,template,source,parse_status,parser_version,parsed_at,raw,ocr_engine,error FROM t_docs
                       ON CONFLICT (file_id) DO UPDATE SET kind=EXCLUDED.kind, template=EXCLUDED.template, source=EXCLUDED.source,
                         parse_status=EXCLUDED.parse_status, parser_version=EXCLUDED.parser_version, parsed_at=EXCLUDED.parsed_at, raw=EXCLUDED.raw,
                         ocr_engine=EXCLUDED.ocr_engine, error=EXCLUDED.error
                       WHERE document.parsed_at IS NULL OR EXCLUDED.parsed_at >= document.parsed_at""")   # never overwrite a newer parse made here
    con.commit()
    st.count("docs", len(rows))
    log.info("docs -> document: %d", len(rows))


def copy_listing(con, sq, st, known):
    rows = [r for r in sq.execute("SELECT * FROM listing") if r["facility_id"] in known]
    with con.cursor() as cur:
        cur.executemany("""INSERT INTO opif_listing(facility_id,year,status,files,api_count,listed_at,error) VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (facility_id, year) DO UPDATE SET status=EXCLUDED.status, files=EXCLUDED.files, api_count=EXCLUDED.api_count,
                             listed_at=EXCLUDED.listed_at, error=EXCLUDED.error
                           WHERE opif_listing.listed_at IS NULL OR EXCLUDED.listed_at >= opif_listing.listed_at""",
                        [(r["facility_id"], r["year"], r["status"], r["files"], r["api_count"], ts(r["listed_at"]), r["error"]) for r in rows])
    con.commit()
    st.count("listing", len(rows))
    log.info("listing -> opif_listing: %d", len(rows))


def copy_ocr(con, sq, st):
    have = {r[0] for r in con.execute("SELECT file_id FROM opif_file")}
    rows = sq.execute("SELECT * FROM ocr").fetchall()
    rows_ok = [r for r in rows if r["file_manager_id"] in have]
    if len(rows_ok) < len(rows):
        st.warn("%d ocr rows refer to files not in opif_file and are skipped", len(rows) - len(rows_ok))
    with con.cursor() as cur:
        cur.executemany("""INSERT INTO ocr(file_id,engine,status,attempts,pages_done,pages_total,chars,seconds,error,ocr_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (file_id) DO UPDATE SET engine=EXCLUDED.engine, status=EXCLUDED.status, attempts=GREATEST(ocr.attempts, EXCLUDED.attempts),
                             pages_done=EXCLUDED.pages_done, pages_total=EXCLUDED.pages_total, chars=EXCLUDED.chars, seconds=EXCLUDED.seconds,
                             error=EXCLUDED.error, ocr_at=EXCLUDED.ocr_at
                           WHERE ocr.ocr_at IS NULL OR EXCLUDED.ocr_at >= ocr.ocr_at""",
                        [(r["file_manager_id"], r["engine"], r["status"], r["attempts"] or 1, r["pages_done"], r["pages_total"], r["chars"], r["seconds"], r["error"], ts(r["ocr_at"]))
                         for r in rows_ok])
    con.commit()
    st.count("ocr", len(rows_ok))
    log.info("ocr -> ocr: %d", len(rows_ok))


def copy_runs(con, sq, st):
    rows = sq.execute("SELECT * FROM pipeline_run ORDER BY run_id").fetchall()
    existing = {r[0]: (r[1], r[2]) for r in con.execute("SELECT run_id, stage, pid FROM pipeline_run")}
    # renumbered rows take ids above both stores' maxima, so they never collide with a SQLite id still to be copied
    top = max([0, *existing] + [r["run_id"] for r in rows])
    con.execute("SELECT setval('pipeline_run_run_id_seq', %s, false)", (top + 1,))
    same = moved = new = 0
    for r in rows:
        started = ts(r["started"])
        vals = dict(stage=r["stage"], batch=r["batch"], started=started, ended=ts(r["ended"]), status=r["status"], pid=r["pid"], host=r["host"],
                    args=r["args"], counts=r["counts"], failures=r["failures"] or 0, error=r["error"], log_path=r["log_path"])
        if existing.get(r["run_id"]) == (r["stage"], r["pid"]):
            con.execute("""UPDATE pipeline_run SET batch=%(batch)s, started=%(started)s, ended=%(ended)s, status=%(status)s, host=%(host)s, args=%(args)s::jsonb,
                           counts=%(counts)s::jsonb, failures=%(failures)s, error=%(error)s, log_path=%(log_path)s WHERE run_id=%(run_id)s""", {**vals, "run_id": r["run_id"]})
            same += 1
            continue
        prior = con.execute("SELECT run_id FROM pipeline_run WHERE stage=%s AND pid=%s AND started=%s AND run_id<>%s", (r["stage"], r["pid"], started, r["run_id"])).fetchone()
        if prior:                                           # copied on an earlier run under a new id
            con.execute("UPDATE pipeline_run SET ended=%(ended)s, status=%(status)s, counts=%(counts)s::jsonb, failures=%(failures)s, error=%(error)s WHERE run_id=%(run_id)s", {**vals, "run_id": prior[0]})
            moved += 1
            continue
        if r["run_id"] not in existing:
            vals["run_id"] = r["run_id"]
            con.execute("""INSERT INTO pipeline_run(run_id,stage,batch,started,ended,status,pid,host,args,counts,failures,error,log_path)
                           VALUES (%(run_id)s,%(stage)s,%(batch)s,%(started)s,%(ended)s,%(status)s,%(pid)s,%(host)s,%(args)s::jsonb,%(counts)s::jsonb,%(failures)s,%(error)s,%(log_path)s)""", vals)
            existing[r["run_id"]] = (r["stage"], r["pid"]); new += 1
        else:                                               # a different run already has this id here
            con.execute("""INSERT INTO pipeline_run(stage,batch,started,ended,status,pid,host,args,counts,failures,error,log_path)
                           VALUES (%(stage)s,%(batch)s,%(started)s,%(ended)s,%(status)s,%(pid)s,%(host)s,%(args)s::jsonb,%(counts)s::jsonb,%(failures)s,%(error)s,%(log_path)s)""", vals)
            moved += 1
    con.execute("SELECT setval('pipeline_run_run_id_seq', COALESCE((SELECT MAX(run_id) FROM pipeline_run), 0) + 1, false)")
    con.commit()
    st.count("runs", len(rows)); st.count("runs_renumbered", moved)
    log.info("pipeline_run: %d rows (%d updated in place, %d new, %d renumbered or matched by stage/pid/start)", len(rows), same, new, moved)


def copy_meta(con, sq, st):
    rows = sq.execute("SELECT key, value FROM meta").fetchall()
    for k, v in rows:
        con.execute("INSERT INTO meta(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (k, v))
    con.commit()
    st.count("meta", len(rows))
    log.info("meta: %s", dict(rows) or "empty")


def compare(con, sq, st, known):
    """Row counts SQLite vs Postgres; a shortfall on the Postgres side fails the stage."""
    facs = sorted(known)
    checks = [
        ("files", "SELECT COUNT(*) FROM files WHERE facility_id IN (%s)" % ",".join(map(str, facs)), "SELECT COUNT(*) FROM opif_file"),
        ("files downloaded", "SELECT COUNT(*) FROM files WHERE downloaded=1 AND facility_id IN (%s)" % ",".join(map(str, facs)), "SELECT COUNT(*) FROM opif_file WHERE downloaded"),
        ("docs", "SELECT COUNT(*) FROM docs d JOIN files f USING(file_manager_id) WHERE f.facility_id IN (%s)" % ",".join(map(str, facs)), "SELECT COUNT(*) FROM document"),
        ("docs needs_ocr", "SELECT COUNT(*) FROM docs d JOIN files f USING(file_manager_id) WHERE json_extract(d.fields,'$.needs_ocr')=1 AND f.facility_id IN (%s)" % ",".join(map(str, facs)), "SELECT COUNT(*) FROM document WHERE needs_ocr"),
        ("listing", "SELECT COUNT(*) FROM listing WHERE facility_id IN (%s)" % ",".join(map(str, facs)), "SELECT COUNT(*) FROM opif_listing"),
        ("ocr", "SELECT COUNT(*) FROM ocr", "SELECT COUNT(*) FROM ocr"),
        ("pipeline_run", "SELECT COUNT(*) FROM pipeline_run", "SELECT COUNT(*) FROM pipeline_run"),
        ("meta", "SELECT COUNT(*) FROM meta", "SELECT COUNT(*) FROM meta"),
    ]
    ok = True
    for name, qs, qp in checks:
        a, b = sq.execute(qs).fetchone()[0], con.execute(qp).fetchone()[0]
        flag = "" if b >= a else "   <-- Postgres has fewer"
        ok &= b >= a
        log.info("  %-16s sqlite %8d   postgres %8d%s", name, a, b, flag)
        st.count("cmp_" + name.replace(" ", "_"), b - a)
    if not ok:
        raise RuntimeError("row counts: Postgres has fewer rows than SQLite for at least one table (see above)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    a = ap.parse_args(argv)
    if not os.path.exists(a.sqlite):
        raise SystemExit(f"{a.sqlite} does not exist")
    with Stage("migrate_sqlite", args=vars(a), min_failures=0, max_fail_rate=0) as st:
        sq = sqlite3.connect(f"file:{a.sqlite}?mode=ro", uri=True, timeout=120); sq.row_factory = sqlite3.Row
        con = db.connect()
        known = {r[0] for r in con.execute("SELECT facility_id FROM station")}
        copy_files(con, sq, st, known)
        copy_docs(con, sq, st, known)
        copy_listing(con, sq, st, known)
        copy_ocr(con, sq, st)
        copy_runs(con, sq, st)
        copy_meta(con, sq, st)
        log.info("row counts (SQLite for stations in the station table vs Postgres):")
        compare(con, sq, st, known)
        con.close(); sq.close()


if __name__ == "__main__":
    main()

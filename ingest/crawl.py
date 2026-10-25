#!/usr/bin/env python3
"""Crawl FCC political files for stations into SQLite, optionally downloading PDFs.

  python3 -m ingest.crawl --stations 33710,66221 --years 2026 --download --workers 6
  python3 -m ingest.crawl --stations-file data/crawl_targets_2026.txt --state PA --years 2026 --download

Resumable and idempotent:
  * a station-year is re-listed unless its `listing` row is complete (a walk that died mid-way
    is recorded as partial and redone on the next run; --relist forces it);
  * downloads go to <file>.pdf.part and are renamed only after the PDF header/trailer check,
    so a killed run never leaves a half file that looks done; files on disk but not marked
    downloaded are verified and adopted;
  * every download failure is recorded on the file (download_attempts, download_error) and
    retried on later runs until MAX_ATTEMPTS, then reported by ingest.status as given up.
Logs to data/logs/crawl-<ts>.log; exits non-zero if failures exceed the threshold.
"""
import argparse, datetime, logging, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from . import fcc, db
from .runlog import Stage

log = logging.getLogger("ingest.crawl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(ROOT, "data", "pdfs")
MAX_ATTEMPTS = 5
CONSECUTIVE_FAIL_PAUSE = 25      # this many download failures in a row: pause (the FCC edge is throttling us)
CONSECUTIVE_FAIL_ABORT = 150     # this many in a row: stop the stage, it is not going to recover by itself


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def list_station(con, st, fac, year, relist):
    row = con.execute("SELECT status, files FROM listing WHERE facility_id=? AND year=?", (fac, year)).fetchone()
    if row and row["status"] in ("complete", "empty") and not relist:
        log.info("  %s/%s: listing %s (%s files), skipping", fac, year, row["status"], row["files"])
        st.count("stations_skipped")
        return row["files"] or 0
    n, new, api_count = 0, 0, None
    st.attempt()
    try:
        for path, f in fcc.walk(str(fac), f"Political Files/{year}"):
            if path == "__count__":
                try:
                    api_count = int(f) if f is not None else None
                except (TypeError, ValueError):
                    api_count = None
                continue
            cur = con.execute("""INSERT INTO files(file_manager_id,facility_id,year,folder_path,file_name,file_size,create_ts)
                           VALUES(?,?,?,?,?,?,?) ON CONFLICT(file_manager_id) DO UPDATE SET
                           folder_path=excluded.folder_path, file_name=excluded.file_name, file_size=excluded.file_size, deleted=0""",
                              (f["file_manager_id"], fac, year, path, f.get("file_name"), f.get("file_size"), f.get("create_ts")))
            n += 1
            if n % 200 == 0:
                con.commit()
    except fcc.FccError as e:
        con.execute("INSERT OR REPLACE INTO listing(facility_id,year,status,files,api_count,listed_at,error) VALUES(?,?,?,?,?,?,?)",
                    (fac, year, "partial" if n else "failed", n, api_count, now(), str(e)[:300]))
        con.commit()
        st.fail(f"{fac}/{year}", f"listing {'partial' if n else 'failed'} after {n} files: {e}")
        st.count("stations_partial" if n else "stations_failed")
        return n
    status = "complete" if n else "empty"
    con.execute("INSERT OR REPLACE INTO listing(facility_id,year,status,files,api_count,listed_at,error) VALUES(?,?,?,?,?,?,NULL)",
                (fac, year, status, n, api_count, now()))
    con.commit()
    if api_count is not None and api_count != n:
        st.warn("  %s/%s: walked %d files but the API reports file_count=%s", fac, year, n, api_count)
    log.info("  %s/%s: listed %d files%s", fac, year, n, f" (API count {api_count})" if api_count is not None else "")
    st.count("stations_listed"); st.count("files_listed", n)
    return n


def adopt_existing(con, st, rows):
    """Files on disk whose DB row says not downloaded (crash between curl and the UPDATE): verify and mark."""
    adopted, left = 0, []
    for r in rows:
        dest = os.path.join(PDF_DIR, str(r["facility_id"]), str(r["year"]), r["file_manager_id"] + ".pdf")
        if os.path.exists(dest):
            ok, why = fcc.check_pdf(dest)
            if ok:
                mark_downloaded(con, r["file_manager_id"], dest)
                adopted += 1
                continue
            log.info("  removing bad file on disk %s: %s", os.path.relpath(dest, ROOT), why)
            os.remove(dest)
        left.append(r)
    if adopted:
        con.commit()
        log.info("  adopted %d files already on disk", adopted)
        st.count("downloads_adopted", adopted)
    return left


def mark_downloaded(con, fid, dest):
    con.execute("UPDATE files SET downloaded=1, local_path=?, local_size=?, sha256=?, downloaded_at=?, download_error=NULL WHERE file_manager_id=?",
                (os.path.relpath(dest, ROOT), os.path.getsize(dest), fcc.sha256_of(dest), now(), fid))


def download_pending(con, st, facs, years, workers, max_attempts=MAX_ATTEMPTS):
    q = f"""SELECT file_manager_id, facility_id, year, download_attempts FROM files
            WHERE downloaded=0 AND deleted=0 AND download_attempts < ?
              AND facility_id IN ({",".join("?"*len(facs))}) AND year IN ({",".join("?"*len(years))})"""
    rows = con.execute(q, (max_attempts, *facs, *years)).fetchall()
    given_up = con.execute(f"""SELECT COUNT(*) FROM files WHERE downloaded=0 AND deleted=0 AND download_attempts >= ?
                               AND facility_id IN ({",".join("?"*len(facs))})""", (max_attempts, *facs)).fetchone()[0]
    if given_up:
        st.warn("  %d files have reached %d failed attempts and are not retried (see ingest.status; --retry-given-up resets them)", given_up, max_attempts)
    rows = adopt_existing(con, st, rows)
    log.info("  downloading %d files with %d workers", len(rows), workers)
    st.count("downloads_pending", len(rows))

    def one(r):
        fid, fac, year = r["file_manager_id"], r["facility_id"], r["year"]
        d = os.path.join(PDF_DIR, str(fac), str(year))
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, fid + ".pdf")
        ok, reason, size = fcc.download(fid, dest)
        time.sleep(0.05)
        return fid, dest, ok, reason, size

    done = ok_n = fail_n = consecutive = 0
    total_bytes = 0
    with ThreadPoolExecutor(workers) as ex:
        for fid, dest, ok, reason, size in ex.map(one, rows):
            done += 1; st.attempt()
            if ok:
                mark_downloaded(con, fid, dest)
                ok_n += 1; total_bytes += size; consecutive = 0
            else:
                con.execute("UPDATE files SET download_attempts=download_attempts+1, download_error=? WHERE file_manager_id=?", (reason, fid))
                st.fail(fid, f"download: {reason}")
                fail_n += 1; consecutive += 1
                if consecutive == CONSECUTIVE_FAIL_PAUSE:
                    con.commit()
                    st.warn("  %d consecutive download failures; pausing 120s", consecutive)
                    time.sleep(120)
                if consecutive >= CONSECUTIVE_FAIL_ABORT:
                    con.commit()
                    raise RuntimeError(f"{consecutive} consecutive download failures; aborting (last: {reason})")
            if done % 50 == 0:
                con.commit()
            st.progress(done, len(rows), every=200, label="download")
    con.commit()
    st.count("downloads_ok", ok_n); st.count("downloads_failed", fail_n); st.count("download_mb", round(total_bytes / 1e6, 1))
    log.info("  downloads: %d ok, %d failed, %.1f MB", ok_n, fail_n, total_bytes / 1e6)


def verify_downloads(con, st, facs):
    """Re-check every downloaded file on disk (header, trailer, size); unmark the bad ones so they are re-fetched."""
    rows = con.execute(f"SELECT file_manager_id, local_path, local_size FROM files WHERE downloaded=1 AND facility_id IN ({','.join('?'*len(facs))})", facs).fetchall()
    bad = 0
    for i, r in enumerate(rows, 1):
        p = os.path.join(ROOT, r["local_path"] or "")
        ok, why = fcc.check_pdf(p) if r["local_path"] else (False, "no local_path")
        if ok and r["local_size"] and os.path.getsize(p) != r["local_size"]:
            ok, why = False, f"size changed ({os.path.getsize(p)} vs {r['local_size']})"
        if not ok:
            bad += 1
            st.fail(r["file_manager_id"], f"verify: {why}")
            con.execute("UPDATE files SET downloaded=0, download_error=? WHERE file_manager_id=?", (f"verify: {why}", r["file_manager_id"]))
            if os.path.exists(p):
                os.remove(p)
        st.progress(i, len(rows), every=5000, label="verify")
    con.commit()
    st.count("verified", len(rows)); st.count("verify_bad", bad)
    log.info("  verified %d files, %d bad (unmarked for re-download)", len(rows), bad)


def read_targets(path, state=None):
    facs = []
    for line in open(path):
        parts = line.split()
        if not parts or (state and parts[0] != state):
            continue
        facs += [int(x) for x in parts[1].split(",") if x]
    return facs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", help="comma-separated facility IDs")
    ap.add_argument("--stations-file", help="file of '<STATE> <fac,fac,...>' lines (data/crawl_targets_2026.txt)")
    ap.add_argument("--state", help="with --stations-file: only this state")
    ap.add_argument("--years", default="2026")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--relist", action="store_true")
    ap.add_argument("--verify", action="store_true", help="re-check files already on disk before downloading")
    ap.add_argument("--retry-given-up", action="store_true", help="reset download_attempts for files that hit the cap")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-fail-rate", type=float, default=0.02)
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args(argv)
    if a.stations:
        facs = [int(x) for x in a.stations.split(",") if x]
    elif a.stations_file:
        facs = read_targets(a.stations_file, a.state)
    else:
        ap.error("--stations or --stations-file required")
    years = [int(y) for y in a.years.split(",")]
    with Stage("crawl", args=vars(a), db_path=a.db, max_fail_rate=a.max_fail_rate) as st:
        con = db.connect(a.db)
        log.info("stations: %d  years: %s", len(facs), years)
        if a.retry_given_up:
            n = con.execute(f"UPDATE files SET download_attempts=0 WHERE downloaded=0 AND deleted=0 AND download_attempts>=? AND facility_id IN ({','.join('?'*len(facs))})", (MAX_ATTEMPTS, *facs)).rowcount
            con.commit(); log.info("reset %d given-up downloads", n)
        for fac in facs:
            for y in years:
                list_station(con, st, fac, y, a.relist)
        if a.verify:
            verify_downloads(con, st, facs)
        if a.download:
            download_pending(con, st, facs, years, a.workers)
        pend = con.execute(f"SELECT COUNT(*) FROM files WHERE downloaded=0 AND deleted=0 AND facility_id IN ({','.join('?'*len(facs))})", facs).fetchone()[0]
        st.count("still_pending", pend)
        con.close()


if __name__ == "__main__":
    main()

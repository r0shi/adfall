#!/usr/bin/env python3
"""Crawl FCC political files for stations into Postgres (opif_file / opif_listing), optionally downloading PDFs.

  python3 -m ingest.crawl --stations 33710,66221 --years 2026 --download --workers 6
  python3 -m ingest.crawl --stations-file data/crawl_targets_2026.txt --state PA --years 2026 --download

Resumable and idempotent:
  * a station-year is re-listed unless its `opif_listing` row is complete (a walk that died mid-way
    is recorded as partial and redone on the next run; --relist forces it);
  * downloads go to <file>.pdf.part and are renamed only after the PDF header/trailer check,
    so a killed run never leaves a half file that looks done; files on disk but not marked
    downloaded are verified and adopted;
  * every download failure is recorded on the file (download_attempts, download_error) and
    retried on later runs until MAX_ATTEMPTS, then reported by ingest.status as given up; a 401, 404
    or 410 is permanent (the station removed or restricted the file) and is given up at once, counted
    as downloads_gone, and does not fail the stage.
Stations that are not in the `station` table (web/data/stations.json, `make stations`) are reported
and skipped, never silently dropped. Logs to data/logs/crawl-<ts>.log; exits non-zero if failures
exceed the threshold.
"""
import argparse, logging, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from . import fcc, db
from .runlog import Stage

log = logging.getLogger("ingest.crawl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(ROOT, "data", "pdfs")
MAX_ATTEMPTS = 5
CONSECUTIVE_FAIL_PAUSE = 25      # this many download failures in a row: pause (the FCC edge is throttling us)
CONSECUTIVE_FAIL_ABORT = 150     # this many in a row: stop the stage, it is not going to recover by itself
PERMANENT = re.compile(r"^HTTP (401|404|410)\b")   # the FCC will not serve this file (removed, restricted, gone): no retries, not a stage failure


def known_stations(con, st, facs):
    """facility ids present in `station`; the others are failures of this run (they need `make stations`)."""
    known = {r[0] for r in con.execute("SELECT facility_id FROM station WHERE facility_id = ANY(%s)", (facs,))}
    con.commit()                         # read-only so far; do not hold a transaction over the network walks that follow
    for fac in facs:
        if fac not in known:
            st.fail(fac, "not in the station table (web/data/stations.json + `make stations`); skipped")
            st.count("stations_unknown")
    return [f for f in facs if f in known]


def list_station(con, st, fac, year, relist):
    row = con.execute("SELECT status, files FROM opif_listing WHERE facility_id=%s AND year=%s", (fac, year)).fetchone()
    if row and row["status"] in ("complete", "empty") and not relist:
        log.info("  %s/%s: listing %s (%s files), skipping", fac, year, row["status"], row["files"])
        st.count("stations_skipped")
        return row["files"] or 0
    n, api_count = 0, None
    st.attempt()
    try:
        for path, f in fcc.walk(str(fac), f"Political Files/{year}"):
            if path == "__count__":
                try:
                    api_count = int(f) if f is not None else None
                except (TypeError, ValueError):
                    api_count = None
                continue
            con.execute("""INSERT INTO opif_file(file_id,facility_id,year,folder_path,file_name,size_bytes,fcc_created_at)
                           VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (file_id) DO UPDATE SET
                           folder_path=EXCLUDED.folder_path, file_name=EXCLUDED.file_name, size_bytes=EXCLUDED.size_bytes, deleted_at=NULL""",
                        (f["file_manager_id"], fac, year, path, f.get("file_name"), f.get("file_size"), f.get("create_ts")))
            n += 1
            if n % 200 == 0:
                con.commit()
    except fcc.FccError as e:
        con.execute("""INSERT INTO opif_listing(facility_id,year,status,files,api_count,listed_at,error) VALUES(%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (facility_id, year) DO UPDATE SET status=EXCLUDED.status, files=EXCLUDED.files, api_count=EXCLUDED.api_count,
                       listed_at=EXCLUDED.listed_at, error=EXCLUDED.error""",
                    (fac, year, "partial" if n else "failed", n, api_count, db.now(), str(e)[:300]))
        con.commit()
        st.fail(f"{fac}/{year}", f"listing {'partial' if n else 'failed'} after {n} files: {e}")
        st.count("stations_partial" if n else "stations_failed")
        return n
    status = "complete" if n else "empty"
    con.execute("""INSERT INTO opif_listing(facility_id,year,status,files,api_count,listed_at,error) VALUES(%s,%s,%s,%s,%s,%s,NULL)
                   ON CONFLICT (facility_id, year) DO UPDATE SET status=EXCLUDED.status, files=EXCLUDED.files, api_count=EXCLUDED.api_count,
                   listed_at=EXCLUDED.listed_at, error=NULL""",
                (fac, year, status, n, api_count, db.now()))
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
        dest = os.path.join(PDF_DIR, str(r["facility_id"]), str(r["year"]), r["file_id"] + ".pdf")
        if os.path.exists(dest):
            ok, why = fcc.check_pdf(dest)
            if ok:
                mark_downloaded(con, r["file_id"], dest)
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
    con.execute("""UPDATE opif_file SET downloaded=true, local_path=%s, local_size=%s, sha256=%s, downloaded_at=%s, download_error=NULL
                   WHERE file_id=%s""", (os.path.relpath(dest, ROOT), os.path.getsize(dest), fcc.sha256_of(dest), db.now(), fid))


def download_pending(con, st, facs, years, workers, max_attempts=MAX_ATTEMPTS):
    rows = con.execute("""SELECT file_id, facility_id, year, download_attempts FROM opif_file
                          WHERE NOT downloaded AND deleted_at IS NULL AND download_attempts < %s
                            AND facility_id = ANY(%s) AND year = ANY(%s) ORDER BY facility_id, year, file_id""",
                       (max_attempts, list(facs), list(years))).fetchall()
    given_up = con.execute("""SELECT COUNT(*) FROM opif_file WHERE NOT downloaded AND deleted_at IS NULL AND download_attempts >= %s
                              AND facility_id = ANY(%s)""", (max_attempts, list(facs))).fetchone()[0]
    if given_up:
        st.warn("  %d files have reached %d failed attempts and are not retried (see ingest.status; --retry-given-up resets them)", given_up, max_attempts)
    rows = adopt_existing(con, st, rows)
    log.info("  downloading %d files with %d workers", len(rows), workers)
    st.count("downloads_pending", len(rows))

    def one(r):
        fid, fac, year = r["file_id"], r["facility_id"], r["year"]
        d = os.path.join(PDF_DIR, str(fac), str(year))
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, fid + ".pdf")
        ok, reason, size = fcc.download(fid, dest)
        time.sleep(0.05)
        return fid, dest, ok, reason, size

    done = ok_n = fail_n = gone_n = consecutive = 0
    total_bytes = 0
    with ThreadPoolExecutor(workers) as ex:
        for fid, dest, ok, reason, size in ex.map(one, rows):
            done += 1; st.attempt()
            if ok:
                mark_downloaded(con, fid, dest)
                ok_n += 1; total_bytes += size; consecutive = 0
            elif PERMANENT.match(reason or ""):
                con.execute("UPDATE opif_file SET download_attempts=%s, download_error=%s WHERE file_id=%s", (max_attempts, f"{reason} (permanent)", fid))
                log.info("  %s: %s; the FCC does not serve this file, not retried (ingest.status lists it as given up)", fid, reason)
                gone_n += 1; consecutive = 0
            else:
                con.execute("UPDATE opif_file SET download_attempts=download_attempts+1, download_error=%s WHERE file_id=%s", (reason, fid))
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
    st.count("downloads_ok", ok_n); st.count("downloads_failed", fail_n); st.count("downloads_gone", gone_n); st.count("download_mb", round(total_bytes / 1e6, 1))
    log.info("  downloads: %d ok, %d failed, %d gone (401/404/410, given up at once), %.1f MB", ok_n, fail_n, gone_n, total_bytes / 1e6)


def verify_downloads(con, st, facs):
    """Re-check every downloaded file on disk (header, trailer, size); unmark the bad ones so they are re-fetched."""
    rows = con.execute("SELECT file_id, local_path, local_size FROM opif_file WHERE downloaded AND facility_id = ANY(%s)", (list(facs),)).fetchall()
    bad = 0
    for i, r in enumerate(rows, 1):
        p = os.path.join(ROOT, r["local_path"] or "")
        ok, why = fcc.check_pdf(p) if r["local_path"] else (False, "no local_path")
        if ok and r["local_size"] and os.path.getsize(p) != r["local_size"]:
            ok, why = False, f"size changed ({os.path.getsize(p)} vs {r['local_size']})"
        if not ok:
            bad += 1
            st.fail(r["file_id"], f"verify: {why}")
            con.execute("UPDATE opif_file SET downloaded=false, download_error=%s WHERE file_id=%s", (f"verify: {why}", r["file_id"]))
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
    a = ap.parse_args(argv)
    if a.stations:
        facs = [int(x) for x in a.stations.split(",") if x]
    elif a.stations_file:
        facs = read_targets(a.stations_file, a.state)
    else:
        ap.error("--stations or --stations-file required")
    years = [int(y) for y in a.years.split(",")]
    with Stage("crawl", args=vars(a), max_fail_rate=a.max_fail_rate) as st:
        con = db.connect()
        facs = known_stations(con, st, facs)
        log.info("stations: %d  years: %s", len(facs), years)
        if a.retry_given_up:
            n = con.execute("UPDATE opif_file SET download_attempts=0 WHERE NOT downloaded AND deleted_at IS NULL AND download_attempts>=%s AND facility_id = ANY(%s)",
                            (MAX_ATTEMPTS, facs)).rowcount
            con.commit(); log.info("reset %d given-up downloads", n)
        for fac in facs:
            for y in years:
                list_station(con, st, fac, y, a.relist)
        if a.verify:
            verify_downloads(con, st, facs)
        if a.download:
            download_pending(con, st, facs, years, a.workers)
        pend = con.execute("SELECT COUNT(*) FROM opif_file WHERE NOT downloaded AND deleted_at IS NULL AND facility_id = ANY(%s)", (facs,)).fetchone()[0]
        st.count("still_pending", pend)
        con.close()


if __name__ == "__main__":
    main()

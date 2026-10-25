#!/usr/bin/env python3
"""Incremental updater: apply the FCC file-history change feed to the local store.

The feed (`/api/manager/file/history.json`) lists every file added, deleted,
moved, renamed or purged across all stations for a date range, with the folder
path, size and timestamps. One call per 500 rows; a peak day is ~30 pages.

  python3 -m ingest.update                       # from last sync (or yesterday) to today
  python3 -m ingest.update --since 2026-10-20    # explicit window
  python3 -m ingest.update --download            # and fetch the new files

Only tracked stations (those already in `files`) are applied unless --stations
adds more. Re-running a window is idempotent. A day whose feed could not be read
is recorded as a failure and the sync marker is not advanced past it, so the next
run picks it up again.
"""
import argparse, datetime, logging, os, re, sys, time
from . import fcc, db
from .runlog import Stage

log = logging.getLogger("ingest.update")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def days(since, until):
    d = since
    while d <= until:
        yield d
        d += datetime.timedelta(days=1)


def fetch_day(day):
    rows, off = [], 0
    while True:
        try:
            page = fcc.file_history(day.isoformat(), day.isoformat(), count=500, offset=off)
        except fcc.FccError as e:
            log.warning("  %s: page at offset %d failed (%s); retrying in 100-row pages", day, off, e)
            time.sleep(5)
            page = []
            for sub in range(0, 500, 100):
                page += fcc.file_history(day.isoformat(), day.isoformat(), count=100, offset=off + sub)
        rows += page
        if len(page) < 500:
            return rows
        off += 500
        time.sleep(0.2)


def apply(con, rows, tracked):
    counts = {}
    for r in rows:
        path = r.get("file_folder_path") or ""
        if r.get("source_service_code") != "TV" or not path.startswith("Political Files/"):
            continue
        try:
            fac = int(r["entity_id"])
        except (TypeError, ValueError):
            continue
        if fac not in tracked:
            continue
        m = re.match(r"Political Files/(\d{4})", path)
        year = int(m.group(1)) if m else None
        st = r.get("history_status"); fid = r.get("file_manager_id")
        counts[st] = counts.get(st, 0) + 1
        if st == "new":
            if year is None:
                counts["new_without_year"] = counts.get("new_without_year", 0) + 1
                continue
            con.execute("""INSERT INTO files(file_manager_id,facility_id,year,folder_path,file_name,file_size,create_ts,deleted)
                           VALUES(?,?,?,?,?,?,?,0) ON CONFLICT(file_manager_id) DO UPDATE SET
                           folder_path=excluded.folder_path, file_name=excluded.file_name, file_size=excluded.file_size, deleted=0""",
                        (fid, fac, year, path, r.get("file_name"), r.get("file_size"), r.get("create_ts")))
        elif st in ("delete", "purge"):
            con.execute("UPDATE files SET deleted=1 WHERE file_manager_id=?", (fid,))
        elif st in ("move", "rename"):
            con.execute("UPDATE files SET folder_path=?, file_name=?, year=COALESCE(?, year) WHERE file_manager_id=?",
                        (path, r.get("file_name"), year, fid))
    con.commit()
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD; default: last sync date, else yesterday")
    ap.add_argument("--until", help="YYYY-MM-DD; default today")
    ap.add_argument("--stations", help="extra facility IDs to track, comma-separated")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args(argv)
    with Stage("update", args=vars(a), db_path=a.db) as st:
        con = db.connect(a.db)
        today = datetime.date.today()
        last = con.execute("SELECT value FROM meta WHERE key='last_history_sync'").fetchone()
        since = datetime.date.fromisoformat(a.since) if a.since else (datetime.date.fromisoformat(last[0]) if last else today - datetime.timedelta(days=1))
        until = datetime.date.fromisoformat(a.until) if a.until else today
        tracked = {r[0] for r in con.execute("SELECT DISTINCT facility_id FROM files")}
        if a.stations:
            tracked |= {int(x) for x in a.stations.split(",")}
        log.info("syncing %s..%s for %d stations", since, until, len(tracked))
        synced_through = None
        for day in days(since, until):
            st.attempt()
            try:
                rows = fetch_day(day)
            except fcc.FccError as e:
                st.fail(str(day), f"feed unreadable: {e}")
                break                                   # do not advance past a day we could not read
            c = apply(con, rows, tracked)
            log.info("  %s: %d feed rows -> %s", day, len(rows), c or "no changes for tracked stations")
            st.count("feed_rows", len(rows))
            for k, v in c.items():
                st.count("applied_" + k, v)
            synced_through = day
        if synced_through:
            con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_history_sync',?)", (synced_through.isoformat(),))
            con.commit()
            log.info("last_history_sync = %s", synced_through)
        if a.download:
            from .crawl import download_pending
            years = [r[0] for r in con.execute("SELECT DISTINCT year FROM files WHERE downloaded=0 AND deleted=0")]
            if years:
                download_pending(con, st, sorted(tracked), years, a.workers)
        con.close()


if __name__ == "__main__":
    main()

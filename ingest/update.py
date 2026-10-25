#!/usr/bin/env python3
"""Incremental updater: apply the FCC file-history change feed to the local store.

The feed (`/api/manager/file/history.json`) lists every file added, deleted,
moved, renamed or purged across all stations for a date range, with the folder
path, size and timestamps. One call per 500 rows; a peak day is ~30 pages.

  python3 -m ingest.update                       # from last sync (or yesterday) to today
  python3 -m ingest.update --since 2026-10-20    # explicit window
  python3 -m ingest.update --download            # and fetch the new files

Only tracked stations (those already in `opif_file`) are applied unless --stations
adds more. Re-running a window is idempotent. A day whose feed could not be read
is recorded as a failure and the sync marker (meta.last_history_sync) is not
advanced past it, so the next run picks it up again.
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
        if off % 2500 == 0:
            log.info("  %s: %d feed rows so far (page %d)", day, len(rows), off // 500)
        time.sleep(0.2)


def apply(con, rows, tracked, known):
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
            if fac not in known:
                counts["new_unknown_station"] = counts.get("new_unknown_station", 0) + 1
                continue
            con.execute("""INSERT INTO opif_file(file_id,facility_id,year,folder_path,file_name,size_bytes,fcc_created_at)
                           VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (file_id) DO UPDATE SET
                           folder_path=EXCLUDED.folder_path, file_name=EXCLUDED.file_name, size_bytes=EXCLUDED.size_bytes, deleted_at=NULL""",
                        (fid, fac, year, path, r.get("file_name"), r.get("file_size"), r.get("create_ts")))
        elif st in ("delete", "purge"):
            con.execute("UPDATE opif_file SET deleted_at=COALESCE(deleted_at, %s) WHERE file_id=%s", (db.now(), fid))
        elif st in ("move", "rename"):
            con.execute("UPDATE opif_file SET folder_path=%s, file_name=%s, year=COALESCE(%s, year) WHERE file_id=%s",
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
    a = ap.parse_args(argv)
    with Stage("update", args=vars(a), min_failures=0) as st:
        con = db.connect()
        today = datetime.date.today()
        last = con.execute("SELECT value FROM meta WHERE key='last_history_sync'").fetchone()
        since = datetime.date.fromisoformat(a.since) if a.since else (datetime.date.fromisoformat(last[0]) if last else today - datetime.timedelta(days=1))
        until = datetime.date.fromisoformat(a.until) if a.until else today
        tracked = {r[0] for r in con.execute("SELECT DISTINCT facility_id FROM opif_file")}
        if a.stations:
            tracked |= {int(x) for x in a.stations.split(",")}
        known = {r[0] for r in con.execute("SELECT facility_id FROM station")}
        unknown = sorted(tracked - known)
        if unknown:
            st.warn("%d tracked stations are not in the station table and their new files cannot be stored: %s (make stations)", len(unknown), unknown[:20])
        log.info("syncing %s..%s for %d stations", since, until, len(tracked))
        synced_through = None
        for day in days(since, until):
            st.attempt()
            try:
                rows = fetch_day(day)
            except fcc.FccError as e:
                st.fail(str(day), f"feed unreadable: {e}")
                break                                   # do not advance past a day we could not read
            c = apply(con, rows, tracked, known)
            log.info("  %s: %d feed rows -> %s", day, len(rows), c or "no changes for tracked stations")
            st.count("feed_rows", len(rows))
            for k, v in c.items():
                st.count("applied_" + k, v)
            synced_through = day
        if synced_through:
            con.execute("INSERT INTO meta(key,value) VALUES('last_history_sync',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (synced_through.isoformat(),))
            con.commit()
            log.info("last_history_sync = %s", synced_through)
        if a.download:
            from .crawl import download_pending
            years = [r[0] for r in con.execute("SELECT DISTINCT year FROM opif_file WHERE NOT downloaded AND deleted_at IS NULL")]
            if years:
                download_pending(con, st, sorted(tracked & known), years, a.workers)
        con.close()


if __name__ == "__main__":
    main()

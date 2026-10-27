#!/usr/bin/env python3
"""Daily update: find what changed in each tracked station's political-file folder and fetch it.

Two methods. The default compares the FCC's own file count for each station-year folder
(`folder/id/<folder>.json` -> `file_count`, one call of ~0.3 s per station) with the files we hold and
re-walks only the station-years whose count differs: new files are added, files that vanished are marked
deleted, and new files are downloaded. The FCC change feed (`--mode feed`, `file/history.json`) was the
original design but is sorted newest-first and times out server-side past offset ~3,000 on any busy day
(seen 2026-10-24, -25, -26), so a day can never be read completely.

  python3 -m ingest.update --download                  # count check for every tracked station, re-list changed ones, download
  python3 -m ingest.update --download --only 23422,3667
  python3 -m ingest.update --mode feed --since 2026-10-20   # the change feed, for small windows
  python3 -m ingest.update --download --all            # re-walk every station regardless of the count (weekly safety net)

Only tracked stations (those already in opif_file) are updated unless --stations adds more. Re-running is idempotent.
"""
import argparse, datetime, logging, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
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


def check_counts(con, st, facs, years, workers=4):
    """For each (facility, year): fetch the FCC file_count of the year folder; return the station-years whose count
    differs from the non-deleted files we hold. Folder ids are cached in opif_listing.folder_id."""
    have = {(r[0], r[1]): r[2] for r in con.execute("""SELECT facility_id, year, COUNT(*) FILTER (WHERE deleted_at IS NULL) FROM opif_file
                                                       WHERE facility_id = ANY(%s) AND year = ANY(%s) GROUP BY 1,2""", (facs, years))}
    folder_ids = {(r[0], r[1]): r[2] for r in con.execute("SELECT facility_id, year, folder_id FROM opif_listing WHERE facility_id = ANY(%s)", (facs,))}
    con.commit()
    targets = [(fac, y) for fac in facs for y in years]

    def one(key):
        fac, year = key
        try:
            fid = folder_ids.get(key)
            if not fid:
                top = fcc.folder_by_path(str(fac), f"Political Files/{year}")
                if not top:
                    return key, None, None, None          # no folder for that year (yet)
                fid = top["entity_folder_id"]
            d = fcc.folder_by_id(str(fac), fid)
            n = d.get("file_count")
            return key, fid, (int(n) if n is not None else None), None
        except fcc.FccError as e:
            return key, folder_ids.get(key), None, str(e)[:200]

    changed, done = [], 0
    with ThreadPoolExecutor(workers) as ex:
        for key, fid, api_count, err in ex.map(one, targets):
            done += 1; st.attempt()
            fac, year = key
            if err:
                st.fail(f"{fac}/{year}", f"count check: {err}")
                continue
            if api_count is None:
                st.count("stations_no_folder")
                continue
            ours = have.get(key, 0)
            con.execute("""INSERT INTO opif_listing(facility_id,year,status,files,api_count,folder_id,checked_at)
                           VALUES (%s,%s,'empty',0,%s,%s,now()) ON CONFLICT (facility_id, year) DO UPDATE SET
                           api_count=EXCLUDED.api_count, folder_id=EXCLUDED.folder_id, checked_at=now()""", (fac, year, api_count, fid))
            if api_count != ours:
                changed.append((fac, year, ours, api_count))
            st.progress(done, len(targets), every=200, label="count check")
    con.commit()
    st.count("stations_checked", done); st.count("stations_changed", len(changed))
    log.info("count check: %d station-years, %d changed (%+d files net)", done, len(changed), sum(a - o for _, _, o, a in changed))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD; default: last sync date, else yesterday")
    ap.add_argument("--until", help="YYYY-MM-DD; default today")
    ap.add_argument("--stations", help="extra facility IDs to track, comma-separated")
    ap.add_argument("--mode", choices=["counts", "feed"], default="counts")
    ap.add_argument("--only", help="counts mode: restrict to these facility ids (testing)")
    ap.add_argument("--all", action="store_true", help="counts mode: re-walk every station-year, not only the changed ones")
    ap.add_argument("--years", default="2026")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.mode == "counts":
        return main_counts(a)
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
        con.commit()                     # no transaction stays open while the feed is fetched (minutes; it would block DDL and mart refreshes)
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


def main_counts(a):
    from .crawl import list_station, download_pending
    with Stage("update", args=vars(a), max_fail_rate=0.02, min_failures=5) as st:
        con = db.connect()
        known = {r[0] for r in con.execute("SELECT facility_id FROM station")}
        tracked = {r[0] for r in con.execute("SELECT DISTINCT facility_id FROM opif_file")}
        if a.stations:
            tracked |= {int(x) for x in a.stations.split(",")}
        if a.only:
            tracked = {int(x) for x in a.only.split(",")}
        unknown = sorted(tracked - known)
        if unknown:
            st.warn("%d tracked stations are not in the station table and are skipped: %s (make stations)", len(unknown), unknown[:20])
        facs = sorted(tracked & known)
        years = [int(y) for y in a.years.split(",")]
        con.commit()
        log.info("checking %d stations for years %s", len(facs), years)
        if a.all:
            changed = [(fac, y, None, None) for fac in facs for y in years]
        else:
            changed = check_counts(con, st, facs, years, workers=a.workers)
        import threading
        local = threading.local()

        def relist(item):                                # each thread walks with its own connection (psycopg connections are not shared across threads)
            fac, year, ours, theirs = item
            if not hasattr(local, "con"):
                local.con = db.connect()
            c = local.con
            before = c.execute("SELECT COUNT(*) FROM opif_file WHERE facility_id=%s AND year=%s", (fac, year)).fetchone()[0]
            list_station(c, st, fac, year, relist=True, mark_missing=True)
            after = c.execute("SELECT COUNT(*) FROM opif_file WHERE facility_id=%s AND year=%s", (fac, year)).fetchone()[0]
            c.commit()
            return fac, year, ours, theirs, after - before

        with ThreadPoolExecutor(a.workers) as ex:
            for i, (fac, year, ours, theirs, new) in enumerate(ex.map(relist, changed), 1):
                st.count("files_new", new)
                log.info("  [%d/%d] %s/%s: held %s, FCC reports %s, %+d files", i, len(changed), fac, year, ours, theirs, new)
        con.execute("INSERT INTO meta(key,value) VALUES('last_count_check',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (datetime.datetime.now().isoformat(timespec="seconds"),))
        con.commit()
        if a.download:
            download_pending(con, st, facs, years, a.workers)
        con.close()


if __name__ == "__main__":
    main()

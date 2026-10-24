#!/usr/bin/env python3
"""Crawl FCC political files for stations into SQLite, optionally downloading PDFs.

  python3 -m ingest.crawl --stations 33710,66221 --years 2026 --download --workers 4

Resumable: files already listed are skipped on re-list only if --relist is absent;
downloads already on disk are never repeated.
"""
import argparse, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from . import fcc, db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(ROOT, "data", "pdfs")


def list_station(con, fac, year, relist):
    have = con.execute("SELECT COUNT(*) FROM files WHERE facility_id=? AND year=?", (fac, year)).fetchone()[0]
    if have and not relist:
        print(f"  {fac}/{year}: {have} files already listed", file=sys.stderr)
        return have
    n = 0
    for path, f in fcc.walk(str(fac), f"Political Files/{year}"):
        con.execute("""INSERT INTO files(file_manager_id,facility_id,year,folder_path,file_name,file_size,create_ts)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(file_manager_id) DO UPDATE SET
                       folder_path=excluded.folder_path, file_name=excluded.file_name, file_size=excluded.file_size""",
                    (f["file_manager_id"], fac, year, path, f.get("file_name"), f.get("file_size"), f.get("create_ts")))
        n += 1
        if n % 200 == 0:
            con.commit()
    con.commit()
    print(f"  {fac}/{year}: listed {n} files", file=sys.stderr)
    return n


def download_pending(con, facs, years, workers):
    q = f"""SELECT file_manager_id, facility_id, year FROM files
            WHERE downloaded=0 AND facility_id IN ({",".join("?"*len(facs))}) AND year IN ({",".join("?"*len(years))})"""
    rows = [tuple(r) for r in con.execute(q, (*facs, *years))]
    print(f"  downloading {len(rows)} files with {workers} workers", file=sys.stderr)

    def one(row):
        fid, fac, year = row
        d = os.path.join(PDF_DIR, str(fac), str(year))
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, fid + ".pdf")
        ok = os.path.exists(dest) and os.path.getsize(dest) > 0
        if not ok:
            ok = fcc.download(fid, dest)
            time.sleep(0.05)
        return fid, dest if ok else None

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for fid, dest in ex.map(one, rows):
            if dest:
                con.execute("UPDATE files SET downloaded=1, local_path=? WHERE file_manager_id=?", (os.path.relpath(dest, ROOT), fid))
            done += 1
            if done % 100 == 0:
                con.commit(); print(f"    {done}/{len(rows)}", file=sys.stderr)
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", required=True, help="comma-separated facility IDs")
    ap.add_argument("--years", default="2026")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--relist", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args()
    facs = [int(x) for x in a.stations.split(",")]
    years = [int(y) for y in a.years.split(",")]
    con = db.connect(a.db)
    for fac in facs:
        for y in years:
            list_station(con, fac, y, a.relist)
    if a.download:
        download_pending(con, facs, years, a.workers)


if __name__ == "__main__":
    main()

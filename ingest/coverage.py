#!/usr/bin/env python3
"""Coverage report: what has been crawled versus the national political-file totals.

The denominator is data/political_doc_counts.csv: per-station document counts for 2024 and 2026 for all
1,750 licensed full-power stations (one FCC folder call each, taken 2026-10-23). The numerator is the
local store (files listed, downloaded, parsed ok). Reported per state and per year, plus the gap list.

  python3 -m ingest.coverage              # table by state
  python3 -m ingest.coverage --json       # for export_methods / the About page
  python3 -m ingest.coverage --missing    # stations not yet crawled, biggest first
"""
import argparse, collections, csv, json, os, sys
from . import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTS = os.path.join(ROOT, "data", "political_doc_counts.csv")


def national():
    rows = {}
    with open(COUNTS) as fh:
        rd = csv.DictReader(fh)
        y26 = next(c for c in rd.fieldnames if c.startswith("docs_2026"))
        for r in rd:
            rows[int(r["facility_id"])] = {"call": r["call"], "state": r["state"], "2024": int(r["docs_2024"] or 0), "2026": int(r[y26] or 0)}
    return rows, y26.replace("docs_2026_through_", "")


def report(con):
    nat, asof = national()
    local = {}
    for fac, year, listed, dl, ok in con.execute("""SELECT f.facility_id, f.year, COUNT(*), SUM(f.downloaded), SUM(d.parse_status='ok')
                                                   FROM files f LEFT JOIN docs d USING(file_manager_id) WHERE f.deleted=0 GROUP BY 1,2"""):
        local[(fac, str(year))] = (listed, dl or 0, ok or 0)
    listing = {(r[0], str(r[1])): r[2] for r in con.execute("SELECT facility_id, year, status FROM listing")}
    by_state = collections.defaultdict(lambda: {y: {"stations": 0, "stations_crawled": 0, "stations_with_docs": 0, "docs_national": 0, "docs_listed": 0, "docs_downloaded": 0, "docs_ok": 0} for y in ("2024", "2026")})
    missing = []
    for fac, info in nat.items():
        for y in ("2024", "2026"):
            s = by_state[info["state"]][y]
            s["stations"] += 1; s["docs_national"] += info[y]
            if info[y] > 0:
                s["stations_with_docs"] += 1
            l = local.get((fac, y))
            if l or listing.get((fac, y)) in ("complete", "empty"):
                s["stations_crawled"] += 1
            if l:
                s["docs_listed"] += l[0]; s["docs_downloaded"] += l[1]; s["docs_ok"] += l[2]
            elif info[y] > 0:
                missing.append((info[y], y, fac, info["call"], info["state"]))
    total = {y: {k: sum(st[y][k] for st in by_state.values()) for k in next(iter(by_state.values()))[y]} for y in ("2024", "2026")}
    extra = {k: v for k, v in local.items() if k[0] not in nat}        # Class A / stations outside the full-power list
    return {"national_counts_as_of": asof, "by_state": dict(by_state), "total": total, "missing": sorted(missing, reverse=True),
            "stations_outside_national_list": len({k[0] for k in extra}), "docs_outside_national_list": sum(v[0] for v in extra.values())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--year", default="2026")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args(argv)
    con = db.connect(a.db)
    r = report(con)
    if a.json:
        print(json.dumps(r, indent=1)); return
    y = a.year
    print(f"Coverage vs national full-power counts (2026 counted through {r['national_counts_as_of']}); year {y}")
    print(f"  {'state':5} {'stns':>5} {'w/docs':>6} {'crawled':>7} {'national':>9} {'listed':>8} {'dl':>8} {'ok':>8} {'cov%':>6}")
    rows = sorted(r["by_state"].items(), key=lambda kv: -kv[1][y]["docs_national"])
    for st, v in rows:
        s = v[y]
        cov = 100.0 * s["docs_downloaded"] / s["docs_national"] if s["docs_national"] else 0
        print(f"  {st:5} {s['stations']:>5} {s['stations_with_docs']:>6} {s['stations_crawled']:>7} {s['docs_national']:>9,} {s['docs_listed']:>8,} {s['docs_downloaded']:>8,} {s['docs_ok']:>8,} {cov:>5.1f}%")
    for yy in ("2026", "2024"):
        t = r["total"][yy]
        print(f"  TOTAL {yy}: stations {t['stations']} (with docs {t['stations_with_docs']}, crawled {t['stations_crawled']})  national docs {t['docs_national']:,}  listed {t['docs_listed']:,}  downloaded {t['docs_downloaded']:,} ({100.0*t['docs_downloaded']/max(1,t['docs_national']):.1f}%)  parsed ok {t['docs_ok']:,}")
    print(f"  outside the full-power list: {r['stations_outside_national_list']} stations, {r['docs_outside_national_list']:,} docs")
    if a.missing:
        print(f"\n  not yet crawled for {y}, biggest first:")
        for n, yy, fac, call, st in [m for m in r["missing"] if m[1] == y][:60]:
            print(f"    {fac:>6} {call:8} {st}  {n:>5}")
        print(f"    ... {len([m for m in r['missing'] if m[1] == y])} stations, {sum(m[0] for m in r['missing'] if m[1] == y):,} documents")


if __name__ == "__main__":
    main()

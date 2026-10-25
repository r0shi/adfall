#!/usr/bin/env python3
"""Parse validation report: invariants checked over document.raw in Postgres, failure rates per template,
and the worst examples with file ids so a human can open the PDFs.

Checks (each applies only where the fields exist):
  lines_sum          order line amounts sum to the order gross (WideOrbit prints with line items)
  net_ratio          net is gross less the 15% agency commission (or equal to gross for direct buys)
  order_no_filename  a 7-9 digit number in the station's file name, when present, matches the parsed order number
  flight_range       flight dates fall inside the cycle window and start <= end
  gross_range        gross is between 0 and $5M (orders above $2M are listed for eyeballing)
  invoice_spots      WideOrbit invoice 'Total Spots' equals the number of per-spot lines read
  invoice_linked     an invoice's order number matches an order filed by the same station
  form_fields        a form yields an advertiser (committee / candidate / sponsor)
  dup_order_cross    an order number appears at stations of different groups (same group = sister stations, normal)

  python3 -m ingest.validate                   # full report
  python3 -m ingest.validate --examples 12     # more worst examples per check
  python3 -m ingest.validate --json > report.json
Also prints parse coverage by kind / template / status, which is the before/after number for parser work.
"""
import argparse, collections, datetime, json, os, re, sys
from . import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW = ("2025-06-01", "2027-01-31")
PDF_URL = "https://publicfiles.fcc.gov/api/manager/download/{folder}/{file}.pdf"


def num_in_name(name, order_no):
    """Order-number-looking tokens in the file name of the same length as the parsed number, excluding estimate numbers."""
    if not name or not order_no:
        return None
    cands = []
    for m in re.finditer(r"(?<![\d.])(\d{6,9})(?![\d.])", name):
        before = name[max(0, m.start() - 6):m.start()].lower()
        if re.search(r"est\.?\s*#?\s*$|#\s*$|inv(?:oice)?\s*#?\s*$", before):
            continue
        if re.fullmatch(r"20[2-3]\d[01]\d[0-3]\d", m.group(1)):
            continue
        if len(m.group(1)) == len(order_no):
            cands.append(m.group(1))
    return cands or None


def run(con, n_examples=6):
    docs = con.execute("""SELECT d.file_id, d.kind, d.template, d.source, d.parse_status, d.raw, f.file_name, f.facility_id, s.call, s.station_group, f.local_path
                          FROM document d JOIN opif_file f USING (file_id) JOIN station s USING (facility_id) WHERE f.deleted_at IS NULL""").fetchall()
    orders_by_station = collections.defaultdict(set)
    order_stations = collections.defaultdict(set)
    for fid, kind, tpl, src, status, raw, name, fac, call, grp, path in docs:
        if kind == "order" and raw.get("order_no"):
            orders_by_station[fac].add(raw["order_no"]); order_stations[raw["order_no"]].add((fac, grp))
    checks = collections.defaultdict(lambda: collections.defaultdict(lambda: {"n": 0, "fail": 0, "examples": []}))
    coverage = collections.Counter()

    def rec(tpl, check, ok, ex):
        c = checks[tpl][check]; c["n"] += 1
        if not ok:
            c["fail"] += 1
            if len(c["examples"]) < 200:
                c["examples"].append(ex)

    for fid, kind, tpl, src, status, raw, name, fac, call, grp, path in docs:
        tpl = tpl or f"{kind}/-"
        coverage[(kind, tpl, status)] += 1
        f = raw.get("fields") or {}
        ex = {"file_id": fid, "call": call, "file_name": name, "local_path": path}
        if kind == "order":
            g, net = raw.get("gross"), raw.get("net")
            lines = f.get("lines") or []
            if lines and g is not None:
                s = round(sum(l.get("amount") or 0 for l in lines), 2)
                rec(tpl, "lines_sum", abs(s - g) < 0.011, {**ex, "gross": g, "lines_sum": s, "diff": round(g - s, 2), "lines": len(lines)})
            if g and net is not None and g > 0:
                ratio = net / g
                rec(tpl, "net_ratio", abs(ratio - 0.85) < 0.012 or abs(ratio - 1.0) < 0.001, {**ex, "gross": g, "net": net, "ratio": round(ratio, 4)})
            cands = num_in_name(name, raw.get("order_no"))
            if cands:
                rec(tpl, "order_no_filename", raw["order_no"] in cands, {**ex, "order_no": raw["order_no"], "in_name": cands})
            fs, fe = raw.get("flight_start"), raw.get("flight_end")
            if fs or fe:
                ok = all(WINDOW[0] <= x <= WINDOW[1] for x in (fs, fe) if x) and (not (fs and fe) or fs <= fe)
                rec(tpl, "flight_range", ok, {**ex, "flight_start": fs, "flight_end": fe})
            if g is not None:
                rec(tpl, "gross_range", 0 <= g <= 5_000_000, {**ex, "gross": g})
                if g > 2_000_000:
                    rec(tpl, "gross_over_2M", False, {**ex, "gross": g, "advertiser": raw.get("advertiser")})
            if raw.get("order_no") and len(order_stations[raw["order_no"]]) > 1:
                groups = {gp for _, gp in order_stations[raw["order_no"]]}
                rec(tpl, "dup_order_cross", len(groups) == 1, {**ex, "order_no": raw["order_no"], "stations": sorted(x for x, _ in order_stations[raw["order_no"]])})
            if f.get("order_no_from_filename"):
                rec(tpl, "order_no_from_filename", False, {**ex, "order_no": raw["order_no"]})
        elif kind == "invoice":
            aired = f.get("aired") or []
            if raw.get("spots") is not None and aired and tpl == "wideorbit-invoice":
                rec(tpl, "invoice_spots", raw["spots"] == len(aired), {**ex, "total_spots": raw["spots"], "aired_lines": len(aired)})
            if raw.get("order_no"):
                rec(tpl, "invoice_linked", raw["order_no"] in orders_by_station[fac], {**ex, "order_no": raw["order_no"]})
            g = raw.get("gross")
            if g is not None:
                rec(tpl, "gross_range", 0 <= g <= 5_000_000, {**ex, "gross": g})
            fs, fe = raw.get("flight_start"), raw.get("flight_end")
            if fs or fe:
                rec(tpl, "flight_range", all(WINDOW[0] <= x <= WINDOW[1] for x in (fs, fe) if x), {**ex, "flight_start": fs, "flight_end": fe})
        elif kind == "form":
            rec(tpl, "form_fields", bool(raw.get("advertiser")), {**ex, "form": {k: v for k, v in (f.get("form") or {}).items() if k in ("candidate", "committee", "sponsor", "agency")}})
            fe = raw.get("flight_end")
            if fe:
                rec(tpl, "flight_range", WINDOW[0] <= fe <= WINDOW[1], {**ex, "election_date": fe})
    return docs, checks, coverage


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="also write the report (JSON) here; default data/validate-<date>.json")
    a = ap.parse_args(argv)
    with db.connect() as con:
        docs, checks, coverage = run(con, a.examples)
    total = len(docs)
    by_status = collections.Counter(); by_kind = collections.Counter()
    for (k, t, s), n in coverage.items():
        by_status[s] += n; by_kind[(k, s)] += n
    report = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "documents": total, "by_status": dict(by_status),
              "coverage": [{"kind": k, "template": t, "status": s, "n": n} for (k, t, s), n in sorted(coverage.items(), key=lambda x: -x[1])],
              "checks": {tpl: {c: {"n": v["n"], "fail": v["fail"], "rate": round(v["fail"] / v["n"], 4) if v["n"] else 0, "examples": v["examples"][:a.examples]}
                              for c, v in cs.items()} for tpl, cs in checks.items()}}
    out = a.out or os.path.join(ROOT, "data", f"validate-{datetime.date.today().isoformat()}.json")
    json.dump(report, open(out, "w"), indent=1, default=str)
    if a.json:
        print(json.dumps(report, indent=1, default=str)); return
    ok = by_status.get("ok", 0)
    print(f"Parse validation {report['generated']}   documents {total:,}   ok {ok:,} ({100*ok/max(1,total):.1f}%)  partial {by_status.get('partial',0):,}  failed {by_status.get('failed',0):,}  unrecognized {by_status.get('unrecognized',0):,}")
    print(f"  by kind: " + "  ".join(f"{k}:{s}={n:,}" for (k, s), n in sorted(by_kind.items(), key=lambda x: -x[1])))
    print("\n  coverage by kind / template / status:")
    for row in report["coverage"][:40]:
        print(f"    {row['n']:7,}  {row['kind']:8s} {row['template']:24s} {row['status']}")
    print("\n  invariant checks (fail / checked):")
    for tpl in sorted(checks, key=lambda t: -sum(v["n"] for v in checks[t].values())):
        for c, v in sorted(checks[tpl].items()):
            flag = "  <<" if v["n"] and v["fail"] / v["n"] > 0.05 else ""
            print(f"    {tpl:24s} {c:22s} {v['fail']:6,} / {v['n']:7,}  ({100*v['fail']/max(1,v['n']):5.1f}%){flag}")
    print(f"\n  worst examples (open with: open data/pdfs/<facility>/<year>/<file_id>.pdf):")
    for tpl in sorted(checks, key=lambda t: -sum(v["fail"] for v in checks[t].values())):
        for c, v in checks[tpl].items():
            if not v["fail"] or c == "dup_order_cross":
                continue
            print(f"    -- {tpl} / {c}: {v['fail']} failures")
            for e in v["examples"][:a.examples]:
                detail = {k: val for k, val in e.items() if k not in ("file_id", "call", "file_name", "local_path")}
                print(f"       {e['file_id']}  {e['call']:8s} {str(e['file_name'])[:55]:55s} {json.dumps(detail, default=str)[:150]}")
    print(f"\n  report written to {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()

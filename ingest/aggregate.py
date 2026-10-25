#!/usr/bin/env python3
"""Roll parsed documents up to spend per station per buyer and export JSON for the web app.

Spend rule, per order number within a station-year:
  * if invoices exist, spend = sum of gross over distinct invoice numbers (what actually aired)
  * else spend = gross on the latest order revision (latest print date, then latest upload)
Buyer = the leaf folder the station filed the documents under (candidate, committee or
issue sponsor), which is how station staff label buys. Category = the second folder level
(Federal / State / Local / Non-Candidate Issue Ads).

  python3 -m ingest.aggregate            # writes web/data/spend/<facility>.json and index.json
"""
import argparse, collections, datetime, json, os, re
from . import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "data", "spend")


from .names import name_tokens

FLIGHT_FOLDER = re.compile(r"^(FLIGHT|WEEK|WK|INVOICES?|ORDERS?|CONTRACTS?|\d{1,2}[./-]\d{1,2})", re.I)


def split_path(p):
    """'Political Files/2026/Federal/US House/Jane Doe-D-US House 1/FLIGHT 9826' -> ('Federal', 'Jane Doe-D-US House 1')
    Stations differ in depth: some add office levels above the buyer ("US House", "PA House of
    Representatives"), some add flight folders below it. An intermediate folder with no name tokens
    (only office/party/state words) is an office level; a leaf keeps its name whatever it says."""
    parts = p.split("/")
    cat = parts[2] if len(parts) > 2 else "Other"
    rest = parts[3:]
    while len(rest) > 1 and FLIGHT_FOLDER.match(rest[-1]):
        rest = rest[:-1]
    while len(rest) > 1 and (not name_tokens(rest[0]) or re.search(r"\bCOUNTY$|\bCITY OF\b|\bSCHOOL (BOARD|DISTRICT)$", rest[0], re.I)):
        rest = rest[1:]                                   # office/jurisdiction levels above the buyer
    return cat, (rest[0] if rest else None)


def aggregate_station(con, fac, year):
    rows = con.execute("""SELECT f.file_id AS file_manager_id, f.folder_path, f.fcc_created_at::text AS create_ts, d.kind, d.parse_status,
                                 d.raw->>'order_no' order_no, d.raw->>'revision' revision, d.raw->>'invoice_no' invoice_no, d.raw->>'advertiser' advertiser,
                                 d.raw->>'agency' agency, d.raw->>'product' product, d.raw->>'flight_start' flight_start, d.raw->>'flight_end' flight_end,
                                 d.raw->>'print_date' print_date, (d.raw->>'gross')::float gross, (d.raw->>'net')::float net, (d.raw->>'spots')::int spots,
                                 d.raw->'ad_ids' ad_ids, d.raw->'fields' fields
                          FROM opif_file f LEFT JOIN document d USING (file_id)
                          WHERE f.facility_id=%s AND f.year=%s AND f.deleted_at IS NULL""", (fac, year)).fetchall()
    orders = collections.defaultdict(lambda: {"invoices": {}, "orders": [], "forms": [], "folder": None, "advertiser": None, "agencies": set(), "ad_ids": set()})
    kinds = collections.Counter(); status = collections.Counter()
    for r in rows:
        kinds[r["kind"] or "unparsed"] += 1; status[r["parse_status"] or "unparsed"] += 1
        if not r["kind"] or r["kind"] == "other":
            continue
        key = r["order_no"] or ("form:" + r["file_manager_id"] if r["kind"] == "form" else
                                "inv:" + (r["invoice_no"] or r["file_manager_id"]) if r["kind"] == "invoice" else None)
        if not key:
            continue
        o = orders[key]
        if r["kind"] == "invoice":
            if r["gross"] is not None:
                o["invoices"][r["invoice_no"] or r["file_manager_id"]] = r["gross"]
            for a in (r["ad_ids"] or []):
                o["ad_ids"].add(a)
        elif r["kind"] == "order":
            o["orders"].append((r["print_date"] or "", r["create_ts"] or "", r["gross"]))
        else:
            o["forms"].append(r["file_manager_id"])
        if r["kind"] != "form" or not o["folder"]:
            o["folder"] = o["folder"] if (o["folder"] and r["kind"] == "form") else r["folder_path"]
        o["advertiser"] = o["advertiser"] or r["advertiser"]
        if r["agency"]:
            o["agencies"].add(r["agency"].split(",")[0].strip())

    buyers = {}
    total = invoiced = 0.0
    for key, o in orders.items():
        if key.startswith("form:"):
            spend, src = 0.0, "form"
        elif key.startswith("inv:"):
            spend, src = sum(o["invoices"].values()), "unlinked"   # invoice with no order number: report, don't add to total
        elif o["invoices"]:
            spend, src = sum(o["invoices"].values()), "invoice"
        elif o["orders"]:
            spend, src = (sorted(o["orders"])[-1][2] or 0.0), "order"
        else:
            continue
        cat, leaf = split_path(o["folder"] or "")
        name = leaf or o["advertiser"] or "Unknown"
        b = buyers.setdefault((cat, name), {"name": name, "category": cat, "gross": 0.0, "invoiced": 0.0, "unlinked_invoiced": 0.0,
                                            "orders": 0, "forms": 0, "agencies": set(), "ad_ids": set(), "advertisers": set()})
        if src == "unlinked":
            b["unlinked_invoiced"] += spend
        else:
            b["gross"] += spend; total += spend
        if src == "invoice":
            b["invoiced"] += spend; invoiced += spend
        b["orders"] += 1 if src in ("invoice", "order") else 0
        b["forms"] += len(o["forms"])
        b["agencies"] |= o["agencies"]; b["ad_ids"] |= o["ad_ids"]
        if o["advertiser"]:
            b["advertisers"].add(o["advertiser"])
    out_buyers = sorted(({**b, "gross": round(b["gross"], 2), "invoiced": round(b["invoiced"], 2), "unlinked_invoiced": round(b["unlinked_invoiced"], 2),
                          "agencies": sorted(b["agencies"])[:5], "ad_ids": len(b["ad_ids"]), "advertisers": sorted(b["advertisers"])[:3]}
                         for b in buyers.values()), key=lambda b: -b["gross"])
    by_cat = collections.Counter()
    for b in out_buyers:
        by_cat[b["category"]] += b["gross"]
    return {"fac": fac, "year": year, "generated": datetime.date.today().isoformat(), "docs": len(rows),
            "kinds": dict(kinds), "parse_status": dict(status), "total": round(total, 2), "invoiced": round(invoiced, 2),
            "by_category": {k: round(v, 2) for k, v in by_cat.items()}, "buyers": out_buyers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()
    con = db.connect()
    os.makedirs(OUT, exist_ok=True)
    index = {}
    for (fac,) in con.execute("SELECT DISTINCT facility_id FROM opif_file WHERE year=%s", (a.year,)):
        s = aggregate_station(con, fac, a.year)
        json.dump(s, open(os.path.join(OUT, f"{fac}.json"), "w"), separators=(",", ":"))
        index[str(fac)] = {"total": s["total"], "buyers": len(s["buyers"]), "docs": s["docs"],
                           "by_category": s["by_category"], "top": [b["name"] for b in s["buyers"][:3]]}
        print(f"{fac}: {s['docs']} docs, {len(s['buyers'])} buyers, ${s['total']:,.0f} (invoiced ${s['invoiced']:,.0f}) kinds={s['kinds']}")
    json.dump({"year": a.year, "generated": datetime.date.today().isoformat(), "stations": index},
              open(os.path.join(OUT, "index.json"), "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()

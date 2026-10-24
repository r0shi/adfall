#!/usr/bin/env python3
"""Parse downloaded political-file PDFs into structured rows.

Handles the three document kinds that make up nearly all of a station's
political file when the station runs WideOrbit traffic (most do):
  * order / contract  ("CONTRACT", "Contract / Revision")
  * invoice           ("INVOICE", "Invoice #", per-spot lines with Ad-ID)
  * NAB PB-19 forms   (fillable AcroForm fields: candidate, committee, agency...)
Anything else is stored as kind=other so the gap is visible.

  python3 -m ingest.parse            # parse everything downloaded and unparsed
  python3 -m ingest.parse --file x.pdf   # print the parse of one file
"""
import argparse, json, os, re, sys
from datetime import datetime
from pypdf import PdfReader
from . import db

PARSER_VERSION = 2
OCR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ocr")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONEY = r"\$?\(?-?[\d,]+\.\d\d\)?"


def money(s):
    if s is None:
        return None
    neg = "(" in s or "-" in s
    v = float(re.sub(r"[^\d.]", "", s) or 0)
    return -v if neg else v


def iso(d):
    """mm/dd/yy or mm/dd/yyyy -> ISO."""
    if not d:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def read(path):
    r = PdfReader(path)
    text = "\n".join((pg.extract_text() or "") for pg in r.pages)
    source = "text"
    if len(text.strip()) < 200:
        ocr = os.path.join(OCR_DIR, os.path.splitext(os.path.basename(path))[0] + ".txt")
        if os.path.exists(ocr):
            text, source = open(ocr).read(), "ocr"
    fields = {}
    try:
        for k, v in (r.get_fields() or {}).items():
            val = v.get("/V")
            if val not in (None, "", "/Off"):
                fields[k] = str(val).lstrip("/")
    except Exception:
        pass
    return text, fields, len(r.pages), source


def classify(text, fields):
    head = text[:3000]
    if re.search(r"\bINVOICE\b", head) and re.search(r"Invoice\s*#", head):
        return "invoice"
    if re.search(r"\bCONTRACT\b", head) and re.search(r"Contract\s*/\s*Revision", head):
        return "order"
    if re.search(r"Contract #\s*\d+", head) and re.search(r"Total \$:", head):
        return "order"                                    # Katz / Sinclair template
    if re.search(r"Contract Agreement Between", head) and re.search(r"Cont[ra]+ct\s*/\s*Revision", head):
        return "order"                                    # WideOrbit print via OCR
    if fields and any(re.search(r"candidate name|issue|sponsor|authorized committee", k, re.I) for k in fields):
        return "form"
    if re.search(r"ADVERTISEMENT AGREEMENT FORM|AGREEMENT FORM FOR (NON-CANDIDATE|POLITICAL)|PB-1[89]", text[:4000], re.I):
        return "form"
    return "other"


def parse_order(text):
    d = {}
    m = re.search(r"Contract Dates\s*\n(?:Original Date / Revision\s*\n)?(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)\s*\n(\d\d/\d\d/\d\d)(\d\d/\d\d/\d\d)(.*)", text)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
        d["print_date"] = iso(m.group(4))
        d["advertiser"] = m.group(5).strip() or None
    m = re.search(r"^Product\s*\n(.+)$", text, re.M)
    if m:
        d["product"] = m.group(1).strip()
    m = re.search(r"Contract / Revision\s*\n(\d+)\s*/\s*(\d*)", text)
    if m:
        d["order_no"], d["revision"] = m.group(1), (m.group(2) or "0")
    m = re.search(r"Demographic\s*\n[^\n]*\n([^\n]+)", text)
    if m and not re.match(r"Ch\*|Attention", m.group(1)):
        d["agency"] = m.group(1).strip()
    # "Totals 87 $33,150.00412.21" (ratings glued on) or "Totals 0 $0.00"
    m = re.search(r"^Totals\s+(\d+)\s+(" + MONEY + ")", text, re.M)
    if m:
        d["spots"], d["gross"] = int(m.group(1)), money(m.group(2))
    # "$28,177.50$33,150.0087Totals ($4,972.50)" -> net, gross
    m = re.search(r"^(" + MONEY + r")(" + MONEY + r")\d+Totals", text, re.M)
    if m:
        d["net"] = money(m.group(1))
        d.setdefault("gross", money(m.group(2)))
    lines = []
    for lm in re.finditer(r"^(\d{1,3}) (\d\d/\d\d/\d\d) (\d\d/\d\d/\d\d) (.+?) :(\d+) (\w+) (\d+) (" + MONEY + ")", text, re.M):
        lines.append({"line": int(lm.group(1)), "start": iso(lm.group(2)), "end": iso(lm.group(3)),
                      "program": lm.group(4).strip(), "len": int(lm.group(5)), "spots": int(lm.group(7)), "amount": money(lm.group(8))})
    d["fields"] = {"lines": lines}
    return d


def parse_order_ocr(text):
    """WideOrbit contract read through OCR (Nexstar prints these to image PDFs)."""
    d = {}
    m = re.search(r"\b(\d{7})\s*/", text[:2500])
    if m:
        d["order_no"] = m.group(1)
    m = re.search(r"(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", text[:2500])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    m = re.search(r"^(.*?)\s+(\d\d/\d\d/\d\d)\s*/\s*(\d\d/\d\d/\d\d)\s*$", text[:2500], re.M)
    if m:
        adv = m.group(1)
        adv = adv[adv.index("POL/"):] if "POL/" in adv else re.sub(r"^[\W\d]*(\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4})?[\W\d]*", "", adv)
        adv = adv.strip(" |'‘")  # OCR glues the station phone number onto this line
        d["advertiser"] = adv or None
        d["print_date"] = iso(m.group(3))
    m = re.search(r"^Product\s*\n\W*([^\n]+)", text[:2500], re.M)
    if m:
        d["product"] = m.group(1).strip()
    m = re.search(r"^\W*Totals\s+(\d+)\s+[$S]\s?([\d,]+\.\d\d)\s+\([$S]?([\d,]+\.\d\d)\)\s+[$S]\s?([\d,]+\.\d\d)", text, re.M)
    if m:
        d["spots"], d["gross"], d["net"] = int(m.group(1)), money(m.group(2)), money(m.group(4))
    else:
        m = re.search(r"^\W*Totals\s+(\d+)\s+[$S]\s?([\d,]+\.\d\d)", text, re.M)
        if m:
            d["spots"], d["gross"] = int(m.group(1)), money(m.group(2))
    d["fields"] = {"template": "wideorbit-ocr"}
    return d


def parse_order_katz(text):
    """Katz / Sinclair contract: labels inline ('Advertiser: X Market: Y Total $: $8,000.00')."""
    d = {}
    g = lambda rx: (lambda m: m.group(1).strip() if m else None)(re.search(rx, text[:4000], re.I))
    d["order_no"] = g(r"Contract #\s*(\d+)")
    d["revision"] = g(r"Version (\d+)")
    d["advertiser"] = g(r"Advertiser:\s*(.+?)\s+(?:Market|Total|Product):")
    d["agency"] = g(r"Agency:\s*(.+?)\s+Advertiser:")
    d["product"] = g(r"Product:\s*(.+?)\s+(?:Order Office|Office|Total|Service):")
    m = re.search(r"Flight:\s*(\d\d?/\d\d?/\d\d(?:\d\d)?)\s*-\s*(\d\d?/\d\d?/\d\d(?:\d\d)?)", text[:4000])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    d["print_date"] = iso(g(r"Changes as of:\s*(\d\d?/\d\d?/\d{4})"))
    v = g(r"Total \$:\s*[$S]?\s?([\d,]+\.\d\d)")
    d["gross"] = money(v) if v else None
    v = g(r"Total Spots:\s*(\d+)")
    d["spots"] = int(v) if v else None
    d["fields"] = {"template": "katz"}
    return d


def parse_invoice(text):
    d = {}
    m = re.search(r"Order\s*#\s*(\d+)", text)
    if m:
        d["order_no"] = m.group(1)
    m = re.search(r"(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)\s*\n([^\n]+)\n([^\n]+)", text[:1500])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
        d["advertiser"] = m.group(3).strip()
        if not re.match(r"Property|Billing|Sales", m.group(4)):
            d["agency"] = m.group(4).strip()
    m = re.search(r"^Product\s*\n(?:Estimate # \d+\s*\n)?(.+)$", text[:1500], re.M)
    if m and not m.group(1).startswith("Estimate"):
        d["product"] = m.group(1).strip()
    m = re.search(r"Invoice #\s*\n(?:[^\n]*\n){0,3}?(\d+-\d+)", text[:3000])
    if m:
        d["invoice_no"] = m.group(1)
    m = re.search(r"Invoice Date\s*\n(?:[^\n]*\n){0,2}?(\d\d/\d\d/\d\d)", text[:3000])
    if m:
        d["print_date"] = iso(m.group(1))
    m = re.search(r"Gross Total\s*(" + MONEY + ")", text)
    if m:
        d["gross"] = money(m.group(1))
    m = re.search(r"(" + MONEY + r")\s*Net Amount Due", text)
    if m:
        d["net"] = money(m.group(1))
    m = re.search(r"Total Spots\s+(\d+)", text)
    if m:
        d["spots"] = int(m.group(1))
    # per-spot lines: "... 05/27/26 6:14 AM JTFI2000HW1 KCCI"
    spots = re.findall(r"(\d\d/\d\d/\d\d) (\d{1,2}:\d\d [AP]M) ([A-Z0-9]{6,16})\b", text)
    d["ad_ids"] = sorted({s[2] for s in spots})
    d["fields"] = {"aired": [{"date": iso(a), "time": t, "ad_id": c} for a, t, c in spots]}
    return d


FORM_MAP = [  # (our key, regex over field name)
    ("candidate", r"candidate name"), ("committee", r"authorized committee"), ("agency", r"agency requesting|agency name"),
    ("party", r"political party"), ("office", r"office sought"), ("election_date", r"date of election"),
    ("treasurer", r"treasurer"), ("estimate", r"^est"), ("issue", r"^issue|issue description|referendum"),
    ("sponsor", r"sponsor|name of (entity|advertiser|organization)|^name - page"), ("contact", r"contact person|chief executive|^contact \d"),
    ("requested_by", r"station time requested by"),
]


def parse_form(text, fields):
    out = {}
    for key, rx in FORM_MAP:
        for k, v in fields.items():
            if re.search(rx, k, re.I) and key not in out and v not in ("Yes", "On"):
                out[key] = v.strip()
    level = None
    for k, v in fields.items():
        if v in ("Yes", "On"):
            if re.search(r"state or local", k, re.I): level = "state/local"
            elif re.search(r"^federal\s*-\s*page", k, re.I) and level is None: level = "federal"
    d = {"advertiser": out.get("committee") or out.get("candidate") or out.get("sponsor"),
         "agency": out.get("agency"), "fields": {"form": out, "level": level, "raw": fields}}
    if out.get("election_date"):
        d["flight_end"] = iso(out["election_date"])
    return d


def parse_file(path):
    text, fields, pages, source = read(path)
    kind = classify(text, fields)
    if kind == "order":
        if re.search(r"Contract #\s*\d+", text[:3000]) and re.search(r"Total \$:", text[:3000]):
            d = parse_order_katz(text)
        elif source == "ocr":
            d = parse_order_ocr(text)
        else:
            d = parse_order(text)
    elif kind == "invoice":
        d = parse_invoice(text)
    elif kind == "form":
        d = parse_form(text, fields)
    else:
        d = {"fields": {"pages": pages, "chars": len(text), "has_text": len(text.strip()) > 200 and source == "text"}}
    d["kind"] = kind
    d.setdefault("fields", {})["source"] = source
    need = {"order": ("order_no", "gross"), "invoice": ("order_no", "gross"), "form": ("advertiser",), "other": ()}[kind]
    missing = [k for k in need if d.get(k) is None]
    d["parse_status"] = "ok" if not missing else ("partial" if len(missing) < len(need) else "failed")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--only-failed", action="store_true", help="reparse documents that are not parse_status=ok or are kind=other")
    a = ap.parse_args()
    if a.file:
        d = parse_file(a.file)
        f = d.pop("fields", {})
        d["ad_ids"] = len(d.get("ad_ids") or [])
        d["n_lines"] = len(f.get("lines") or f.get("aired") or [])
        d["form"] = f.get("form"); d["level"] = f.get("level")
        print(json.dumps(d, indent=1, default=str))
        return
    con = db.connect(a.db)
    q = "SELECT file_manager_id, local_path FROM files WHERE downloaded=1"
    if a.only_failed:
        q += " AND file_manager_id IN (SELECT file_manager_id FROM docs WHERE parse_status!='ok' OR kind='other')"
    elif not a.reparse:
        q += " AND file_manager_id NOT IN (SELECT file_manager_id FROM docs WHERE parser_version=%d)" % PARSER_VERSION
    rows = con.execute(q).fetchall()
    print(f"parsing {len(rows)} files", file=sys.stderr)
    stats = {}
    for i, r in enumerate(rows, 1):
        try:
            d = parse_file(os.path.join(ROOT, r["local_path"]))
        except Exception as e:
            d = {"kind": "other", "parse_status": "failed", "fields": {"error": str(e)[:200]}}
        stats[(d["kind"], d["parse_status"])] = stats.get((d["kind"], d["parse_status"]), 0) + 1
        con.execute("""INSERT OR REPLACE INTO docs(file_manager_id,kind,parse_status,order_no,revision,invoice_no,advertiser,agency,product,
                       flight_start,flight_end,print_date,gross,net,spots,ad_ids,fields,parser_version)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["file_manager_id"], d["kind"], d["parse_status"], d.get("order_no"), d.get("revision"), d.get("invoice_no"),
                     d.get("advertiser"), d.get("agency"), d.get("product"), d.get("flight_start"), d.get("flight_end"), d.get("print_date"),
                     d.get("gross"), d.get("net"), d.get("spots"), json.dumps(d.get("ad_ids") or []), json.dumps(d.get("fields") or {}, default=str),
                     PARSER_VERSION))
        if i % 250 == 0:
            con.commit(); print(f"  {i}/{len(rows)}", file=sys.stderr)
    con.commit()
    for k, v in sorted(stats.items()):
        print(f"  {k[0]:8s} {k[1]:8s} {v}", file=sys.stderr)


if __name__ == "__main__":
    main()

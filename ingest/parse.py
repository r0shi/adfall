#!/usr/bin/env python3
"""Parse downloaded political-file PDFs into structured rows.

Every document gets a kind (order | invoice | form | other), a template naming the layout that
was recognised, a source (text layer or OCR) and a parse_status (ok | partial | failed | unrecognized). Layouts:

  wideorbit-contract      WideOrbit "CONTRACT" print, text layer (Hearst, Tegna, Fox, Nexstar invoices...)
  wideorbit-contract-ocr  the same printed to an image PDF and OCR'd (Nexstar, Gray)
  wideorbit-order         WideOrbit "ORDER" print ("Order / Rev:", "Flight Dates:"), text (Gray, Nexstar, Scripps, Allen)
  wideorbit-order-ocr     the same OCR'd (Gray scans)
  wideorbit-invoice       WideOrbit invoice with per-spot Ad-ID lines
  katz                    Katz / Sinclair contract ("Contract #", "Total $:"), text or OCR
  katz-ecr                Katz ECR confirmation contract ("External #", "Grand Total:"), Sinclair stations
  locality-worksheet      Locality rep "CONTRACT WORKSHEET REPORT" (OCR)
  sinclair-contract       Sinclair traffic contract ("Contract #", "Date Entered", "Schedule Dates"), OCR
  eport                   Sinclair ePort order/revision summary
  sinclair-invoice        Sinclair "OFFICIAL BILLING INVOICE" (text or OCR)
  nab-acroform            NAB PB-19 fillable form, values in AcroForm fields
  nab-text                NAB / station agreement forms read from page text or OCR (scanned, signed forms)
  nab-supplement          ad-specific NAB supplements and addenda (ISCI codes, no money) -> kind other
Anything else is kind=other with template NULL so the gap is visible; ingest.validate clusters those.

Text extraction is cached under data/text/<ab>/<file_id>.json (text layer, AcroForm fields, page count) so
re-parsing after a parser change is regex-only. Image-only PDFs are flagged needs_ocr; ingest.ocr fills
data/ocr/<file_id>.txt and `parse --only-failed` picks the text up.

  python3 -m ingest.parse                 # parse everything downloaded and not yet at PARSER_VERSION
  python3 -m ingest.parse --only-failed   # re-parse documents that are not ok or unrecognised (after OCR)
  python3 -m ingest.parse --reparse       # everything (from the text cache)
  python3 -m ingest.parse --file x.pdf    # print the parse of one file
"""
import argparse, datetime as _dt, io, json, logging, os, re, sys, time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from . import db
from .runlog import Stage

log = logging.getLogger("ingest.parse")
PARSER_VERSION = 5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_DIR = os.path.join(ROOT, "data", "ocr")
TEXT_DIR = os.path.join(ROOT, "data", "text")
MIN_TEXT = 200                     # fewer chars than this in the text layer: image-only, needs OCR
NUM_TEXT = r"\d{1,3}(?:,\d{3})*\.\d\d"                      # text layer: always comma-grouped; stops before a glued rating ("$6,000.007.44")
NUM = r"(?:\d{1,3}(?:[,.]\d{3})*|\d{4,})[.:;]\d\d"     # OCR: 22.525.00 / 22,525:00 / 8820.00 also occur. Only for OCR templates.
MONEY = r"\$?\(?-?" + NUM_TEXT + r"\)?"
DATE = r"\d\d?/\d\d?/\d\d(?:\d\d)?"


# ----------------------------------------------------------------------------------------------- helpers
def money(s):
    """'$22,525.00', '(1,590.00)', OCR '22.525.00' / '22,525:00' -> float. Last separator is the decimal point."""
    if s is None:
        return None
    neg = "(" in s or s.strip().startswith("-")
    digits = re.sub(r"[^\d.,:;]", "", s)
    digits = re.sub(r"[.,:;](\d\d)$", r"\1", digits)         # drop the decimal separator; cents are the last two digits
    digits = re.sub(r"[^\d]", "", digits)
    if not digits:
        return None
    v = int(digits) / 100.0
    return -v if neg else v


def iso(d):
    """mm/dd/yy, mm/dd/yyyy, 'November 3, 2026' -> ISO date, or None."""
    if not d:
        return None
    d = d.strip().rstrip(".,")
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b%d/%y", "%b %d/%y"):
        try:
            return datetime.strptime(re.sub(r"\s+", " ", d.replace(" ,", ",")), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" |'‘’,:;-_") or None


def first(rx, text, flags=0, group=1):
    m = re.search(rx, text, flags)
    return m.group(group).strip() if m else None


def text_cache_path(fid):
    return os.path.join(TEXT_DIR, fid[:2], fid + ".json")


# ----------------------------------------------------------------------------------------------- extraction
def extract(path):
    """Text layer, AcroForm fields and page count of a PDF; PDF portfolios are unpacked (Hearst files
    them: the real order/invoice/form are attachments inside a one-page cover)."""
    from pypdf import PdfReader
    r = PdfReader(path)
    text = "\n".join((pg.extract_text() or "") for pg in r.pages)
    fields = acroform(r)
    pages = len(r.pages)
    portfolio = False
    if len(text.strip()) < MIN_TEXT or "open this PDF portfolio" in text[:600]:
        try:
            atts = r.attachments
        except Exception:
            atts = {}
        parts = []
        for name, blobs in (atts or {}).items():
            if not name.lower().endswith(".pdf"):
                continue
            for blob in blobs:
                try:
                    sub = PdfReader(io.BytesIO(blob))
                    parts.append("\n".join((pg.extract_text() or "") for pg in sub.pages))
                    fields.update(acroform(sub)); pages += len(sub.pages); portfolio = True
                except Exception as e:
                    parts.append(f"[attachment {name} unreadable: {e}]")
        if parts:
            text = "\n\f\n".join(parts)
    return text, fields, pages, portfolio


def acroform(reader):
    out = {}
    try:
        for k, v in (reader.get_fields() or {}).items():
            val = v.get("/V")
            if val not in (None, "", "/Off"):
                out[k] = str(val).lstrip("/")
    except Exception:
        pass
    return out


def read(path, fid=None, use_cache=True):
    """-> text, fields, pages, source ('text' | 'ocr' | 'none'), portfolio"""
    cache = text_cache_path(fid) if fid else None
    data = None
    if cache and use_cache and os.path.exists(cache):
        try:
            data = json.load(open(cache))
        except ValueError:
            data = None
    if data is None:
        text, fields, pages, portfolio = extract(path)
        data = {"text": text, "fields": fields, "pages": pages, "portfolio": portfolio}
        if cache:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            tmp = cache + ".part"
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, cache)
    text, source = data["text"], "text"
    if len(text.strip()) < MIN_TEXT:
        ocr = os.path.join(OCR_DIR, (fid or os.path.splitext(os.path.basename(path))[0]) + ".txt")
        if os.path.exists(ocr):
            text, source = re.sub(r"[^\x00-\x7f\u00c0-\u00ff]", "", open(ocr).read()), "ocr"     # Vision hallucinates ł ą ẠỊ after digits
        else:
            source = "none"
    return text, data["fields"], data["pages"], source, data.get("portfolio", False)


# ----------------------------------------------------------------------------------------------- classification
FORM_FIELD_RX = re.compile(r"candidate name|issue|sponsor|authorized committee", re.I)
FORM_TEXT_RX = re.compile(r"ADVERTISEMENT\s+AGREEMENT\s+FORM|AGREEMENT FORM FOR (?:NON-CANDIDATE|POLITICAL|CANDIDATE)|PB-1[89]\b|Political Broadcast Agreement Form|"
                          r"SUPPLEMENT TO ORDER FOR|POLITICAL INQUIRY RECORD|Public File Disclosure Form|Political Advertising Issues|hereby requests? station time|"
                          r"ADVERTISEMENT POLITICAL FILE FORM|request station time as follows", re.I)
SUPPLEMENT_RX = re.compile(r"IF ANY AD BUY IS REJECTED|Ad-Specific Information|NAB Addendum|Spot Approv", re.I)


def classify(text, fields, source):
    """-> (kind, template)"""
    head = text[:4000]
    T = lambda rx, s=head, f=0: re.search(rx, s, f) is not None
    ocr = "-ocr" if source == "ocr" else ""
    if "OFFICIAL BILLING INVOICE" in text[:8000]:
        return "invoice", "sinclair-invoice"
    if T(r"\bINVOICE\b") and T(r"Invoice\s*#"):
        return "invoice", "wideorbit-invoice"
    if T(r"CONTRACT WORKSHEET REPORT"):
        return "order", "locality-worksheet"
    if T(r"External #") and T(r"Buyer Name") and T(r"Contract #"):
        return "order", "katz-ecr"
    if T(r"Contract #\s*\d{6,9}") and T(r"Date Entered") and T(r"Schedule Dates"):
        return "order", "sinclair-contract"
    if T(r"Contract #\s*\d+") and T(r"Total \$"):
        return "order", "katz"
    if T(r"Airtime Dollars:") and T(r"Flight Start:"):
        return "order", "eport"
    if T(r"\bCONTRACT\b") and T(r"Contract\s*/\s*Revision"):
        return "order", "wideorbit-contract" + ocr
    if T(r"Contract Agreement Between") and T(r"Cont[ra]+ct\s*\W?\s*Revision|Alt Order"):
        return "order", "wideorbit-contract-ocr"
    if (T(r"Order\s*/\s*Rev\b") and (T(r"Flight Dates") or T(r"Alt Order\s*#"))) or (T(r"Alt Order\s*#") and T(r"Flight Dates")):
        return "order", "wideorbit-order" + ocr
    if fields and any(FORM_FIELD_RX.search(k) for k in fields):
        return "form", "nab-acroform"
    if SUPPLEMENT_RX.search(text[:3000]) and not FORM_TEXT_RX.search(text[:3000]):
        return "other", "nab-supplement"
    if FORM_TEXT_RX.search(text[:8000]):
        return "form", "nab-text"
    return "other", None


# ----------------------------------------------------------------------------------------------- orders
# "1 05/27/26 05/28/26 M-F News CH8 @ 430-5A 430-5A :30 NM 2 $20.00N" or, with spots/week and rate, "22 08/13/26 08/24/26 FBI 858p-10p M------ :30 0 $3,500.00 NM 3 $10,500.00N"
LINE_RX = re.compile(r"(?<![\d/$,.]) ?(\d{1,3}) (\d\d/\d\d/\d\d) (\d\d/\d\d/\d\d) (.+?) ?:(\d+)(?: (\d+) (" + MONEY + r"))? (\w+) (\d+) (" + MONEY + ")", re.M)


def parse_order(text):
    """WideOrbit CONTRACT print, text layer."""
    d = {}
    m = re.search(r"Contract Dates\s*\n(?:Original Date / Revision\s*\n)?(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)\s*\n(\d\d/\d\d/\d\d)(\d\d/\d\d/\d\d)(.*)", text)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
        d["print_date"] = iso(m.group(4))
        d["advertiser"] = clean(m.group(5))
    m = re.search(r"^Product\s*\n(.+)$", text, re.M)
    if m:
        d["product"] = clean(m.group(1))
    m = re.search(r"Contract / Revision\s*\n(\d+)\s*/\s*(\d*)", text)
    if m:
        d["order_no"], d["revision"] = m.group(1), (m.group(2) or "0")
    m = re.search(r"Estimate #\s*\n(?:[^\n]*\n)?([^\n]*?)\s*$", text[:3000], re.M)
    m = re.search(r"Demographic\s*\n[^\n]*\n([^\n]+)", text)
    if m and not re.match(r"Ch\*|Attention", m.group(1)):
        d["agency"] = clean(m.group(1))
    m = re.search(r"^(" + MONEY + r")(" + MONEY + r")(\d+)Totals", text, re.M)   # "$28,177.50$33,150.0087Totals ($4,972.50)" -> net, gross, spots (the order summary)
    if m:
        d["net"], d["gross"], d["spots"] = money(m.group(1)), money(m.group(2)), int(m.group(3))
    else:
        tots = re.findall(r"^Totals\s+(\d+)\s+(" + MONEY + ")", text, re.M)        # page/period totals; the last one is the order total
        if tots:
            d["spots"], d["gross"] = int(tots[-1][0]), money(tots[-1][1])
    lines = []
    for lm in LINE_RX.finditer(text):
        lines.append({"line": int(lm.group(1)), "start": iso(lm.group(2)), "end": iso(lm.group(3)), "program": lm.group(4).strip(), "len": int(lm.group(5)),
                      "rate": money(lm.group(7)) if lm.group(7) else None, "spots": int(lm.group(9)), "amount": money(lm.group(10))})
    d["fields"] = {"lines": lines}
    return d


ADDR_PREFIX = re.compile(r"^.*?\b[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s+")          # "Savannah, GA 31405 Jackson/R/Governor"
URL_PREFIX = re.compile(r"^.*?(?:Sales T ?& ?C:?\s*)?\S*graymed\S*\s*", re.I)             # Gray's header carries a URL


def parse_order_ocr(text):
    """WideOrbit CONTRACT print read through OCR (Nexstar, Gray, Fox scans). Tolerant of Vision and tesseract output."""
    d = {}
    head = text[:3000]
    m = (re.search(r"\b(\d{7})\W{0,3}\s*(?:/\s*)?I?WOC", head) or re.search(r"\b(\d{7})\s*[/|]", head)
         or re.search(r"Alt Order\s*#.{0,120}?\b(\d{7})\b", head, re.S) or re.search(r"\b(5\d{6})\b", text[:1500]))
    if m:
        d["order_no"] = m.group(1)
    m = re.search(r"(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", head)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    m = re.search(r"^(.*?)\s+(\d\d/\d\d/\d\d)\W{0,2}\s*[/|=]+\s*(\d\d/\d\d/\d\d)\W*$", head, re.M) or \
        re.search(r"^(.*?)\s+(\d\d/\d\d/\d\d)\W{0,2}\s*\|?\s*$\n\W*(\d\d/\d\d/\d\d)\W*$", head, re.M)
    if m:
        adv = m.group(1)
        adv = URL_PREFIX.sub("", adv)
        adv = ADDR_PREFIX.sub("", adv)
        pol = re.search(r"PO[LU]\s*[/I1l|]?\s*(.*)$", adv)       # Nexstar prefixes political advertisers with POL/
        adv = ("POL/" + pol.group(1)) if pol else re.sub(r"^.*?\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}\s*", "", adv)
        adv = re.sub(r"^\W+", "", adv)
        if not re.search(r"Original Date|Revision|Advertiser$", adv):
            d["advertiser"] = clean(adv)
        d["print_date"] = iso(m.group(3))
    m = re.search(r"^Product\s*\n\W*([^\n]+)", head, re.M)
    if m and not m.group(1).startswith(("And", "Billing")):
        d["product"] = clean(m.group(1))
    m = re.search(r"Estimate #[^\n]*\n[^\n]*?(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)\W*\s+(\S+)\s*$", head, re.M)
    if m:
        d["estimate"] = m.group(3)
    tot = re.search(r"^\W*Totals\s+(?:[\d.]+\W*\s+)?(\d+)\s+[$S]\s?(" + NUM + r")(?:\s+\([$S]?(" + NUM + r")\))?(?:\s+[$S]\s?(" + NUM + "))?", text, re.M)
    best = None
    for tm in re.finditer(r"^\W*Totals\s+(?:[\d.]+\W*\s+)?(\d+)\s+[$S]\s?(" + NUM + r")(?:\s+\([$S]?(" + NUM + r")\))?(?:\s+[$S]\s?(" + NUM + "))?", text, re.M):
        if best is None or (tm.group(4) and not best.group(4)):
            best = tm
    if best:
        d["spots"], d["gross"] = int(best.group(1)), money(best.group(2))
        if best.group(4):
            d["net"] = money(best.group(4))
    d["fields"] = {}
    return d


def parse_order_wo(text):
    """WideOrbit ORDER print, text layer. Page 1 lists labels then a block of values:
    'Original Date / Rev:\\n<order_no>\\n<start> - <end>\\n<orig> / <rev>\\n<advertiser>\\n<agency>'."""
    d = {}
    m = re.search(r"Original Date / Rev:\s*\n(\d{4,9})\s*\n(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)\s*\n(\d\d/\d\d/\d\d) / (\d\d/\d\d/\d\d)\s*\n([^\n]+)\n([^\n]+)", text)
    if m:
        d["order_no"] = m.group(1); d["flight_start"], d["flight_end"] = iso(m.group(2)), iso(m.group(3))
        d["print_date"] = iso(m.group(5)); d["advertiser"] = clean(m.group(6))
        if not re.match(r"Primary AE|Billing|Buying", m.group(7)):
            d["agency"] = clean(m.group(7))
    else:                                                           # Univision variant: every label on its own line, value on the next
        m = re.search(r"Order/Rev:\s*\n(\d{4,9})", text)
        if m:
            d["order_no"] = m.group(1)
        d["agency"] = clean(first(r"Agency Name:\s*\n([^\n]+)", text))
        d["advertiser"] = clean(first(r"Advertiser Name:\s*\n([^\n]+)", text))
        m = re.search(r"Flight Dates:\s*\n?(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)", text)
        if m:
            d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    if not d.get("order_no"):
        d["order_no"] = first(r"Order\s*/\s*Rev:\s*(\d{4,9})", text)
    m = re.search(r"Order\s*/\s*Rev:\s*\d{4,9}\s*/\s*(\d{1,3})\b", text)
    if m:
        d["revision"] = m.group(1)
    d["estimate"] = first(r"Estimate:\s*([^\n]+?)\s*(?:Primary AE:.*)?$", text, re.M)
    m = re.search(r"Estimate:[^\n]*\n([^\n]+)\nFlight Dates:", text)
    if m and m.group(1).strip() not in ("Order",):
        d["product"] = clean(m.group(1))
    if not d.get("print_date"):
        d["print_date"] = iso(first(r"^(\d\d/\d\d/\d\d) \d\d:\d\d:\d\d", text, re.M))
    m = re.search(r"^\$?([\d,]+\.\d\d)(\d+)Totals\s+\$?([\d,]+\.\d\d)", text, re.M)     # "$201,050.0048Totals $170,892.50 0.00"
    if m:
        d["gross"], d["spots"], d["net"] = money(m.group(1)), int(m.group(2)), money(m.group(3))
    m = re.search(r"^Totals\s+(\d+)\s+\$([\d,]+\.\d\d)(?:\s+\$([\d,]+\.\d\d))?", text, re.M)
    if m:
        d.setdefault("spots", int(m.group(1))); d.setdefault("gross", money(m.group(2)))
        if m.group(3):
            d.setdefault("net", money(m.group(3)))
    if d.get("gross") is None:                                      # Univision: "Totals\n66\n$7,175.00\n$6,098.75"
        m = re.search(r"Totals\s*\n(\d+)\s*\n\$([\d,]+\.\d\d)\s*\n\$([\d,]+\.\d\d)", text)
        if m:
            d["spots"], d["gross"], d["net"] = int(m.group(1)), money(m.group(2)), money(m.group(3))
    lines = []
    for lm in re.finditer(r"(?<![\d/$,.])(\d{1,3}) (\d\d/\d\d/\d\d) (\d\d/\d\d/\d\d) (.+?) ?:(\d+) (\d+) \$([\d,]+\.\d\d) (\w+) (\d+) \$([\d,]+\.\d\d)", text, re.M):
        lines.append({"line": int(lm.group(1)), "start": iso(lm.group(2)), "end": iso(lm.group(3)), "program": lm.group(4).strip(),
                      "len": int(lm.group(5)), "rate": money(lm.group(7)), "spots": int(lm.group(9)), "amount": money(lm.group(10))})
    d["fields"] = {"lines": lines}
    return d


def parse_order_wo_ocr(text):
    """WideOrbit ORDER print scanned: labels inline ('Orders Order / Rev: 4431458', 'Flight Dates: 06/08/26 - 06/21/26')."""
    d = {}
    head = text[:4000]
    d["order_no"] = first(r"Order\s*/\s*Rev:\s*(\d{4,9})", head)
    d["revision"] = first(r"Order\s*/\s*Rev:\s*\d{4,9}\s*/\s*(\d{1,3})\b", head)
    m = re.search(r"Flight Dates:\s*(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", head)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    d["print_date"] = iso(first(r"Original Date\s*/\s*Rev:\s*\d\d/\d\d/\d\d\s*/\s*(\d\d/\d\d/\d\d)", head)) or iso(first(r"Print Date:?\s*(\d\d/\d\d/\d\d)", head))
    d["agency"] = clean(first(r"Agency Name:\s*([^\n]+?)(?:\s{2,}|\s+(?:Buying|Billing|Sales)\b.*)?$", head, re.M))
    d["advertiser"] = clean(first(r"Advertiser Name:\s*([^\n]+?)(?:\s{2,}|\s+(?:Demographic|New Business|Product).*)?$", head, re.M))
    d["estimate"] = first(r"Estimate:\s*(\S+)", head)
    d["product"] = clean(first(r"Product Desc:\s*([^\n]+?)(?:\s{2,}|\s+(?:Estimate|Primary|Sales)\b.*)?$", head, re.M))
    best = None
    for tm in re.finditer(r"^\W*Totals\s+(\d+)\s+[$S]\s?(" + NUM + r")(?:\s+[$S]\s?(" + NUM + r"))?", text, re.M):
        if best is None or (tm.group(3) and not best.group(3)):
            best = tm
    if best:
        d["spots"], d["gross"] = int(best.group(1)), money(best.group(2))
        if best.group(3):
            d["net"] = money(best.group(3))
    d["fields"] = {}
    return d


def parse_order_katz(text):
    """Katz / Sinclair contract: labels inline ('Advertiser: X Market: Y Total $: $8,000.00')."""
    d = {}
    g = lambda rx: first(rx, text[:4000], re.I)
    d["order_no"] = g(r"Contract #\s*(\d+)")
    d["revision"] = g(r"Version[: ]+(\d+)") or g(r"Version:\s*Current State Version\s*(\d+)")
    d["advertiser"] = clean((lambda m: m.group(1) if m else None)(re.search(r"Advertiser:\s*(.{1,80}?)\s+(?:Market|Total|Product):", text[:4000], re.I | re.S)))
    d["agency"] = clean(g(r"Agency:\s*(.+?)\s+Advertiser:"))
    d["product"] = clean(g(r"Product:\s*(.+?)\s+(?:Order Office|Office|Total|Service):"))
    m = re.search(r"Flight:\s*(" + DATE + r")\s*-\s*(" + DATE + ")", text[:4000])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    d["print_date"] = iso(g(r"Changes as of:\s*(\d\d?/\d\d?/\d{4})"))
    d["estimate"] = g(r"CPE:\s*\d+/\d+/(\d+)")
    v = g(r"Total \$:\s*[$S]?\s?(" + NUM + ")")
    d["gross"] = money(v) if v else None
    v = g(r"Total Spots:\s*(\d+)")
    d["spots"] = int(v) if v else None
    d["fields"] = {}
    return d


def parse_order_katz_ecr(text):
    """Katz ECR confirmation contract (text): values are scattered lines; the identifying ones are
    '<start>-<end>Schedule Dates', '<Advertiser> (id)\\n<Agency> (id)\\nAdvertiser\\nAgency', '$600.00 Grand Total:  6'."""
    d = {}
    m = re.search(r"^(.+?) \((\d+)\)\n(.+?) \((\d+)\)\nAdvertiser\nAgency", text, re.M)
    if m:
        d["advertiser"], d["agency"] = clean(m.group(1)), clean(m.group(3))
    else:
        d["advertiser"] = clean(first(r"Advertiser\s+(.+?)\s*\(\d+\)", text))
        d["agency"] = clean(first(r"Agency\s+(.+?)\s*\(\d+\)", text))
    m = re.search(r"(\d\d/\d\d/\d\d)-(\d\d/\d\d/\d\d)\s*Schedule Dates", text) or re.search(r"Schedule Dates\s*(\d\d/\d\d/\d\d)-(\d\d/\d\d/\d\d)", text)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    d["order_no"] = first(r"Contract #\s*(\d{6,9})", text) or first(r"^(\d{7})\s*$", text, re.M)
    m = re.search(r"\$?(" + NUM + r")\s*Grand Total:?\s*(\d+)", text) or re.search(r"Grand Total:?\s*(\d+)?\s*\$?(" + NUM + ")", text)
    if m:
        a, b = m.group(1), m.group(2)
        if re.fullmatch(NUM, a or ""):
            d["gross"], d["spots"] = money(a), (int(b) if b and b.isdigit() else None)
        else:
            d["gross"], d["spots"] = money(b), (int(a) if a and a.isdigit() else None)
    v = first(r"Net Total\s*\$?(" + NUM + ")", text)
    d["net"] = money(v) if v else None
    d["estimate"] = first(r"\d+/\d+/(\d+) \(\d+\)Brand", text)
    d["print_date"] = iso(first(r"^(\d\d/\d\d/\d\d)\s*\n[^\n]*\nDate Entered", text, re.M))
    d["fields"] = {}
    return d


def parse_order_sinclair_contract(text):
    """Sinclair traffic contract scan: 'Contract # 7115801 Date Entered 09/03/26 Flint (WSMH)', 'Schedule Dates 09/08/26-09/14/26',
    'Advertiser NRSC-Mike Rogers for Senate-R (157573)', '... Grand Total'."""
    d = {}
    d["order_no"] = first(r"Contract #\s*(\d{6,9})", text)
    m = re.search(r"Schedule Dates\s*(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", text)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    d["advertiser"] = clean(first(r"Advertiser\s+(.+?)\s*\(\d{3,}\)", text))
    d["agency"] = clean(first(r"Agency\s+(.+?)\s*\(\d{3,}\)", text))
    d["print_date"] = iso(first(r"Last ?Modified\s*(\d\d?/\d\d?/\d\d)", text)) or iso(first(r"Date ?Entered\s*(\d\d/\d\d/\d\d)", text))
    amounts = [money(x) for x in re.findall(r"[$S]\s?(" + NUM + ")", text)]
    m = re.search(r"Grand Total:?\s*(\d+)?\s*\$?\s*(" + NUM + ")", text) or re.search(r"\$?(" + NUM + r")\s*Grand Total", text)
    if m:
        d["gross"] = money(m.group(m.lastindex))
    elif amounts:
        d["gross"] = max(amounts)                                  # the grand total is the largest figure on the page
        d["fields"] = {"gross_is_max_amount": True}
    d.setdefault("fields", {})
    return d


def parse_order_locality(text):
    """Locality rep 'CONTRACT WORKSHEET REPORT' (OCR): '*** ORIGINAL REV#0 *** 20130722', 'Total $43,200', 'Total Spots 19',
    'APR21/26-APR27/26', 'Agency Name: ...', '<salesperson> ISS/<advertiser> TYPE O'."""
    d = {}
    d["order_no"] = first(r"REV#\s*\w+\s*\*+\s*(\d{7,9})", text) or first(r"\*\*\*[^\n]*\*\*\*\s*(\d{7,9})", text)
    d["revision"] = first(r"REV#\s*([0-9O]+)", text)
    if d["revision"]:
        d["revision"] = d["revision"].replace("O", "0")
    m = re.search(r"([A-Z]{3}\d{1,2}/\d\d)\s*-\s*([A-Z]{3}\d{1,2}/\d\d)", text)
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1).title()), iso(m.group(2).title())
    adv = first(r"^(?:[A-Z][A-Za-z.'-]+\s+){0,3}(?:ISS/|POLI?/|CAND/)?([^\n]+?)\s+TYPE\s+[A-Z0-9]\s*$", text, re.M)
    d["advertiser"] = clean(re.sub(r"^(?:ISS|POLI?|CAND)/", "", adv)) if adv else None
    d["agency"] = clean(first(r"Agency Name:\s*([^\n]+)", text))
    v = first(r"CONTRACT TOTAL\s*\$?\s*(\d[\d,]*(?:\.\d\d)?)", text) or first(r"^Total\s*\$\s*(\d[\d,]*(?:\.\d\d)?)", text, re.M)
    d["gross"] = money(v if "." in (v or "") else (v + ".00" if v else None))
    v = first(r"TOTAL SPOTS\s*(\d+)", text, re.I)
    d["spots"] = int(v) if v else None
    d["estimate"] = first(r"\bEST#?\s*=?\s*(\d+)", text)
    d["print_date"] = iso(first(r"RUN ON\s*([A-Za-z]{3}\d{1,2}/\d{4})", text).replace("/", " ", 1).title() + "") if first(r"RUN ON\s*([A-Za-z]{3}\d{1,2}/\d{4})", text) else None
    d["fields"] = {}
    return d


def parse_order_eport(text, file_name=""):
    """Sinclair ePort order/revision summary: 'Agency: X Station: KDSM-TV Flight Start: .. Client: 275 - Name .. Airtime Dollars: $4,605.00'."""
    d = {}
    g = lambda rx: first(rx, text[:4000], re.I | re.S)
    d["order_no"] = g(r"Order(?: Number| #|#)?:?\s*(\d{7,9})\b") or first(r"\b(\d{8})\b", file_name)
    d["revision"] = g(r"Version\s+(\d+)")
    d["agency"] = clean(g(r"Agency:\s*(.+?)\s+Station:"))
    d["advertiser"] = clean(g(r"Client:\s*(?:\d+\s*-\s*)?(.+?)\s+(?:Cancel Date|Hiatus|Flight|Product):"))
    d["product"] = clean(g(r"Product:\s*(?:\d+\s*-\s*)?([^\n]+?)\s+(?:Piggyback|Estimate|Received)"))
    d["flight_start"] = iso(g(r"Flight Start:\s*(\d\d/\d\d/\d{4})"))
    d["flight_end"] = iso(g(r"Flight End:\s*(\d\d/\d\d/\d{4})"))
    d["print_date"] = iso(g(r"Received in ePort:\s*(\d\d?/\d\d?/\d{4})"))
    v = g(r"Airtime Dollars:\s*[$S]?\s?(" + NUM + ")")
    d["gross"] = money(v) if v else None
    d["fields"] = {}
    return d


# ----------------------------------------------------------------------------------------------- invoices
def parse_invoice_sinclair(text, file_name="", source="text"):
    """Sinclair 'OFFICIAL BILLING INVOICE'. In the text-layer version the header values (advertiser, invoice and
    contract numbers, period) are not in the text layer, so they come from the file name ('Rob Sand, invoice #11747281');
    OCR'd copies carry them as 'Invoice 11856120', 'Advertiser X (id)', 'Contract 7115801', 'Period 9/7/2026 - 9/13/2026'."""
    d = {}
    m = re.search(r"invoice\s*#\s*(\d+)", file_name, re.I)
    if m:
        d["invoice_no"] = m.group(1)
    m = re.match(r"\s*(.+?),\s*invoice", file_name, re.I)
    if m:
        d["advertiser"] = clean(m.group(1))
    if not d.get("invoice_no"):
        d["invoice_no"] = first(r"Invoice\s*#?\s*(\d{7,9})\b", text[:3000])
    if not d.get("advertiser"):
        d["advertiser"] = clean(first(r"Advertiser\s+(.+?)\s*\(\d{3,}\)", text[:3000]))
    d["agency"] = clean(first(r"Agency\s+(.+?)\s*\(\d{3,}\)", text[:3000]))
    d["order_no"] = first(r"[Cc]ontract\s+(\d{7,9})\b", text[:3000])
    m = re.search(r"Period\s*(" + DATE + r")\s*-\s*(" + DATE + ")", text[:3000])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
    m = re.search(r"\$([\d,]+\.\d\d)\n\$[\d,]+\.\d\d\(\$[\d,]+\.\d\d\)\n\$([\d,]+\.\d\d)\nGross Total", text)
    if m:
        d["gross"], d["net"] = money(m.group(1)), money(m.group(2))
    else:
        m = re.search(r"Gross Total[^\n$]*[$S]\s?(" + NUM + r")(?:[^\n$]*[$S]\s?(" + NUM + r"))?(?:[^\n$]*[$S]\s?(" + NUM + "))?", text)
        if m:
            d["gross"] = money(m.group(1))
            if m.group(3):
                d["net"] = money(m.group(3))
    spots = re.findall(r"(\d\d/\d\d/\d\d)\s+(\d{1,2}:\d\d\s?[AP]M).*?SPOT(?: M/G For [\d.]+)?([A-Z0-9]{6,16})\s*$", text, re.M)
    if not spots and source == "ocr":
        spots = re.findall(r"\W(\d\d/\d\d/\d\d)\s+(\d{1,2}:\d\d\s?[AP]M)\s+\(\w\w\)\s+.*?\s(\w*[A-Z]{2,}\w*\d\w*)\b", text)
    d["spots"] = len(spots) or None
    d["ad_ids"] = sorted({s[2] for s in spots})
    d["fields"] = {"aired": [{"date": iso(a), "time": t, "ad_id": c} for a, t, c in spots]}
    return d


def parse_invoice(text):
    d = {}
    m = re.search(r"Order\s*#\s*(\d+)", text)
    if m:
        d["order_no"] = m.group(1)
    m = re.search(r"(\d\d/\d\d/\d\d) - (\d\d/\d\d/\d\d)\s*\n([^\n]+)\n([^\n]+)", text[:1500])
    if m:
        d["flight_start"], d["flight_end"] = iso(m.group(1)), iso(m.group(2))
        d["advertiser"] = clean(m.group(3))
        if not re.match(r"Property|Billing|Sales", m.group(4)):
            d["agency"] = clean(m.group(4))
    m = re.search(r"^Product\s*\n(?:Estimate # \d+\s*\n)?(.+)$", text[:1500], re.M)
    if m and not m.group(1).startswith("Estimate"):
        d["product"] = clean(m.group(1))
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
    spots = re.findall(r"(\d\d/\d\d/\d\d) (\d{1,2}:\d\d [AP]M) ([A-Za-z0-9]{6,16})\b", text)
    d["ad_ids"] = sorted({s[2] for s in spots})
    d["fields"] = {"aired": [{"date": iso(a), "time": t, "ad_id": c} for a, t, c in spots]}
    return d


# ----------------------------------------------------------------------------------------------- forms
FORM_MAP = [  # (our key, regex over AcroForm field name)
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


def _after_label(text, label_rx, maxskip=2):
    """Value on the same line after a label, else the first non-empty line below it (skipping label-like lines)."""
    m = re.search(label_rx + r"[ \t]*([^\n]*)\n((?:[^\n]*\n){0,%d})" % maxskip, text, re.I)
    if not m:
        return None
    same = m.group(1).strip(" :.")
    if same and not re.fullmatch(r"[\W_]*|N/?A", same):
        return same
    for ln in m.group(2).split("\n"):
        ln = ln.strip(" :.|")
        if ln and not re.fullmatch(r"[\W_]*", ln) and not re.search(r":\s*$", ln) and not re.match(r"(?:ALL QUESTIONS|The undersigned|Check one)", ln, re.I):
            return ln
    return None


def parse_form_text(text):
    """NAB PB-19 / station agreement forms read from page text or OCR. Labels are stable across the 2020 and 2024 NAB
    versions, Graham's 'SUPPLEMENT TO ORDER', NBC's 'POLITICAL INQUIRY RECORD' and Fox's disclosure form; values follow
    the label on the same or the next line. Checkboxes are not readable from OCR, so 'level' comes from the office text."""
    out = {}
    g = lambda rx, skip=2: _after_label(text, rx, skip)
    v = first(r"^\W{0,3}\s*(.{2,80}?)\s*,?\s*hereby request", text, re.I | re.M)
    if v:
        out["requested_by"] = clean(re.sub(r"^[\W_]+", "", v))
    out["candidate"] = g(r"Candidate(?:'s)? name:") or g(r"THE NAME OF THE CANDIDATE IS:?", 1)
    out["referenced_candidate"] = g(r"Name\(s\) of (?:every )?candidate[^\n:]*:", 1)
    out["committee"] = g(r"CANDIDATE'S AUTHORIZED COMMITTEE IS:?") or g(r"Authorized committee:")
    out["agency"] = g(r"Agency requesting time[^\n:]*:?") or g(r"Agency name:?", 1)
    out["party"] = g(r"Candidate(?:'s)? political party:?")
    out["office"] = g(r"Office sought[^\n:]*:?") or g(r"SEEKS ELECTION TO THE OFFICE OF:?")
    out["election_date"] = g(r"Date of (?:the )?election:?", 2)
    out["treasurer"] = g(r"Treasurer of (?:the )?candidate's authorized committee:?") or g(r"THE TREASURER OF THE AUTHORIZED COMMITTEE IS:?")
    out["sponsor"] = (g(r"Name of advertiser/sponsor[^\n]*(?:\n[^\n]*){0,2}?\n\s*Name:?", 1) or g(r"THE sponsor IS:?", 1)
                      or g(r"Name of (?:Advertiser|Sponsor|entity)[^\n:]*:?", 1) or g(r"Advertiser/Sponsor:?", 1))
    out["issue"] = g(r"(?:Clearly identify|Issues? mentioned|Describe the issue)[^\n]*(?:\n[^\n]*){0,1}?:", 2)
    out["order_no"] = first(r"ORDER NO\.?\s*:?\s*(\d{5,9})", text, re.I)
    for k, v in list(out.items()):
        if v is not None:
            v = re.sub(r"^(?:(?:\[.{0,3}\]|LC\]|L\]|CL\]|N/A|ii|i|\|)\s*)+", "", v)                      # leading checkbox debris / N/A box
            v = re.sub(r"\s*(?:\[.{0,3}\]|LC\]|L\]|\(\s*\)).*$", "", v).strip(" :;|_.,")           # trailing checkbox debris
            if k in ("agency", "committee", "sponsor", "candidate", "treasurer"):
                v = re.sub(r"\s+\d{2,6}\s+[A-Z][\w.]*\s.*$", "", v)                                     # a street address glued on
                v = re.sub(r"\s*(?:\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}|\S+@\S+).*$", "", v)              # phone / email
            if re.fullmatch(r"(?i)is|are|n/?a|none|see attached", v.strip()):
                v = ""
            out[k] = v.strip() or None
    if out.get("candidate") and re.search(r"IDENTIFY CANDIDATE|FEDERAL CANDIDATE", out["candidate"], re.I):
        out["candidate"] = None
    if out.get("requested_by") and not out.get("agency"):
        out["agency"] = out["requested_by"]
    for k in ("candidate", "committee", "sponsor", "agency", "party", "office", "treasurer"):
        if out.get(k) and (len(out[k]) > 90 or re.search(r"represents that|undersigned|request station time", out[k], re.I)):
            out[k] = None
    level = None
    office = (out.get("office") or "") + " " + (out.get("candidate") or "")
    if re.search(r"Congress|Senate|United States|U\.?S\.?|President|Federal", office, re.I):
        level = "federal"
    elif out.get("office"):
        level = "state/local"
    d = {"advertiser": out.get("committee") or out.get("candidate") or out.get("sponsor"), "agency": out.get("agency"),
         "fields": {"form": {k: v for k, v in out.items() if v}, "level": level}}
    if out.get("election_date"):
        ed = out["election_date"]
        m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", ed) or re.search(r"\b([A-Z][a-z]+ \d{1,2}\s*,?\s*\d{4})\b", ed)
        d["flight_end"] = iso(m.group(1)) if m else None
    if out.get("order_no"):
        d["order_no"] = out["order_no"]
    return d


# ----------------------------------------------------------------------------------------------- driver
def parse_text(text, fields, source, file_name=""):
    kind, template = classify(text, fields, source)
    if kind == "order":
        d = {"wideorbit-contract": parse_order, "wideorbit-contract-ocr": parse_order_ocr, "wideorbit-order": parse_order_wo,
             "wideorbit-order-ocr": parse_order_wo_ocr, "katz": parse_order_katz, "katz-ecr": parse_order_katz_ecr,
             "sinclair-contract": parse_order_sinclair_contract, "locality-worksheet": parse_order_locality}.get(template)
        d = parse_order_eport(text, file_name) if template == "eport" else d(text)
        if template == "wideorbit-contract" and d.get("gross") is None and d.get("order_no") is None:
            d = parse_order_ocr(text)                              # a text-layer PDF that is really a flattened scan
        if not d.get("order_no") and source == "ocr":
            m = re.search(r"(?<!\d)(\d{7,8})(?!\d)", file_name or "")   # stations name scanned orders by order number
            if m:
                d["order_no"] = m.group(1); d.setdefault("fields", {})["order_no_from_filename"] = True
    elif kind == "invoice":
        d = parse_invoice_sinclair(text, file_name, source) if template == "sinclair-invoice" else parse_invoice(text)
    elif kind == "form":
        d = parse_form(text, fields) if template == "nab-acroform" else parse_form_text(text)
    else:
        d = {"fields": {}}
    d["kind"], d["template"] = kind, template
    return d


def parse_file(path, file_name="", fid=None, use_cache=True):
    text, fields, pages, source, portfolio = read(path, fid, use_cache)
    d = parse_text(text, fields, source, file_name)
    f = d.setdefault("fields", {})
    f["source"] = source; f["pages"] = pages; f["chars"] = len(text)
    if portfolio:
        f["portfolio"] = True
    if source == "none":
        f["needs_ocr"] = True
    if d.get("estimate"):
        f["estimate"] = d.pop("estimate")
    kind = d["kind"]
    need = {"order": ("order_no", "gross"), "invoice": ("order_no", "gross"), "form": ("advertiser",), "other": ()}[kind]
    if d.get("template") == "sinclair-invoice" and not d.get("order_no"):
        need = ("invoice_no", "gross")                    # Katz-contract Sinclair stations: invoices carry no linkable order number
    missing = [k for k in need if d.get(k) is None]
    d["parse_status"] = "ok" if not missing else ("partial" if len(missing) < len(need) else "failed")
    if kind == "other":
        if source == "none":
            d["parse_status"] = "failed"                  # nothing could be read yet: OCR pending
        elif d.get("template") is None:
            d["parse_status"] = "unrecognized"            # readable text, but no known layout: never counted as ok
    return d


def _work(job):
    fid, path, file_name, use_cache = job
    try:
        d = parse_file(os.path.join(ROOT, path), file_name or "", fid, use_cache)
        d["error"] = None
    except Exception as e:
        d = {"kind": "other", "template": None, "parse_status": "failed", "fields": {"error": f"{type(e).__name__}: {str(e)[:200]}"}, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    d["fid"] = fid
    return d


def store(con, d):
    con.execute("""INSERT OR REPLACE INTO docs(file_manager_id,kind,parse_status,order_no,revision,invoice_no,advertiser,agency,product,
                   flight_start,flight_end,print_date,gross,net,spots,ad_ids,fields,parser_version,parsed_at,error)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d["fid"], d["kind"], d["parse_status"], d.get("order_no"), d.get("revision"), d.get("invoice_no"),
                 d.get("advertiser"), d.get("agency"), d.get("product"), d.get("flight_start"), d.get("flight_end"), d.get("print_date"),
                 d.get("gross"), d.get("net"), d.get("spots"), json.dumps(d.get("ad_ids") or []),
                 json.dumps({**(d.get("fields") or {}), "template": d.get("template")}, default=str), PARSER_VERSION,
                 _dt.datetime.now().isoformat(timespec="seconds"), d.get("error")))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--ids", help="comma-separated file ids")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    ap.add_argument("--reparse", action="store_true", help="every downloaded document (from the text cache)")
    ap.add_argument("--only-failed", action="store_true", help="documents that are not parse_status=ok or are kind=other, and have text or OCR available")
    ap.add_argument("--stations", help="restrict to these facility ids")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    ap.add_argument("--no-cache", action="store_true", help="re-extract text from the PDFs instead of data/text")
    ap.add_argument("--max-fail-rate", type=float, default=0.01, help="parser crashes (not failed parses) allowed")
    a = ap.parse_args(argv)
    if a.file:
        d = parse_file(a.file, os.path.splitext(os.path.basename(a.file))[0], None, use_cache=False)
        f = d.pop("fields", {})
        d["ad_ids"] = len(d.get("ad_ids") or [])
        d["n_lines"] = len(f.get("lines") or f.get("aired") or [])
        d["lines_sum"] = round(sum(l["amount"] or 0 for l in f.get("lines") or []), 2) if f.get("lines") else None
        d["form"] = f.get("form"); d["level"] = f.get("level"); d["source"] = f.get("source"); d["pages"] = f.get("pages"); d["estimate"] = f.get("estimate")
        print(json.dumps(d, indent=1, default=str))
        return
    with Stage("parse", args=vars(a), db_path=a.db, max_fail_rate=a.max_fail_rate) as st:
        con = db.connect(a.db)
        q = "SELECT file_manager_id, local_path, file_name FROM files WHERE downloaded=1 AND deleted=0"
        params = []
        if a.ids:
            ids = a.ids.split(","); q += f" AND file_manager_id IN ({','.join('?'*len(ids))})"; params += ids
        elif a.only_failed:
            q += """ AND file_manager_id IN (SELECT d.file_manager_id FROM docs d LEFT JOIN ocr o USING(file_manager_id)
                     WHERE ((d.parse_status!='ok' OR d.kind='other' OR d.parser_version<%d)
                            AND (json_extract(d.fields,'$.needs_ocr') IS NULL OR o.status='ok'))
                        OR (o.status='ok' AND o.ocr_at > COALESCE(d.parsed_at, '')))""" % PARSER_VERSION
        elif not a.reparse:
            q += " AND file_manager_id NOT IN (SELECT file_manager_id FROM docs WHERE parser_version=%d AND json_extract(fields,'$.needs_ocr') IS NULL)" % PARSER_VERSION
            q += " AND file_manager_id NOT IN (SELECT d.file_manager_id FROM docs d LEFT JOIN ocr o USING(file_manager_id) WHERE d.parser_version=%d AND json_extract(d.fields,'$.needs_ocr')=1 AND o.status IS DISTINCT FROM 'ok')" % PARSER_VERSION
        if a.stations:
            facs = [int(x) for x in a.stations.split(",")]; q += f" AND facility_id IN ({','.join('?'*len(facs))})"; params += facs
        rows = con.execute(q, params).fetchall()
        log.info("parsing %d files with %d workers (cache %s)", len(rows), a.workers, "off" if a.no_cache else "on")
        st.count("queued", len(rows))
        jobs = [(r["file_manager_id"], r["local_path"], r["file_name"], not a.no_cache) for r in rows]
        stats, crashes, needs_ocr = {}, 0, 0
        with ProcessPoolExecutor(a.workers) as ex:
            for i, d in enumerate(ex.map(_work, jobs, chunksize=16), 1):
                st.attempt()
                key = (d["kind"], d.get("template") or "-", d["parse_status"])
                stats[key] = stats.get(key, 0) + 1
                if d.get("error"):
                    crashes += 1; st.fail(d["fid"], f"parser crash: {d['error']}")
                if (d.get("fields") or {}).get("needs_ocr"):
                    needs_ocr += 1
                store(con, d)
                if i % 500 == 0:
                    con.commit()
                st.progress(i, len(rows), every=2000, label="parse")
        con.commit()
        for (k, t, s), v in sorted(stats.items(), key=lambda x: -x[1]):
            log.info("  %-8s %-24s %-8s %6d", k, t, s, v)
            st.count(f"{k}/{t}/{s}", v)
        ok = sum(v for (k, t, s), v in stats.items() if s == "ok")
        st.count("ok", ok); st.count("crashes", crashes); st.count("needs_ocr", needs_ocr)
        log.info("  ok %d of %d (%.1f%%); %d need OCR; %d parser crashes", ok, len(rows), 100.0 * ok / max(1, len(rows)), needs_ocr, crashes)
        con.close()


if __name__ == "__main__":
    main()

"""Newscast blocks: which political spots are booked into, and confirmed aired in, each station's news programs.

    python3 -m ingest.newscasts            # writes web/data/newscasts/<facility>.json for every station with news buys
    python3 -m ingest.newscasts --test     # classifier on sample program strings

Order lines name the program and its clock window ("Action News at 6p 6p-7p", "M-F Late News 11:00 PM-11:35 PM",
"M-F News CH8 @ 430-5A 430-5A"); each line is one week of a flight with that week's spot count. That is enough to
say what is scheduled into tonight's news. Invoices confirm what aired, with a time per spot but no program name,
a median 17 days after the air date; those spots are placed into the same blocks by air time. The app shows the
schedule for tonight and last night and swaps in confirmed airings for nights the invoices have reached.
"""
import argparse, collections, datetime as dt, json, logging, os, re, sys
from . import db
from .export import WEB, slug, CAT_LABEL
from .runlog import Stage

log = logging.getLogger("ingest")

NEWS = re.compile(r"news|nightbeat|nightline|newschannel|eyewitness", re.I)
NETWORK = re.compile(r"nightly news|evening news|world news|nightline|news daily|cbs mornings|good morning america|today show|\bgma\b|cbs morning news|morning news(?!.*(?:at|@)\s*\d)", re.I)
# "6p-7p", "11:00 PM-11:35 PM", "530a-6a", "6-7A", "430-5A", "10-1035P", "630-7p", "12:30-1PM", "12:35 XM-1:00 XM"
WINDOW = re.compile(r"(\d{1,2})(?::(\d\d)|(\d\d))?\s*([apx])?m?\s*-\s*(\d{1,2})(?::(\d\d)|(\d\d))?\s*([apx])m?", re.I)
DAYS = [("M-F", [0, 1, 2, 3, 4]), ("MTWTF", [0, 1, 2, 3, 4]), ("M-SU", list(range(7))), ("M-SUN", list(range(7))), ("MO-SU", list(range(7))),
        ("M-SA", list(range(6))), ("SA-SU", [5, 6]), ("SAT-SUN", [5, 6]), ("SAT", [5]), ("SUN", [6]), ("SA", [5]), ("SU", [6]), ("M-TH", [0, 1, 2, 3]), ("T-F", [1, 2, 3, 4])]
MASK = re.compile(r"([M1-][T1-][W1-][T1-][F1-][S1-][S1-])(?![A-Za-z0-9])")   # "---T---", "-----S-", "MTWTF--" (often glued to the window)


def minutes(h, mm, mer, fallback_mer):
    h = int(h); mm = int(mm or 0)
    mer = (mer or fallback_mer or "").lower()
    if mer == "p" and h != 12:
        h += 12
    elif mer == "a" and h == 12:
        h = 0
    elif mer == "x":                      # "XM": past midnight on some WideOrbit layouts
        h = h % 12
    return h * 60 + mm


def window(s):
    """Last 'start-end' clock window in a program string -> (start_min, end_min) or None."""
    best = None
    for m in WINDOW.finditer(s):
        h1, m1a, m1b, mer1, h2, m2a, m2b, mer2 = m.groups()
        # "530a": the regex read h=5, mm=30 via the no-colon branch; "1035P" -> 10:35
        if m1b is None and m1a is None and len(h1) > 2:
            h1, m1b = h1[:-2], h1[-2:]
        if m2b is None and m2a is None and len(h2) > 2:
            h2, m2b = h2[:-2], h2[-2:]
        try:
            start = minutes(h1, m1a or m1b, mer1, mer2)
            end = minutes(h2, m2a or m2b, mer2, mer1)
        except ValueError:
            continue
        if not mer1 and mer2 and start > end and (mer2.lower() == "p") and int(h1) < 12:
            start = minutes(h1, m1a or m1b, "a", None)   # "11-1p" style: morning start
            if start > end:
                start = minutes(h1, m1a or m1b, "p", None)
        if end <= start:
            end += 24 * 60
        if 0 <= start < 24 * 60 and end - start <= 6 * 60:
            best = (start, end)
    return best


def days(s):
    """Weekdays a line runs (Mon=0) from a day token or a 7-char mask; None when the string says nothing."""
    m = MASK.search(s)
    if m and "-" in m.group(1):
        return [i for i, ch in enumerate(m.group(1)) if ch != "-"] or None
    u = re.sub(r"[^A-Z-]", " ", s.upper())
    for tok, d in DAYS:
        if re.search(r"(?<![A-Z])" + re.escape(tok) + r"(?![A-Z])", u):
            return d
    return None


def label(start):
    return "Late" if start < 4 * 60 else "Morning" if start < 9 * 60 else "Midday" if start < 15 * 60 + 30 else "Evening" if start < 19 * 60 + 30 else "Late"


def classify(program):
    """-> {start, end, label, days, network} for a newscast line, else None."""
    if not program or not NEWS.search(program):
        return None
    w = window(program)
    if not w:
        return None
    return {"start": w[0], "end": w[1], "label": label(w[0]), "days": days(program), "network": bool(NETWORK.search(program))}


def clock(mins):
    mins %= 24 * 60
    h, m = divmod(mins, 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def spot_minutes(t):
    m = re.match(r"\s*(\d{1,2}):(\d\d)\s*([AP])M", t or "", re.I)
    return minutes(m.group(1), m.group(2), m.group(3), None) if m else None


def export_newscasts(con, since_days=60, ahead_days=60):
    out_dir = os.path.join(WEB, "newscasts"); os.makedirs(out_dir, exist_ok=True)
    today = dt.date.today()
    st = {r[0]: {"fac": r[0], "call": r[1], "city": r[2], "state": r[3]} for r in con.execute("SELECT facility_id, call, city, state FROM station")}
    buyers = {r[0]: {"name": r[1], "slug": slug(r[2], r[1]), "category": CAT_LABEL.get(r[2], r[2]), "party": r[3], "office": r[4]}
              for r in con.execute("SELECT buyer_id, canonical_name, category, party, office FROM buyer")}
    per = collections.defaultdict(lambda: {"blocks": {}, "lines": [], "confirmed": []})
    seen = unmatched = 0
    for fac, bid, program, start, end, spots, length, amount in con.execute(
            """SELECT o.facility_id, o.buyer_id, l.program, l.start_date, l.end_date, l.spots, l.length_sec, l.amount
               FROM order_line l JOIN order_ o USING (order_id)
               WHERE l.program ILIKE '%%news%%' AND l.end_date >= %s AND l.start_date <= %s AND l.spots > 0""",
            (today - dt.timedelta(days=since_days), today + dt.timedelta(days=ahead_days))):
        c = classify(program); seen += 1
        if not c or fac not in st:
            unmatched += 1; continue
        p = per[fac]
        key = (c["start"], c["end"])
        b = p["blocks"].setdefault(key, {"start": c["start"], "end": c["end"], "label": c["label"], "network": c["network"], "name": program, "days": set()})
        if c["days"]:
            b["days"].update(c["days"])
        p["lines"].append({"b": key, "buyer": bid, "start": str(start), "end": str(end), "days": c["days"], "spots": spots, "len": length, "amount": float(amount or 0)})
    # confirmed airings: spots with a time inside one of the station's news windows
    for fac, bid, day, t, ad in con.execute("SELECT facility_id, buyer_id, aired_on, aired_time, ad_id FROM spot WHERE aired_on >= %s", (today - dt.timedelta(days=since_days),)):
        p = per.get(fac)
        if not p:
            continue
        mins = spot_minutes(t)
        if mins is None:
            continue
        hit = next((k for k, b in p["blocks"].items() if b["start"] <= mins < b["end"] or b["start"] <= mins + 1440 < b["end"]), None)
        if hit is None:
            continue
        p["confirmed"].append({"b": hit, "buyer": bid, "d": str(day), "t": mins, "ad_id": ad})
    n = 0
    for fac, p in per.items():
        keys = sorted(p["blocks"], key=lambda k: (k[0], k[1]))
        idx = {k: i for i, k in enumerate(keys)}
        blocks = [{"id": f"{k[0]}-{k[1]}", "label": p["blocks"][k]["label"], "start": k[0], "end": k[1], "time": f"{clock(k[0])}–{clock(k[1])}",
                   "network": p["blocks"][k]["network"], "name": p["blocks"][k]["name"], "days": sorted(p["blocks"][k]["days"]) or None} for k in keys]
        bu = {}
        def buyer_ref(bid):
            if bid not in bu:
                b = buyers.get(bid) or {"name": "unknown", "slug": None, "category": "Other", "party": None, "office": None}
                bu[bid] = {"id": bid, **b}
            return bid
        lines = [{**l, "b": idx[l["b"]], "buyer": buyer_ref(l["buyer"])} for l in p["lines"]]
        confirmed = sorted(({**c, "b": idx[c["b"]], "buyer": buyer_ref(c["buyer"])} for c in p["confirmed"]), key=lambda c: (c["d"], c["t"]))
        out = {**st[fac], "generated": str(today), "blocks": blocks, "buyers": {str(k): v for k, v in bu.items()}, "lines": lines, "confirmed": confirmed,
               "confirmed_through": max((c["d"] for c in confirmed), default=None)}
        json.dump(out, open(os.path.join(out_dir, f"{fac}.json"), "w"), separators=(",", ":")); n += 1
    json.dump({"generated": str(today), "facs": sorted(per), "since_days": since_days}, open(os.path.join(out_dir, "index.json"), "w"))
    log.info(f"  newscasts/: {n} stations; {seen} news lines, {unmatched} without a parsable window")
    return n


TESTS = ["CH2 Action News at 6p6p-7p", "M-F Late News 11:00 PM-11:35 PM", "M-F News CH8 @ 430-5A 430-5A", "M-Sun News CH8 10-1035P M-Su 10-1035P",
         "CH2 News Nightbeat at 11p11p-1135p", "45 News Noon 12p-1p---T---", "WRAL SAT 6pm News 6-630p", "NBC NIGHTLY NEWS630-7p",
         "NBC Nightly News - Su 6:30 PM-7:00 PM", "M-F Local News 4p-5p4:30 PM-5:00 PM", "ABC News Nightline 12:35 XM-1:00 XM", "The Price is Right Various", "Local News @ 6a M-F 6-7a"]


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--test", action="store_true"); a = ap.parse_args(argv)
    if a.test:
        for t in TESTS:
            c = classify(t)
            print(f"{t!r:55} -> {c and (clock(c['start']) + '-' + clock(c['end']), c['label'], c['days'], 'network' if c['network'] else 'local')}")
        return
    with Stage("newscasts") as st:
        con = db.connect()
        st.count("stations", export_newscasts(con))


if __name__ == "__main__":
    main()

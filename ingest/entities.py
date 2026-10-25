#!/usr/bin/env python3
"""Rebuild domain entities from `document.raw` + `opif_file.folder_path`.

Deterministic and total: it truncates the entity tables and rebuilds them, so a parser
improvement or an alias change only needs `load_pg` + `entities`, never a recrawl.
Manual buyer merges live in data/buyer_overrides.yaml (alias -> canonical name) and are
applied on top of the automatic folder-based identity.
  python3 -m ingest.entities
"""
import collections, datetime, json, logging, os, re, sys
from . import pg
from .runlog import Stage
log = logging.getLogger('ingest.entities')
from .aggregate import split_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATEGORY = {"Federal": "federal", "State": "state", "Local": "local", "Non-Candidate Issue Ads": "issue"}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).strip(" -_.,")


def load_overrides():
    """data/buyer_overrides.yaml: lines of `alias: Canonical Name` (flat; no YAML parser needed)."""
    path = os.path.join(ROOT, "data", "buyer_overrides.yaml")
    out = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.split("#", 1)[0].rstrip()
            if ":" in line:
                a, c = line.split(":", 1)
                out[norm(a).lower()] = norm(c)
    return out


def load_identity():
    path = os.path.join(ROOT, "data", "buyer_identity.json")
    return json.load(open(path)) if os.path.exists(path) else {"aliases": {}, "buyers": {}}


def main():
    with Stage('entities') as st:
        build(st)


def build(st):
    overrides = load_overrides()
    identity = load_identity()
    with pg.connect() as con, con.cursor() as cur:
        cur.execute("TRUNCATE spot, invoice, order_line, order_revision, order_, form, buyer_alias, buyer, agency, creative RESTART IDENTITY CASCADE")
        rows = cur.execute("""SELECT f.file_id, f.facility_id, f.folder_path, f.fcc_created_at, d.kind, d.template, d.raw
                              FROM opif_file f JOIN document d USING (file_id) WHERE f.deleted_at IS NULL""").fetchall()
        log.info(f"documents: {len(rows)}")

        # ---- buyers: identity = (category, station's folder label), with overrides
        buyer_ids, alias_rows = {}, {}
        def buyer_for(facility_id, folder_path, advertiser=None):
            cat_label, leaf = split_path(folder_path)
            cat = CATEGORY.get(cat_label, "other")
            name = norm(leaf) or norm(advertiser) or "Unknown"
            ident = identity["aliases"].get(f"{cat}|{name.lower()}")
            canon = overrides.get(name.lower()) or (ident["name"] if ident else name)
            key = (canon.lower(), cat)
            if key not in buyer_ids:
                cur.execute("INSERT INTO buyer(canonical_name, category) VALUES (%s,%s) ON CONFLICT (canonical_name, category) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING buyer_id", (canon, cat))
                buyer_ids[key] = cur.fetchone()[0]
            bid = buyer_ids[key]
            for alias, src in ((name, "folder"), (norm(advertiser), "advertiser")):
                if alias and (alias.lower(), facility_id) not in alias_rows:
                    alias_rows[(alias.lower(), facility_id)] = (alias, facility_id, bid, src)
            return bid

        agency_ids = {}
        def agency_for(name):
            name = norm(name)
            if not name:
                return None
            k = name.lower()
            if k not in agency_ids:
                cur.execute("INSERT INTO agency(name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING agency_id", (name,))
                agency_ids[k] = cur.fetchone()[0]
            return agency_ids[k]

        # ---- orders: group by (facility, order_no); latest revision wins
        orders = collections.defaultdict(list); invoices = []; forms = []
        for r in rows:
            file_id, fac, path, created, kind, template, raw = r
            if kind == "order" and raw.get("order_no") and raw.get("gross") is not None:
                orders[(fac, raw["order_no"])].append((raw.get("print_date") or "", created or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), file_id, path, raw))
            elif kind == "invoice" and raw.get("gross") is not None:
                invoices.append((file_id, fac, path, raw))
            elif kind == "form":
                forms.append((file_id, fac, path, raw))
        order_ids = {}
        n_lines = 0
        for (fac, order_no), revs in orders.items():
            revs.sort(key=lambda x: (x[0], x[1]))
            pd, created, file_id, path, raw = revs[-1]
            bid = buyer_for(fac, path, raw.get("advertiser"))
            status = "cancelled" if (raw.get("gross") or 0) == 0 and not raw.get("spots") else "booked"
            cur.execute("""INSERT INTO order_(facility_id,order_no,buyer_id,agency_id,advertiser_text,product,flight_start,flight_end,status,gross,net,spots,latest_file_id,first_seen,last_seen)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING order_id""",
                        (fac, order_no, bid, agency_for(raw.get("agency")), raw.get("advertiser"), raw.get("product"), raw.get("flight_start"), raw.get("flight_end"),
                         status, raw.get("gross"), raw.get("net"), raw.get("spots"), file_id, revs[0][1], created))
            oid = cur.fetchone()[0]; order_ids[(fac, order_no)] = oid
            cur.executemany("INSERT INTO order_revision(order_id,file_id,print_date,fcc_created_at,gross,net,spots) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            [(oid, rv[2], rv[0] or None, rv[1], rv[4].get("gross"), rv[4].get("net"), rv[4].get("spots")) for rv in revs])
            lines = (raw.get("fields") or {}).get("lines") or []
            if lines:
                cur.executemany("INSERT INTO order_line(order_id,line_no,program,start_date,end_date,spots,length_sec,amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                [(oid, l["line"], l.get("program"), l.get("start"), l.get("end"), l.get("spots"), l.get("len"), l.get("amount")) for l in lines])
                n_lines += len(lines)
        log.info(f"orders: {len(order_ids)}  lines: {n_lines}")

        # ---- invoices and spots
        n_spots = 0
        for file_id, fac, path, raw in invoices:
            bid = buyer_for(fac, path, raw.get("advertiser"))
            oid = order_ids.get((fac, raw.get("order_no")))
            cur.execute("""INSERT INTO invoice(facility_id,invoice_no,order_id,buyer_id,period_start,period_end,gross,net,spots,file_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (facility_id, file_id) DO NOTHING RETURNING invoice_id""",
                        (fac, raw.get("invoice_no"), oid, bid, raw.get("flight_start"), raw.get("flight_end"), raw.get("gross"), raw.get("net"), raw.get("spots"), file_id))
            got = cur.fetchone()
            if not got:
                continue
            aired = (raw.get("fields") or {}).get("aired") or []
            cur.executemany("INSERT INTO spot(invoice_id,facility_id,buyer_id,aired_on,aired_time,ad_id) VALUES (%s,%s,%s,%s,%s,%s)",
                            [(got[0], fac, bid, a["date"], a.get("time"), a.get("ad_id")) for a in aired if a.get("date")])
            n_spots += len(aired)
        log.info(f"invoices: {len(invoices)}  spots: {n_spots}")

        # ---- forms
        for file_id, fac, path, raw in forms:
            fm = (raw.get("fields") or {}).get("form") or {}
            bid = buyer_for(fac, path, fm.get("committee") or fm.get("candidate") or fm.get("sponsor"))
            ed = fm.get("election_date")
            try:
                ed = datetime.datetime.strptime(ed, "%m/%d/%Y").date() if ed and len(ed.split("/")[-1]) == 4 else (datetime.datetime.strptime(ed, "%m/%d/%y").date() if ed else None)
            except ValueError:
                ed = None
            cur.execute("""INSERT INTO form(file_id,facility_id,buyer_id,candidate,committee,office,party,election_date,treasurer,level,issue,sponsor,raw)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (file_id) DO NOTHING""",
                        (file_id, fac, bid, fm.get("candidate"), fm.get("committee"), fm.get("office"), fm.get("party"), ed, fm.get("treasurer"),
                         (raw.get("fields") or {}).get("level"), fm.get("issue"), fm.get("sponsor"), json.dumps(fm)))
            if fm.get("committee"):
                alias_rows.setdefault((norm(fm["committee"]).lower(), fac), (norm(fm["committee"]), fac, bid, "form"))
        log.info(f"forms: {len(forms)}")

        cur.executemany("INSERT INTO buyer_alias(alias,facility_id,buyer_id,source) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", list(alias_rows.values()))
        # buyer enrichment from forms: party/office/kind where a form exists
        cur.execute("""UPDATE buyer b SET party = x.party, office = x.office, kind = 'candidate'
                       FROM (SELECT DISTINCT ON (buyer_id) buyer_id, party, office FROM form WHERE candidate IS NOT NULL ORDER BY buyer_id) x
                       WHERE x.buyer_id = b.buyer_id""")
        cur.execute("UPDATE buyer SET kind='issue' WHERE category='issue' AND kind='unknown'")
        # identity attributes (FEC ids, party, office) and merge counts
        n_id = 0
        for bk, info in identity["buyers"].items():
            cur.execute("""UPDATE buyer SET kind=COALESCE(%s, kind), party=COALESCE(%s, party), office=COALESCE(%s, office), district=%s, state=COALESCE(%s, state),
                           fec_candidate_id=%s, fec_committee_id=%s, fec_committee_name=%s, identity_method=%s, raw_labels=%s
                           WHERE lower(canonical_name)=%s AND category=%s""",
                        (info.get("kind"), info.get("party"), info.get("office"), info.get("district"), info.get("state"), info.get("fec_candidate_id"),
                         info.get("fec_committee_id"), info.get("fec_committee_name"), info.get("method"), len(info.get("labels", [])), info["name"].lower(), info["category"]))
            n_id += cur.rowcount
        log.info(f"identity applied to {n_id} buyers")
        # creatives
        cur.execute("""INSERT INTO creative(ad_id,prefix,buyer_id,first_aired,last_aired,airings)
                       SELECT ad_id, left(ad_id,4), (array_agg(buyer_id ORDER BY aired_on DESC))[1], MIN(aired_on), MAX(aired_on), COUNT(*)
                       FROM spot WHERE ad_id IS NOT NULL GROUP BY ad_id""")
        cur.execute("INSERT INTO meta(key,value) VALUES ('entities_built_at', now()::text) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value")
        con.commit()
        for t in ("buyer", "buyer_alias", "agency", "order_", "order_revision", "order_line", "invoice", "spot", "creative", "form"):
            n = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            st.count(t, n)
            log.info(f"  {t:15s} {n:>8}")
        st.count("documents", len(rows))
        if len(rows) and not order_ids:
            raise RuntimeError("no orders were built from %d documents: parser output or load_pg is broken" % len(rows))


if __name__ == "__main__":
    main()

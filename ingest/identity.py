#!/usr/bin/env python3
"""Buyer identity: merge the stations' own folder labels into canonical buyers and match them
to FEC candidates and committees.

Inputs: buyer_alias rows of source 'folder' (one per station label) with the station's state,
FEC bulk master files in data/fec (cn.txt candidates, cm.txt committees, ccl.txt linkage),
and data/buyer_overrides.yaml (manual: `raw label: Canonical Name`, or `category|raw label: ...`).
Output: data/buyer_identity.json, read by ingest.entities on its next run.

  python3 -m ingest.identity          # then: python3 -m ingest.entities
"""
import collections, csv, json, os, re, sys
from rapidfuzz import fuzz, process
from . import pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEC = os.path.join(ROOT, "data", "fec")
OUT = os.path.join(ROOT, "data", "buyer_identity.json")

from .names import STATES, STATE_WORDS, PARTY, OFFICE, GENERIC, NOISE_RX, norm, name_tokens, org_key, title


def load_fec():
    cands, cmtes, by_pcc = [], {}, {}
    with open(os.path.join(FEC, "cn.txt"), encoding="latin-1") as fh:
        for r in csv.reader(fh, delimiter="|"):
            if len(r) < 10 or r[3] != "2026" or r[5] not in ("H", "S", "P"):
                continue
            last, _, first = r[1].partition(",")
            first_words = [w for w in re.sub(r"[^A-Za-z' -]", " ", first).split() if len(w.strip(".")) > 1] or [w for w in first.split() if w]
            cands.append({"id": r[0], "name": r[1], "last": norm(last).split(), "first": norm(first).split(), "party": r[2],
                          "display": title(" ".join((first_words[:1] + [last.strip()]))).replace("'S", "'s"),
                          "state": r[4], "office": {"H": "US House", "S": "US Senate", "P": "President"}[r[5]], "district": r[6],
                          "status": r[8], "pcc": r[9]})
    with open(os.path.join(FEC, "cm.txt"), encoding="latin-1") as fh:
        for r in csv.reader(fh, delimiter="|"):
            if len(r) < 11:
                continue
            cmtes[r[0]] = {"id": r[0], "name": r[1], "norm": norm(r[1]), "type": r[9], "party": r[10], "dsgn": r[8], "cand": r[14] if len(r) > 14 else ""}
    return cands, cmtes


STATE_BY_NAME = {v: k for k, v in STATES.items()}


def state_hints(label):
    """States named in the label ('for Florida', '- SC', 'North Carolina'), as abbreviations."""
    u = norm(label)
    hints = {STATE_BY_NAME[n] for n in STATE_BY_NAME if re.search(r"\b" + n + r"\b", u)}
    hints |= {t for t in u.split() if t in STATES and t not in ("IN", "OR", "ME", "OK", "HI", "DE", "PA", "WA", "LA", "MA", "CO", "ID")}
    hints |= {t for t in u.split() if t in ("PA", "WA", "CO", "LA", "MA", "DE", "ID", "OK") and re.search(r"\b" + t + r"\b(?!\w)", u) and len(u.split()) <= 6}
    return hints


def match_candidate(label, states, cands_by_state):
    toks = name_tokens(label)
    if not toks:
        return None
    hinted = state_hints(label)
    pool_states = hinted or set(states)
    pool = [c for st in pool_states for c in cands_by_state.get(st, [])]
    tokset = set(toks)
    scored = []
    for c in pool:
        cand_toks = [t for t in c["last"] + c["first"] if len(t) > 2]
        overlap = sum(1 for t in cand_toks if t in tokset)
        last_str = " ".join(c["last"])
        last_exact = bool(c["last"]) and all(t in tokset for t in c["last"])
        last_fuzzy = last_exact or any(fuzz.ratio(t, last_str) >= 88 for t in toks if len(t) > 3)
        first_lead = bool(c["first"]) and toks[0] == c["first"][0] and (len(toks) == 1 or fuzz.ratio(toks[1], last_str) >= 70)
        if overlap >= 2 or (last_exact and len(c["last"]) > 1):
            score = 3
        elif last_fuzzy:
            score = 2
        elif first_lead:
            score = 1
        else:
            continue
        score += 0.5 if c["status"] == "C" else 0
        score += 0.2 if any(t in tokset for t in c["first"] if len(t) > 2) else 0
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best_s, best = scored[0]
    top = [c for s_, c in scored if s_ >= best_s - 0.01]
    if len({c["id"] for c in top}) > 1:
        if len({c["name"] for c in top}) == 1:          # same person filed for two offices (e.g. House incumbent running for Senate)
            u = norm(label)
            want = "US Senate" if re.search(r"\b(SENATE|SEN|SENATOR)\b", u) else "US House" if re.search(r"\b(CONGRESS|HOUSE|CD|DISTRICT)\b", u) else None
            pick = [c for c in top if c["office"] == want] or [c for c in top if c["office"] == "US Senate"] or [c for c in top if c["status"] == "C"] or top
            return pick[0]
        return None                      # ambiguous: two different candidates with the same evidence
    return best


def main():
    cands, cmtes = load_fec()
    cands_by_state = collections.defaultdict(list)
    for c in cands:
        cands_by_state[c["state"]].append(c)
    cm_names = {k: v["norm"] for k, v in cmtes.items() if v["norm"]}
    print(f"FEC: {len(cands)} 2026 candidates, {len(cmtes)} committees", file=sys.stderr)

    overrides = {}
    path = os.path.join(ROOT, "data", "buyer_overrides.yaml")
    if os.path.exists(path):
        for line in open(path):
            line = line.split("#", 1)[0].rstrip()
            if ":" in line:
                a, c = line.rsplit(":", 1)
                overrides[a.strip().lower()] = c.strip()

    with pg.connect() as con:
        rows = con.execute("""SELECT b.category, a.alias, array_agg(DISTINCT s.state), COUNT(*) FROM buyer_alias a
                              JOIN buyer b USING (buyer_id) JOIN station s ON s.facility_id = a.facility_id
                              WHERE a.source = 'folder' GROUP BY 1,2""").fetchall()
    print(f"raw labels: {len(rows)}", file=sys.stderr)

    aliases, buyers, stats = {}, {}, collections.Counter()
    for cat, label, states, n in rows:
        key = f"{cat}|{label.lower()}"
        states = [s for s in states if s]
        ident = None
        if label.lower() in overrides or key in overrides:
            ident = {"name": overrides.get(key) or overrides[label.lower()], "method": "manual"}
        elif cat in ("federal", "issue", "other"):
            c = match_candidate(label, states, cands_by_state) if cat == "federal" else None
            if c:
                pcc = cmtes.get(c["pcc"], {})
                ident = {"name": c["display"], "method": "fec-candidate", "kind": "candidate",
                         "party": {"DEM": "Democratic", "REP": "Republican"}.get(c["party"], c["party"]), "office": c["office"],
                         "district": c["district"] if c["office"] == "US House" else None, "state": c["state"],
                         "fec_candidate_id": c["id"], "fec_committee_id": c["pcc"] or None, "fec_committee_name": pcc.get("name")}
            else:
                q = org_key(label)
                hit = process.extractOne(q, cm_names, scorer=fuzz.token_sort_ratio, score_cutoff=93) if q else None
                distinctive = set(name_tokens(label)) & set(name_tokens(cmtes[hit[2]]["name"])) if hit else set()
                if hit and distinctive:
                    cm = cmtes[hit[2]]
                    ident = {"name": title(cm["norm"]), "method": "fec-committee", "kind": "pac" if cm["type"] in ("O", "U", "V", "W", "N", "Q", "I") else "committee",
                             "party": {"DEM": "Democratic", "REP": "Republican"}.get(cm["party"]) if cm["party"] else None,
                             "fec_committee_id": cm["id"], "fec_committee_name": cm["name"]}
        if not ident and cat in ("federal", "state", "local"):
            toks = name_tokens(label)
            if toks:
                ident = {"name": title(" ".join(toks)), "method": "name-rule", "kind": "candidate", "state": states[0] if len(states) == 1 else None}
        if not ident:
            q = org_key(label)
            ident = {"name": title(q) if q else label, "method": "name-rule" if q else "raw", "kind": "issue" if cat == "issue" else "unknown"}
        gk = f"{cat}|" + (ident.get("fec_candidate_id") or ident.get("fec_committee_id") or ident["name"].lower())
        b = buyers.setdefault(gk, {"category": cat, "name": ident["name"], "fec_name": ident["name"] if ident["method"].startswith("fec") else None,
                                   "labels": [], "label_n": [], "method": ident["method"], "renderings": collections.Counter()})
        b["labels"].append(label); b["label_n"].append(n)
        toks = name_tokens(label)
        if ident["method"] == "fec-candidate" and toks:
            b["renderings"][title(" ".join(toks))] += n       # how stations spell the person, weighted by documents
        for k in ("kind", "party", "office", "district", "state", "fec_candidate_id", "fec_committee_id", "fec_committee_name"):
            if ident.get(k) and not b.get(k):
                b[k] = ident[k]
        aliases[key] = gk
        stats[ident["method"]] += 1

    # display name: for FEC candidates, the most common station rendering that contains the FEC surname-ish token
    # (so "Ashley Hinson" beats "Ashley Arenholz", "Jon Ossoff" beats "Jonathan Ossoff"); else the FEC/name-rule name
    out_buyers = {}
    for gk, b in buyers.items():
        if b["method"] == "fec-candidate" and b["renderings"]:
            fec_last = b["fec_name"].split()[-1].upper()
            cands = [(c, r) for r, c in b["renderings"].items() if 2 <= len(r.split()) <= 3]
            good = [(c, r) for c, r in cands if fec_last in r.upper() or any(t in r.upper().split() for t in b["fec_name"].upper().split()[1:])] or cands
            if good:
                b["name"] = max(good)[1]
        b.pop("renderings"); b.pop("label_n")
        out_buyers[f"{b['category']}|{b['name'].lower()}"] = b
    aliases = {k: {"name": buyers[gk]["name"], "method": buyers[gk]["method"]} for k, gk in aliases.items()}
    buyers = out_buyers
    json.dump({"aliases": aliases, "buyers": buyers}, open(OUT, "w"), indent=0)
    merged = sum(1 for b in buyers.values() if len(b["labels"]) > 1)
    print(f"methods: {dict(stats)}", file=sys.stderr)
    print(f"{len(rows)} labels -> {len(buyers)} buyers ({merged} merged from 2+ labels)", file=sys.stderr)
    for b in sorted(buyers.values(), key=lambda b: -len(b["labels"]))[:12]:
        print(f"  {len(b['labels']):3d}  {b['category']:8s} {b['method']:14s} {b['name'][:40]:40s} <- {' | '.join(b['labels'][:4])[:110]}", file=sys.stderr)


if __name__ == "__main__":
    main()

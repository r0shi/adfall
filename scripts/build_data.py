#!/usr/bin/env python3
"""Build web/data/stations.json from FCC TV Query exports, the FCC TV service
contour file, and the NewsON station list.

Inputs (all public, no restrictions on use):
  * FCC TV Query, pipe-delimited (list=4), one file per state and service:
      https://transition.fcc.gov/fcc-bin/tvq?state=IA&serv=DTV&vac=3&list=4&size=9
  * FCC TV service contour points (updated daily, ~85 MB unzipped):
      https://transition.fcc.gov/bureaus/mb/databases/map/TV_service_contour_current.zip
  * NewsON station list, collected by searching the NewsON API per state
    (see scripts/fetch_newson.py).

Usage:
  python3 scripts/build_data.py --tvq-dir RAW/tvq --contour RAW/TV_service_contour_current.txt \
      --newson RAW/newson_stations.json --out web/data/stations.json
"""
import argparse, datetime, glob, json, os, re, sys
from collections import defaultdict

# TV Query list=4 column positions (0 = empty leading field)
C_CALL, C_SERVICE, C_RF, C_STATUS, C_CITY, C_STATE = 1, 3, 4, 9, 10, 11
C_ERP, C_HAAT, C_FACID = 14, 16, 18
C_LAT_NS, C_LAT_D, C_LAT_M, C_LAT_S = 19, 20, 21, 22
C_LON_EW, C_LON_D, C_LON_M, C_LON_S = 23, 24, 25, 26
C_LICENSEE, C_APPID, C_VCHAN, C_LMSID = 27, 37, 38, 39

STEP = 5          # keep every 5th contour azimuth (72 points per polygon)
DEC = 3           # coordinate decimals (~100 m)


def dms(sign, d, m, s):
    v = float(d) + float(m) / 60 + float(s) / 3600
    return -v if sign in ("S", "W") else v


UPPER = {"Llc", "Ii", "Iii", "Iv", "Lp", "L.p.", "L.l.c.", "Tv", "Dt", "Usa", "Pbs", "Abc", "Cbs", "Nbc"}


def nice_case(name):
    return " ".join(w.upper() if w.strip(",.") in UPPER else w for w in name.title().split())


def base_call(call):
    """KCCI-DT / WOI-TV / WXIA-TV -> KCCI / WOI / WXIA"""
    return re.sub(r"-(DT|TV|CD|LD|CA|LP)$", "", call.strip().upper())


def load_tvq(tvq_dir):
    stations = {}
    for fn in sorted(glob.glob(os.path.join(tvq_dir, "*.txt"))):
        for line in open(fn, errors="replace"):
            f = [x.strip() for x in line.split("|")]
            if len(f) < 40 or f[C_STATUS] != "LIC":
                continue
            fac = f[C_FACID]
            if fac in stations:          # a station can appear once per service file; keep first
                continue
            try:
                lat = dms(f[C_LAT_NS], f[C_LAT_D], f[C_LAT_M], f[C_LAT_S])
                lon = dms(f[C_LON_EW], f[C_LON_D], f[C_LON_M], f[C_LON_S])
            except ValueError:
                continue
            stations[fac] = {
                "call": f[C_CALL],
                "fac": int(fac),
                "svc": f[C_SERVICE],             # DTV = full power, DCA = Class A
                "city": f[C_CITY].title(),
                "state": f[C_STATE],
                "rf": f[C_RF],
                "vchan": f[C_VCHAN],
                "erp": f[C_ERP].replace("  ", " "),
                "licensee": nice_case(f[C_LICENSEE]),
                "tx": [round(lat, 4), round(lon, 4)],
                "app": f[C_APPID],               # CDBS-style application id ('0' for LMS-era filings)
                "lms": f[C_LMSID],               # LMS application id (32 hex chars)
                "slug": f[C_CALL].lower(),       # publicfiles.fcc.gov/tv-profile/<slug>
            }
    return stations


def load_contours(path, wanted_lms):
    """Return {lms_application_id: [polygon, ...]} ; polygon = [[lat, lon], ...] (closed).
    A DTS station has one record per transmitter site, hence the list."""
    out = defaultdict(list)
    with open(path, errors="replace") as fh:
        next(fh)  # header
        for line in fh:
            parts = line.split("|")
            lms = parts[2].strip()
            if lms not in wanted_lms:
                continue
            pts = []
            for i in range(0, 360, STEP):
                cell = parts[5 + i]
                lat, lon = cell.split(",")
                pts.append([round(float(lat), DEC), round(float(lon), DEC)])
            pts.append(pts[0])
            out[lms].append(pts)
    return out


def load_newson(path):
    by_call = {}
    if not path or not os.path.exists(path):
        return by_call
    for s in json.load(open(path)).values():
        name = s["name"]
        if "radio" in name.lower():
            continue
        call = base_call(name.split(" - ")[0])
        if not re.fullmatch(r"[KW][A-Z]{2,3}", call):
            continue              # cable channels like "News 12 New York"
        by_call.setdefault(call, {"id": s["id"], "name": name, "logo": s.get("logo")})
    return by_call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tvq-dir", required=True)
    ap.add_argument("--contour", required=True)
    ap.add_argument("--newson")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    stations = load_tvq(a.tvq_dir)
    print(f"stations from TV Query: {len(stations)}", file=sys.stderr)
    contours = load_contours(a.contour, {s["lms"] for s in stations.values()})
    print(f"stations with contours: {len(contours)}", file=sys.stderr)
    newson = load_newson(a.newson)
    print(f"NewsON broadcast stations: {len(newson)}", file=sys.stderr)

    records, matched = [], 0
    for s in stations.values():
        polys = contours.get(s["lms"])
        if not polys:
            continue
        lats = [p[0] for poly in polys for p in poly]
        lons = [p[1] for poly in polys for p in poly]
        rec = dict(s)
        rec.pop("app"); rec.pop("lms")
        rec["bbox"] = [min(lats), min(lons), max(lats), max(lons)]
        rec["polys"] = polys
        n = newson.get(base_call(s["call"]))
        if n:
            rec["newson"] = n
            matched += 1
        records.append(rec)
    records.sort(key=lambda r: (r["state"], r["call"]))
    print(f"written: {len(records)} stations, {matched} with a NewsON stream", file=sys.stderr)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump({"generated": datetime.date.fromtimestamp(os.path.getmtime(a.contour)).isoformat(),
                   "stations": records}, fh,
                  separators=(",", ":"))
    print(f"{a.out}: {os.path.getsize(a.out)/1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()

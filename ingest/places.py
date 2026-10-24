#!/usr/bin/env python3
"""Static place index for search: ZIP centroids and populated places from the Census Gazetteer files.
Writes web/data/places.json so the app can resolve "50309", "Des Moines" or "Des Moines, IA" with no
external geocoder. Street addresses still fall back to Nominatim in the app.

  python3 -m ingest.places
"""
import csv, io, json, os, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "data", "geo")
ZCTA_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_zcta_national.zip"
PLACE_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip"
UA = "tv-wormhole/0.1 (research prototype)"


def fetch(url, dest):
    if not os.path.exists(dest):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as fh:
            fh.write(r.read())
    return dest


def rows(zip_path):
    z = zipfile.ZipFile(zip_path)
    name = [n for n in z.namelist() if n.endswith(".txt")][0]
    txt = io.TextIOWrapper(z.open(name), encoding="latin-1")
    for r in csv.DictReader(txt, delimiter="\t"):
        yield {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}


def main():
    os.makedirs(GEO, exist_ok=True)
    zips = {}
    for r in rows(fetch(ZCTA_URL, os.path.join(GEO, "gaz_zcta_2023.zip"))):
        zips[r["GEOID"]] = [round(float(r["INTPTLAT"]), 4), round(float(r["INTPTLONG"]), 4)]
    places = []
    pop = {}
    try:
        with open(os.path.join(GEO, "co-est2024-alldata.csv"), encoding="latin-1") as fh:   # not place-level; places get area as a proxy
            pass
    except FileNotFoundError:
        pass
    for r in rows(fetch(PLACE_URL, os.path.join(GEO, "gaz_place_2023.zip"))):
        name = r["NAME"]
        for suffix in (" city", " town", " village", " CDP", " borough", " municipality", " urbana", " comunidad", " zona urbana"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        places.append([name, r["USPS"], round(float(r["INTPTLAT"]), 4), round(float(r["INTPTLONG"]), 4), round(float(r["ALAND_SQMI"]), 1)])
    places.sort(key=lambda p: -p[4])        # larger land area first as a crude prominence proxy
    out = {"zips": zips, "places": places, "columns": ["name", "state", "lat", "lon", "land_sqmi"]}
    path = os.path.join(ROOT, "web", "data", "places.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"places.json: {len(zips)} ZIPs, {len(places)} places, {os.path.getsize(path)/1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()

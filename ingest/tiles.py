#!/usr/bin/env python3
"""Vector tiles (PMTiles) for the map: hex money layers and station contours, via tippecanoe.

  python3 -m ingest.tiles        -> web/data/tiles/hex5.pmtiles, hex7.pmtiles, contours.pmtiles, meta.json
"""
import json, os, subprocess, sys, tempfile
import h3
from . import pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "data", "tiles")
ZOOMS = {5: ("3", "8"), 7: ("6", "11")}


def hex_features(con, res, fh):
    maxima = {"booked": 0, "invoiced": 0, "spots": 0, "pp": 0, "ps": 0, "stations": 0}
    vals = {k: [] for k in maxima}
    n = 0
    for h, booked, invoiced, spots, pop, stations in con.execute("SELECT h3, booked, invoiced, spots_aired, pop, stations_with_buys FROM hex_total WHERE res=%s", (res,)):
        booked, invoiced, spots, pop = float(booked or 0), float(invoiced or 0), float(spots or 0), float(pop or 0)
        if booked <= 0 and spots <= 0:
            continue
        props = {"h3": h, "booked": round(booked), "invoiced": round(invoiced), "spots": round(spots), "pop": round(pop), "stations": stations,
                 "pp": round(booked / pop, 2) if pop > 0 else 0, "ps": round(booked / spots) if spots > 0 else 0}
        ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(h)]; ring.append(ring[0])
        fh.write(json.dumps({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}) + "\n")
        for k in vals:
            vals[k].append(props[k])
        n += 1
    for k, v in vals.items():
        v.sort(); maxima[k] = v[int(len(v) * 0.985)] if v else 1       # 98.5th percentile, same as the JSON layer used
    return n, maxima


def contour_features(fh):
    d = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))
    for s in d["stations"]:
        coords = [[[[lon, lat] for lat, lon in poly]] for poly in s["polys"]]
        fh.write(json.dumps({"type": "Feature", "properties": {"fac": s["fac"], "call": s["call"], "state": s["state"], "svc": s["svc"]},
                             "geometry": {"type": "MultiPolygon", "coordinates": coords}}) + "\n")
    return len(d["stations"])


def tippecanoe(src, dest, layer, zmin, zmax, extra=()):
    cmd = ["tippecanoe", "-o", dest, "--force", "-l", layer, "-Z", zmin, "-z", zmax, "--no-feature-limit", "--no-tile-size-limit",
           "--detect-shared-borders", "--simplification=4", "--quiet", *extra, src]
    subprocess.run(cmd, check=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {"hex": {}}
    with pg.connect() as con, tempfile.TemporaryDirectory() as td:
        for res, (zmin, zmax) in ZOOMS.items():
            src = os.path.join(td, f"hex{res}.json")
            with open(src, "w") as fh:
                n, maxima = hex_features(con, res, fh)
            tippecanoe(src, os.path.join(OUT, f"hex{res}.pmtiles"), f"hex{res}", zmin, zmax)
            meta["hex"][str(res)] = {"cells": n, "max": maxima, "minzoom": int(zmin), "maxzoom": int(zmax)}
            print(f"  hex{res}.pmtiles: {n} cells, {os.path.getsize(os.path.join(OUT, f'hex{res}.pmtiles'))/1e6:.1f} MB", file=sys.stderr)
        src = os.path.join(td, "contours.json")
        with open(src, "w") as fh:
            n = contour_features(fh)
        tippecanoe(src, os.path.join(OUT, "contours.pmtiles"), "contours", "3", "10", ("--coalesce-densest-as-needed",))
        print(f"  contours.pmtiles: {n} stations, {os.path.getsize(os.path.join(OUT, 'contours.pmtiles'))/1e6:.1f} MB", file=sys.stderr)
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"))


if __name__ == "__main__":
    main()

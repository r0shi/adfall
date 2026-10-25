# TV Wormhole

Prototype: pick any spot in the US and see which broadcast TV stations reach it
(FCC predicted service contours), with a link to each station's live newscast
stream on NewsON and to its FCC political advertising file.

Docs: [docs/research.md](docs/research.md) (findings, data sources, pitfalls) and
[docs/spec.md](docs/spec.md) (proto-spec and v1 plan).

## Run

```bash
python3 -m http.server 8765 --directory web
```

Then open http://localhost:8765.

## Rebuild the data

`web/data/stations.json` is generated from public FCC data plus the NewsON
station list. To refresh it:

1. Download the FCC contour file (updated daily):
   https://transition.fcc.gov/bureaus/mb/databases/map/TV_service_contour_current.zip
2. Export TV Query pipe-delimited lists per state for services `DTV` and `DCA`
   into a folder (`tvq?state=IA&serv=DTV&vac=3&list=4&size=9`).
3. `python3 scripts/fetch_newson.py` (writes `dl/newson_stations.json`).
4. `python3 scripts/build_data.py --tvq-dir RAW/tvq --contour RAW/TV_service_contour_current.txt --newson RAW/newson_stations.json --out web/data/stations.json`

## Web app (SvelteKit)

```bash
npm --prefix app install
npm --prefix app run dev        # http://localhost:5173 — Stations, Buyers, Ads, Over time
npm --prefix app run build      # static site in app/build (data included)
npm --prefix app run preview -- --host 0.0.0.0 --port 4173   # serve the build on the LAN/tailnet; `tailscale serve --bg 4173` for HTTPS
# any Host header is accepted by default; ALLOWED_HOSTS=ix.carp-gopher.ts.net,localhost narrows it
```

The app reads the exported JSON in `web/data` (symlinked as `app/static/data`). The
single-file prototype under `web/` still runs with the python server above.

## Data layer

Postgres with PostGIS via docker compose; see [docs/design.md](docs/design.md).

```bash
make db-up && make migrate      # start PostGIS on 127.0.0.1:5434 and apply db/migrations
make geo                        # counties, population, H3 cells, coverage (once; rerun when the crawl widens)
make fec                        # FEC candidate/committee master files (once per cycle refresh)
make pipeline                   # load -> entities -> identity -> entities -> marts -> export -> tiles (tippecanoe)
```

Crawl and parse (`python3 -m ingest.crawl`, `ingest.parse`, `ingest.ocr`, `ingest.update`) still
write the SQLite store at `data/political.sqlite`; `make load` upserts it into Postgres.

## What it does not do

* Network affiliation is not in the FCC TV Query export, so stations show call
  sign and channel only.
* Streams are linked, not embedded. Station streams replace broadcast ad breaks
  with a slate, so political ads are not visible on them; the FCC political file
  link is the substitute.

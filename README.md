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
make stations                   # upsert web/data/stations.json into the station table (once; rerun when it changes)
make pipeline                   # stations -> entities -> identity -> entities -> marts -> export -> tiles (tippecanoe)
```

## Ingest pipeline

Postgres is the only store: every stage reads and writes it directly (`DATABASE_URL`, default the
compose service), so a crawl, a parse and the updater can run at the same time. Stages, in order:
`crawl` (list + download PDFs into `opif_file` and `data/pdfs/`), `parse` (text layer -> `document`;
image-only PDFs are flagged), `ocr` (Apple Vision, or tesseract; ledger in `ocr`), `parse --only-failed`
(pick up OCR text), `entities`, `identity`, `entities`, `marts`, then `geo`/`export`/`tiles` for the
site. `update` applies the FCC change feed for daily upkeep. `make migrate` applies new schema files;
a stage refuses to run against a schema that is behind.

```bash
make status                     # counts per stage, running/failed stages, problems; STATE=PA for per-station rows
make coverage                   # crawled vs the national 2024/2026 document counts, by state (MISSING=1 lists gaps)
make validate                   # parse invariants per template with worst examples (needs Postgres loaded)
make batch                      # national 2026 crawl+OCR+parse, state by state, resumable; Postgres refreshed in the background
make crawl STATE=TX             # one state from data/crawl_targets_2026_national.txt
make update                     # FCC change feed since the last sync, plus downloads
make refresh                    # entities -> identity -> entities -> marts
make migrate-sqlite             # one-off: copy the retired data/political.sqlite store into Postgres
```

Every stage writes `data/logs/<stage>-<timestamp>.log` (mirrored to stderr) ending in a
`SUMMARY` line with counts and failures, records a row in the Postgres `pipeline_run` table,
holds a lock in `data/locks/` so it cannot overlap itself, and exits
non-zero when failures exceed its threshold. Everything resumes after a kill: listings are
redone unless complete, downloads are atomic and verified, OCR and download failures are
retried a capped number of times and then reported by `make status`. Operations notes and
findings: [docs/research.md](docs/research.md).

## What it does not do

* Network affiliation is not in the FCC TV Query export, so stations show call
  sign and channel only.
* Streams are linked, not embedded. Station streams replace broadcast ad breaks
  with a slate, so political ads are not visible on them; the FCC political file
  link is the substitute.

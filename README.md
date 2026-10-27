# Adfall

Drop a pin anywhere in the United States and see the broadcast TV stations whose
signal reaches it (its *airshed*), watch their newscasts, and follow the political
advertising money that lands on it (its *adfall*): who bought airtime, for how
much, when the spots aired, and, where a match exists, the ad itself.

The project has two independent ends joined by one directory:

```
FCC public files, TV Query, contours      Census, FEC, NewsON, YouTube
                 │                                   │
                 ▼                                   ▼
   ┌───────────────────────────────────────────────────────┐
   │  Pipeline  (Python, PostGIS)             make …        │
   │  crawl → parse → ocr → entities → identity → marts     │
   └───────────────────────────┬───────────────────────────┘
                               │  make export / make tiles
                               ▼
                 web/data/   JSON · Parquet · PMTiles
                               │  (symlinked as app/static/data)
                               ▼
   ┌───────────────────────────────────────────────────────┐
   │  App  (SvelteKit static site: MapLibre, deck.gl,       │
   │        Observable Plot, DuckDB-WASM)    npm …          │
   └───────────────────────────────────────────────────────┘
```

The app never talks to Postgres and the pipeline never reads the app's exports
back in. Either end can be started, stopped or rebuilt on its own; deploying the
app means copying `app/build` (which includes `web/data`) to any static host.

Status: working prototype, data for 2026 being crawled nationally. Not yet
deployed. Findings, pitfalls and design live in [docs/](#documentation).

## Prerequisites

| | Needed for |
|---|---|
| Python 3.12 or newer (developed on 3.14), venv at `.venv`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` | pipeline |
| PostgreSQL 17 + PostGIS: `brew install postgresql@17 postgis` (or Docker with Compose, see below) | pipeline store |
| Node 20+ | app |
| [tippecanoe](https://github.com/felt/tippecanoe) (`brew install tippecanoe`) | `make tiles` |
| Apple Vision on macOS (the `ocrmac` package in requirements); elsewhere the `tesseract` CLI, picked automatically | `make ocr` |
| `yt-dlp` (in requirements), optionally `YOUTUBE_API_KEY` in `.env` for the Data API | `make video` |

Copy `.env.example` to `.env`. The only required setting is `DATABASE_URL`, and the
default already points at `127.0.0.1:5434`, where both the Homebrew server (as set
up below) and the compose service listen.

## Quick start

```bash
brew services start postgresql@17 && make migrate   # PostGIS on 127.0.0.1:5434 (see Set up once), schema from db/migrations
make geo && make fec              # counties, population, H3 cells, coverage; FEC master files (once per cycle)
make stations && make places      # station table from web/data/stations.json; place index for search
make crawl STATE=IA               # one state's 2026 political files into Postgres and data/pdfs
make parse && make ocr && make parse
make pipeline                     # entities → identity → entities → marts → export → tiles
npm --prefix app install && npm --prefix app run dev     # http://localhost:5173
```

The repository ships with the aggregate exports committed, so the app runs
against real data before any of the pipeline steps above.

## The app

```bash
npm --prefix app run dev                       # dev server with hot reload on :5173
npm --prefix app run build                     # static site in app/build, data included
npm --prefix app run serve -- --host 0.0.0.0 --port 4173      # serve the build on the LAN (app/serve.mjs, reads app/build live)
tailscale serve --bg 4173                      # HTTPS on the tailnet
ALLOWED_HOSTS=ix.carp-gopher.ts.net,localhost npm --prefix app run dev   # restrict Host headers (any host is accepted by default)
```

Routes:

| Route | What it shows |
|---|---|
| `/` | Map-first home. Click or search to drop a pin; the popover lists stations reaching it with newscast and FCC links, money by buyer, aired ads, the political spots in tonight's and last night's newscasts, and a timeline. The nav's "Color by" switch colors every buyer mark by office level or by party. A second pin (B) turns on comparison and difference layers. |
| `/map` | The coverage map on its own, without the money layers. |
| `/time` | Money moving across the hex grid day by day, with trails or accumulate, driven by the global timeline bar. |
| `/buyers`, `/buyers/<slug>` | Who is buying: treemap by category, per-buyer stations, flights, dayparts, creatives. |
| `/stations/<facility>` | One station: buyers, flights, daypart heatmap, documents. |
| `/ads`, `/ads/<ad_id>` | Creatives by Ad-ID, with the matched video where one exists. |
| `/explore` | Pivot builder over the Parquet marts, in the browser via DuckDB-WASM. |
| `/about` | Methods and provenance, generated from `web/data/methods.json` at export time. |

Serve the build with `npm run serve`, not `vite preview`: the preview server indexes
the build folder once at startup, so after `post_batch.sh` or `npm run build` rewrites
it, the preview answers 404 for every new chunk until restarted and the site is blank.
`app/serve.mjs` looks files up per request, answers Range requests for the PMTiles, and
sends an ETag with `Cache-Control: no-cache` so browsers revalidate every data file.
`scripts/launchd/com.adfall.web.plist` keeps it running across reboots
(`cp` it into `~/Library/LaunchAgents/` and `launchctl load -w` it, like the daily job).

The client recovers on its own from the two ways a static deploy used to leave a tab
stuck. A rebuild drops every old chunk: a tab still holding the previous page reloads
once when a dynamic import fails (`src/lib/recover.js`, rate-limited to once a minute),
and polls `_app/version.json` so the next in-app navigation after a deploy is a full
load. A data file that fails to load (an export mid-write, a network blip) is retried
once, never memoized, and the Over time views show the reason with a Try again button
(`src/lib/timedata.svelte.js`, `LoadPanel.svelte`) instead of a blank timeline.

The URL hash carries the whole view (pins, layer, tab, newscast night, timeline, color mode, camera), so any view is linkable and Back/Forward step through your changes.

## The pipeline

Every stage is a Python module under `ingest/` and a `make` target. Postgres is
the only store: stages read and write it directly, so a crawl, a parse and the
updater can run at the same time. Each stage:

- writes `data/logs/<stage>-<timestamp>.log`, mirrored to stderr, ending in a
  `SUMMARY` line with counts and failures;
- records a row in the `pipeline_run` table (`make status` reads it);
- holds a lock in `data/locks/` so it cannot overlap itself, and refuses to run
  against a schema that is behind (`make migrate` fixes that);
- resumes after a kill: listings are redone unless complete, downloads are
  atomic and verified, OCR and download failures are retried a capped number of
  times and then reported.

### Set up once

Postgres runs natively under Homebrew and `brew services` (launchd), so it comes
back after a reboot and the daily jobs can depend on it. On this Mac
`postgresql@17` listens on `127.0.0.1:5434` only (5433 belongs to another app);
the role, database and password match `.env.example`, so `DATABASE_URL` is the
default. One-time install:

```bash
brew install postgresql@17 postgis
conf=/opt/homebrew/var/postgresql@17/postgresql.conf
cat >> $conf <<'EOF2'
# Adfall (scripts/backup.sh, README "Set up once")
listen_addresses = '127.0.0.1'
port = 5434
shared_buffers = 512MB
work_mem = 64MB
maintenance_work_mem = 256MB
EOF2
brew services start postgresql@17
/opt/homebrew/opt/postgresql@17/bin/psql -p 5434 -d postgres -c "CREATE ROLE tvw LOGIN SUPERUSER PASSWORD 'tvw'" \
  -c "CREATE DATABASE tvw OWNER tvw TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'en_US.UTF-8'"
```

`brew services info postgresql@17` shows whether it is up; the log is
`/opt/homebrew/var/log/postgresql@17.log`. Nightly dumps: `scripts/backup.sh`
(`pg_dump -Fc` into `data/backups/`, newest 7 kept, uploaded to Backblaze B2 when
`B2_BUCKET` is set in `.env` and `rclone` or the `b2` CLI is configured), scheduled
by `scripts/launchd/com.adfall.backup.plist` once copied into
`~/Library/LaunchAgents` (instructions in the file).

The alternative is the compose service in `docker-compose.yml` (same port, role and
password): `make db-up` starts it, `make db-down` stops it, data persists in the
`tvw-pgdata` volume. Only one of the two can hold port 5434. The data was moved from
that container (PostgreSQL 16 under Colima) to Homebrew on 2026-10-26; the volume still
holds the pre-move copy, so rolling back is

```bash
brew services stop postgresql@17 && docker --context colima start tvw-db   # and the reverse to come back
```

(anything written after the move is only on the Homebrew side; carry it over with
`pg_dump -Fc` from one and `pg_restore` into the other).

```bash
make migrate         # apply db/migrations/*.sql in order; rerun after pulling new migrations
make geo             # counties, population, H3 cells, station coverage (rerun when stations.json changes)
make fec             # FEC candidate, committee and linkage files for the cycle into data/fec
make stations        # upsert web/data/stations.json; the crawl only accepts stations listed there
make places          # Census Gazetteer ZIPs and places for the search box
```

### Get data

```bash
make batch                       # national 2026 crawl, state by state, in the background: crawl → parse → ocr → parse,
                                 # with the entity refresh running behind the next state's download. Resumable.
make crawl STATE=TX              # one state from data/crawl_targets_2026_national.txt
make update                      # FCC change feed since the last sync, plus downloads (daily upkeep)
make ocr                         # OCR image-only PDFs (Apple Vision on macOS)
make parse                       # parse new downloads, then re-parse failed ones that now have OCR text
```

`make batch` writes to `data/logs/batch-stdout.log` and one log per stage. A state
whose stage fails is recorded failed and skipped on resume until rerun; three
consecutive failures stop the driver. Options behind the target: `--states
IA,FL`, `--all` (redo done states), `--no-pg` (skip the refresh chain), and
worker counts for download, OCR and parse.

### Process and publish

```bash
make refresh                     # entities → identity → entities → marts (what the batch runs after each state)
make export                      # web/data JSON, Parquet marts and methods.json
scripts/safe_export.sh           # same, but waits for any running entity or marts rebuild first
TVW_TILES=1 scripts/safe_export.sh --only creatives,pages,details    # subset export, then PMTiles
make tiles                       # PMTiles for hex layers and contours
make video                       # buyer → YouTube channel → upload per creative (TOP=300 buyers by airings)
make pipeline                    # stations → entities → identity → entities → marts → export → tiles
nohup scripts/post_batch.sh --rerun > data/logs/post_batch.log 2>&1 &   # after a batch: wait for the driver, rerun failed states, export + tiles, video, build
```

Export sections for `--only`: `methods, stations, hex, buyers, creatives, time,
details, pages, newscasts, parquet`. Hand-maintained inputs that the refresh applies:
`data/buyer_identity.json` and `data/buyer_overrides.yaml` for buyer merges,
`data/video_overrides.yaml` for ad video.

### Watch and diagnose

```bash
make status                      # counts per stage, running and failed stages, problems; STATE=PA for per-station rows
make coverage                    # crawled vs the national document counts by state; MISSING=1 lists the gaps
make validate                    # parse invariants per template with worst examples; report in data/validate-<date>.json
tail -f data/logs/batch-stdout.log
ls -la data/locks/               # a held lock names the pid; stale files are harmless (flock, not pid files)
```

Useful queries live in `pipeline_run` (one row per stage run with status, counts
and log path) and `document` (kind, template, parse status and the parsed fields
in `raw`). `docs/research.md` keeps the running account of coverage and parser
quality.

### Run it every day

```bash
scripts/daily.sh                 # update → parse → ocr → parse → refresh → export + tiles → build; add --video for the YouTube re-alignment (Sundays do it anyway)
scripts/health.sh                # database answers, newest ok update and export under 30 h old → web/data/health.json, exit 1 on failure
```

`scripts/daily.sh` runs every stage in order, logs one timestamp line per step to
`data/logs/daily-<date>.log` (the stages' own logs stay in `data/logs/<stage>-<timestamp>.log`),
skips the steps that depend on a failed one, and always exports and builds so the
site reflects whatever the database holds. It steps aside when a batch driver holds
the `pipeline` lock, and a second copy of itself exits at once (`data/locks/daily.lock`).
`scripts/health.sh` writes `web/data/health.json`, which the About page shows under
the build line.

Two launchd agents in `scripts/launchd/` schedule them: `com.adfall.daily` at 05:10
local time and `com.adfall.health` hourly at :30 (and once on load). They are not
installed by the repository; the paths inside them are absolute, so edit them if the
checkout is not at `/Users/alex/tv_wormhole`, then:

```bash
cp scripts/launchd/com.adfall.*.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.adfall.daily.plist
launchctl load -w ~/Library/LaunchAgents/com.adfall.health.plist
launchctl list | grep adfall           # a third column of 0 is the last exit status; - means never run
launchctl start com.adfall.daily       # run the daily job now instead of waiting for 05:10
launchctl unload -w ~/Library/LaunchAgents/com.adfall.daily.plist   # stop scheduling it
```

launchd's own capture of each job's stdout and stderr goes to `data/logs/launchd-daily.log`
and `data/logs/launchd-health.log`. Agents run only while this user is logged in, and
a run scheduled while the Mac sleeps happens at the next wake, so for a run at 05:10
the Mac has to be awake: `sudo pmset repeat wakeorpoweron MTWRFSU 05:05:00` wakes it
every day at 05:05 (`pmset -g sched` shows the schedule; `sudo pmset repeat cancel`
removes it). PostGIS must already be up (`make db-up`); the health check reports when
it is not.

### Maintenance

```bash
.venv/bin/python -m ingest.parse --reparse                       # every document, from the text cache in data/text
.venv/bin/python -m ingest.parse --only-failed                   # unrecognised or failed documents that now have OCR text
.venv/bin/python -m ingest.parse --kind invoice --no-lock        # one document kind, alongside a running batch
.venv/bin/python -m ingest.parse --file data/pdfs/<id>.pdf       # one file, for parser work
.venv/bin/python -m ingest.crawl --stations 25685 --years 2026 --download --verify   # recheck one station's files
.venv/bin/python -m ingest.video report                          # match rates by tier, category and place
```

A parser change that should reach every document bumps `PARSER_VERSION` in
`ingest/parse.py`; the next `make parse` then reparses everything. A change
limited to one layout is cheaper to apply with `--kind`, as above, followed by
`make refresh`. Video matches are keyed by Ad-ID, so after any change to how
codes are read, run `make video` again.

## Repository layout

```
app/            SvelteKit app (static adapter). app/static/data → ../../web/data
web/data/       exports the app reads: stations.json, spend/, hex/, buyers/, creatives/, marts/*.parquet, tiles/
ingest/         pipeline stages, one module each; runlog.py (locks, logs, ledger), pg.py (migrate, marts)
db/migrations/  schema, applied in order by make migrate
data/           crawl store (pdfs/, text/, ocr/), logs/, locks/, target lists, overrides, FEC files
scripts/        build_data.py (stations.json from FCC exports), fetch_newson.py, safe_export.sh, backup.sh (+ launchd/ plist)
docs/           research.md, spec.md, design.md, design-pass.md
docker-compose.yml   alternative PostGIS service tvw-db on 127.0.0.1:5434 (default is Homebrew postgresql@17)
```

Per-entity exports (`web/data/buyers/`, `stations/`, `creatives/id/`, `marts/`,
`tiles/*.pmtiles`) are build artifacts and not committed; the aggregates are.

## Rebuilding `stations.json`

The station list with contours is a pipeline input as well as an app file. To
refresh it from source:

1. Download the FCC contour file (updated daily):
   https://transition.fcc.gov/bureaus/mb/databases/map/TV_service_contour_current.zip
2. Export TV Query pipe-delimited lists per state for services `DTV` and `DCA`
   into a folder (`tvq?state=IA&serv=DTV&vac=3&list=4&size=9`).
3. `python3 scripts/fetch_newson.py` (writes `dl/newson_stations.json`).
4. `python3 scripts/build_data.py --tvq-dir RAW/tvq --contour RAW/TV_service_contour_current.txt --newson RAW/newson_stations.json --out web/data/stations.json`
5. `make stations && make geo`

## Documentation

- [docs/research.md](docs/research.md): findings, data sources, pitfalls, coverage and parser quality over time.
- [docs/spec.md](docs/spec.md): proto-spec and v1 plan.
- [docs/design.md](docs/design.md): data layer decisions (static artifacts, time allocation, H3 geography, buyer identity).
- [docs/design-pass.md](docs/design-pass.md): presentation design pass and build order.
- `/about` in the app: methods as exported, kept in sync with the pipeline by `ingest.export`.

## Data sources and limits

Contours and station facts come from the FCC (TV Query and the TV service
contour file); political advertising documents from the FCC public inspection
files through the FCC Data API; population from the Census; candidate and
committee identities from FEC bulk files; newscast links from NewsON; ad video
is embedded from the campaigns' own channels and never downloaded or rehosted.
This product uses the FCC Data API but is not endorsed or certified by the FCC.

- Spend is read from scanned order and invoice PDFs. Booked money is the latest
  order revision, invoiced money the invoice total, aired spots are exact; dollars
  per person spread a station's money over its footprint by population share.
- Network affiliation is not in the FCC TV Query export, so stations show call
  sign and channel only.
- Streams are linked, not embedded, and station streams replace broadcast ad
  breaks with a slate, so the political ads are not visible on them.
- Buyer identity is alias-table matching with FEC confirmation; mistakes are
  corrected in `data/buyer_overrides.yaml`.

## License

The code is released under the [MIT License](LICENSE).

Dependencies are MIT, BSD, ISC, Apache-2.0 or Unlicense, with one exception:
`psycopg` is LGPL-3.0. It is imported unmodified and installed from PyPI by
whoever runs the pipeline, which the LGPL permits without affecting this
project's license. PostGIS (GPL) and tippecanoe (BSD) run as separate programs
and are not distributed here.

The data files under `web/data` and `data/` are not covered by the MIT license.
They derive from FCC, Census and FEC public records, which are in the public
domain, and from NewsON's station list and the campaigns' public channels, which
remain their owners'. Map tiles come from OpenFreeMap and carry OpenStreetMap's
ODbL attribution in the app.

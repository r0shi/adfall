# Design: data layer and presentation layer

Status: proposal, 2026-10-24. Decision points are marked **DP-n** and
collected at the end. Nothing here is built yet except where noted.

## What the system has to do

Today: location → stations → spend by buyer, with links out. Soon: the views
already agreed (spenders, spend per person, ads actually aired). Eventually:
heatmaps of ad density, money density and dollars per spot; time animation
("watch the money move"); buyer enrichment from FEC and state data; and
enough caching that a traffic spike doesn't take it down.

Facts that shape the design:

- The data changes once a day. Nothing is real-time. Every expensive
  computation can be done at build time.
- The raw corpus is big (hundreds of thousands of PDFs per cycle) but the
  derived, servable data is small (tens of MB per cycle). Users never need
  the PDFs through the site; they need numbers, geometry and links.
- Reads vastly outnumber writes. Almost every read is "metrics for a place,
  a station, a buyer, or a time window."
- Geography is contour polygons, points and population; time is daily;
  entities are stations, buyers, orders, creatives.

## Shape of the system

```
FCC OPIF ──crawl──▶ PDF store ──parse/OCR──▶ Postgres (system of record)
                                                │
                                      build step (SQL + Python)
                                                │
                       ┌────────────────────────┼─────────────────────────┐
                       ▼                        ▼                         ▼
               PMTiles (hex metrics,     Parquet/JSON marts         Search index
               contours, by time)        (per station/buyer/day)    (places, buyers)
                       │                        │                         │
                       └────────── object storage + CDN ──────────────────┘
                                                │
                                        browser app (static)
```

Three layers, deliberately separated:

1. **System of record**: Postgres with PostGIS, written only by the ingest
   pipeline. Holds everything, normalized, with history.
2. **Build step**: SQL views and a small Python job that produce serving
   artifacts. Runs after each ingest.
3. **Serving**: immutable artifacts on object storage behind a CDN. No
   database in the read path. That is the caching layer and the horizontal
   scaling story in one: the CDN is the cache, and the origin is a bucket.

An API server is optional and only for things that cannot be precomputed.
Right now there are none: the location lookup is already client-side, and
search over places and buyers can be a small static index.

**DP-1: static-artifact serving (recommended) vs. a live API over Postgres.**
A live API (FastAPI or PostgREST, with Redis and a CDN) is more flexible for
ad-hoc queries, but it puts a database in the read path and needs real
capacity planning. Static artifacts give unlimited read scale for the cost of
a bucket, and the daily cadence means staleness is not a concern. Ad-hoc
analysis still happens against Postgres directly, not through the site. The
one thing that argues for an API later is user-defined queries (arbitrary
buyer × station × time pivots); DuckDB-WASM over Parquet in the browser
covers much of that without a server (see presentation layer).

## System of record: Postgres + PostGIS

Run via docker compose: `postgis/postgis` image, a named volume, nothing
else required. Optional services later: `martin` (tile server, for local
development of tile layers), `pgadmin` or none.

### Schema

Ingest tables (migrated from the SQLite pilot, same meaning):

- `station(facility_id pk, call, service, city, state, licensee, group,
  dma_code, tx geometry(Point), contour geometry(MultiPolygon),
  newson_id, public_file_slug)` — one row per licensed station, refreshed
  from TV Query and the contour file.
- `opif_file(file_id pk, facility_id, year, folder_path, file_name, size,
  created_at, downloaded_at, deleted_at, sha256)` — every document the FCC
  lists, as listed. Never deleted; `deleted_at` is set.
- `document(file_id pk, kind, template, source(text|ocr), parse_status,
  parser_version, parsed_at, raw jsonb)` — parse outcome, with the full
  extraction kept as JSON so reparsing is a replay, not a recrawl.

Domain tables (the interesting part; populated from `document`):

- `buyer(buyer_id pk, canonical_name, category(federal|state|local|issue),
  kind(candidate|party|pac|issue|unknown), party, office, state,
  fec_committee_id, followthemoney_id, notes)`.
- `buyer_alias(alias text, facility_id nullable, buyer_id)` — every folder
  name, advertiser string and form committee name that maps to a buyer.
  Matching is automatic first (normalized string, `POL/` strip, form
  committee), then manual overrides from a YAML file in the repo. The
  alias table is how the manual work compounds instead of being redone.
- `order_(order_id pk, facility_id, order_no, buyer_id, agency_id,
  advertiser_text, product, flight_start, flight_end, status
  (booked|revised|cancelled), gross, net, spots, latest_file_id,
  first_seen, last_seen)` — one row per order number, the current state.
- `order_revision(order_id, revision_seq, file_id, print_date, gross, net,
  spots)` — every revision, so "the money moving" includes cancellations
  and re-bookings.
- `order_line(order_id, line_no, program, daypart, start_date, end_date,
  days_mask, spots_per_week, rate, length_sec, amount)` — the schedule
  grid from WideOrbit orders; this is what lets booked dollars be placed
  on calendar days before any invoice exists.
- `invoice(invoice_id pk, facility_id, invoice_no, order_id nullable,
  buyer_id, period_start, period_end, gross, net, spots, file_id)`.
- `spot(spot_id pk, invoice_id, facility_id, buyer_id, aired_at timestamptz,
  program, rate, length_sec, ad_id)` — one row per aired spot. This is the
  finest grain in the system and the basis for ad density and "ads actually
  shown".
- `creative(ad_id pk, prefix, buyer_id nullable, first_aired, last_aired,
  airings, title nullable, video_url nullable)` — Ad-ID codes with whatever
  we learn about them.
- `agency(agency_id pk, name, aliases[])`.
- `form(file_id pk, buyer_id, candidate, committee, office, party,
  election_date, treasurer, level, issue, raw jsonb)`.

Geography and population:

- `county(geoid pk, name, state, pop, geom, centroid)` from Census TIGER
  and the Gazetteer file.
- `hex(h3 pk, res, geom, pop)` — H3 cells at two resolutions (5 for
  national, 7 for market zoom), population allocated from block groups.
- `station_hex(facility_id, h3, res, coverage_share)` — which cells each
  contour covers; share is the fraction of the cell inside the contour.

Time-series marts (materialized views, refreshed by the build step):

- `spend_daily(facility_id, buyer_id, day, booked, invoiced, spots_booked,
  spots_aired)` — booked dollars allocated across the order's schedule days
  (from `order_line`, else evenly across the flight), invoiced dollars on
  the invoice period, aired spots from `spot`.
- `hex_daily(h3, res, day, booked, invoiced, spots, pop)` — the join of
  `spend_daily` with `station_hex`; money and ads are spread across a
  station's cells in proportion to cell population. Dividing by `pop` gives
  per-person density; dividing by `spots` gives dollars per spot.
- `buyer_station(buyer_id, facility_id, booked, invoiced, spots, creatives)`
  and `buyer_total`, `station_total` for the ranked views.

**DP-2: allocation model for "money over time".** Booked dollars have a
flight window and often a per-line schedule; invoiced dollars have a billing
period; aired spots have timestamps. The proposal: use the finest grain
available per order (spots > order lines > flight window), and always show
which grain a number came from. The alternative, invoiced-only, is more
honest but lags a month and misses the final two weeks entirely.

**DP-3: how money is spread over geography.** By covering-station contour,
split across cells by population share. The alternative is Nielsen DMA
assignment, which matches how buyers think but needs licensed boundaries.
Contours are what we have, are public, and are the thing the site is about.
Overlapping contours mean a dollar can count in several cells; that is
correct for "money reaching this spot" and should be labeled as such.

**DP-4: H3 hexes vs. counties vs. raw polygons as the spatial unit.** H3
gives uniform cells, trivial aggregation at multiple zooms, and maps
directly onto deck.gl's H3HexagonLayer. Counties are familiar and carry
population natively but are wildly uneven in size. Raw contours are right
for "which stations reach here" and wrong for density. Recommendation: H3
for all density and animation layers, contours for the lookup, counties
only as a display option.

### Ingest changes

- Write to Postgres directly from the pipeline (psycopg); keep the SQLite
  path as a loader for the pilot database.
- Make steps idempotent and replayable from `document.raw` so parser
  improvements never require a recrawl.
- Store a `sha256` per PDF so a changed upload is detected.
- Orchestration: one `pipeline` CLI with subcommands and a Makefile; cron or
  launchd daily. No workflow engine until there is a reason.

### Operational notes

- Postgres is the only stateful service. Backups are `pg_dump` plus the PDF
  directory. Everything else is rebuildable.
- Expected sizes at national scale for one cycle: `opif_file` ~1.5M rows,
  `spot` ~10–20M rows, `hex_daily` ~ (cells × days) ~ 5M rows at res 5.
  All fine on a laptop Postgres.
- Parquet exports of the marts for DuckDB are a byproduct of the build step,
  for pivots outside the site.

## Build step: what gets published

| Artifact | Format | Size (est., one cycle) | Used by |
| --- | --- | --- | --- |
| Station contours + metadata | PMTiles (vector) | 5 MB | lookup map, station layer |
| Hex metrics by day | PMTiles with one layer per day bucket, or Parquet | 20–60 MB | heatmaps, time animation |
| Per-station spend + buyers | JSON per station | 2–10 MB total | station cards (today's `spend/*.json`) |
| Buyer profiles | JSON per buyer | small | buyer pages |
| Spend marts | Parquet | 10–30 MB | in-browser pivots (DuckDB-WASM) |
| Search index | JSON | small | place and buyer search |
| Rebuild manifest | JSON | tiny | cache busting: every artifact path carries a build id |

Immutable paths (`/v/<build_id>/...`) plus a tiny `latest.json` make the
CDN cache trivially correct: long max-age on everything versioned, short on
the pointer.

## Presentation layer

### Requirements

Responsive (phone-first panel, desktop map-plus-sidebar), rich map layers
(polygons, hexes, heat, animation with a time scrubber), charts (ranked
bars, small multiples, sparklines over time), and data-dense without a
server round-trip per interaction.

### Framework options

**Map engine**
- Leaflet (current): fine for polygons and markers; no GPU; hex layers with
  thousands of cells and animation get slow.
- MapLibre GL JS: GPU vector maps, PMTiles support, styling by data,
  smooth at any zoom. Standard choice.
- deck.gl on top of MapLibre: H3HexagonLayer, HeatmapLayer, TripsLayer,
  built-in time-based transitions. This is what "watch the money move"
  needs. Recommended pairing.

**App framework**
- Vanilla JS (current): fine for one page; the views ahead want components,
  state and routing.
- SvelteKit: small bundles, simple reactivity, static adapter builds a
  pure-static site; good fit for map apps where DOM overhead matters.
- React (Vite or Next): largest ecosystem, deck.gl's first-party bindings
  are React, more people know it.
- Observable Framework: static data-app generator with data loaders and
  Plot built in; superb for dashboards, less so for a map-centric app with
  custom interaction.

**Charts**
- Observable Plot: concise, good defaults, works with any framework.
- Vega-Lite: declarative, more interaction built in, heavier.
- ECharts: everything, large.
- D3 directly: when a view is bespoke.

**In-browser data**
- DuckDB-WASM reading Parquet over HTTP range requests: arbitrary pivots
  with no server, ~5 MB of WASM up front. Worth it for the buyer × station ×
  time explorations; not for first paint.

**DP-5: SvelteKit + MapLibre + deck.gl + Observable Plot (recommended) vs.
React + the same map stack.** The map and chart choices are the same either
way; the app framework is the real question and is partly taste. deck.gl's
React bindings are a mild point for React; bundle size and simplicity are
points for Svelte. Either is fine; choose by who will be writing the UI.

**DP-6: adopt DuckDB-WASM for pivots** (yes, as a lazy-loaded "explore"
mode) vs. precomputing every pivot the UI offers.

### Layout

- Phone: map on top (45vh), a bottom sheet with tabs (Stations, Buyers,
  Ads, Over time). Desktop: map plus a 420px sidebar with the same tabs.
- Time scrubber docked on the map when a temporal layer is active; plays
  day-by-day from the first filing of the cycle to today.
- Layer picker: Coverage (contours), Money (hexes, $/person), Ads (hexes,
  spots/person), $/spot. One active density layer at a time.
- Every number carries its grain (booked / invoiced / aired) and the build
  date.

## Caching and scale

- Static artifacts behind a CDN (Cloudflare Pages or R2 + CDN, or S3 +
  CloudFront). Versioned paths, immutable cache headers.
- The only dynamic calls are geocoding and reverse geocoding. Options: a
  tiny edge function proxying a geocoder with a cache, or a self-hosted
  Pelias/Nominatim, or a US-only ZIP/place index shipped as a static file
  (covers most queries at zero cost). Recommend the static index plus a
  rate-limited fallback.
- Map tiles: PMTiles on the same bucket; basemap from Protomaps (also
  PMTiles, self-hostable) instead of OSM's tile servers.
- If an API appears later, it goes behind the CDN with ETags and short
  TTLs, and Postgres gets a read replica before anything else.

## Migration path from the pilot

1. Compose file with PostGIS; load the pilot SQLite into the ingest tables;
   point the pipeline at Postgres.
2. Add `buyer`, `buyer_alias`, `order_`, `order_revision`, `order_line`,
   `invoice`, `spot`, `creative` and populate from `document.raw`.
3. Load counties and build H3 cells with population; compute `station_hex`.
4. Build `spend_daily` and `hex_daily`; export JSON, Parquet and PMTiles.
5. New web app with the four views; keep the current page until parity.

## Decision points, collected

| | Question | Recommendation |
| --- | --- | --- |
| DP-1 | Static artifacts + CDN vs. live API | static; API only when a need appears |
| DP-2 | Time allocation of money | finest grain available; label the grain |
| DP-3 | Geography of money | contour coverage, population-weighted; label as "reaching" |
| DP-4 | Spatial unit | H3 (res 5 and 7) for density, contours for lookup |
| DP-5 | App framework | SvelteKit (or React if preferred); MapLibre + deck.gl + Plot regardless |
| DP-6 | In-browser pivots | DuckDB-WASM, lazy-loaded |
| DP-7 | Buyer identity | alias table + YAML overrides; FEC/FollowTheMoney IDs as they're matched |
| DP-8 | Ingest target | Postgres directly; SQLite only as the pilot loader |

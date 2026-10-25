# Adfall (originally TV Wormhole): proto-spec

Status: prototype (v0) built 2026-10-23. This document describes what v0 is,
what v1 should be, and what is deliberately out of scope. See
[research.md](research.md) for the evidence behind the choices.

## One sentence

Pick any spot in the US and see the local TV stations that reach it, with a
way to watch their newscasts and to follow the political money each station
is taking.

## Who it is for

- People who want to hear how the rest of the country sounds, one newscast at
  a time, without knowing station call signs.
- Reporters, researchers and campaign staff who need "which stations cover
  this county, and who is buying time on them" in one place.

## Goals and non-goals

Goals
- Location in, station list out, in one interaction, no account.
- Every link leads somewhere that works without a sign-up or cookie wall.
- Show the political-ad money trail per station, since the ads themselves
  are not on any stream.
- Run on a static host for near-zero cost.

Non-goals
- Never carry, proxy, re-stream or embed broadcast signals or station
  players. Link out only. (Aereo, Locast.)
- No attempt to show the actual broadcast ad breaks; they are not streamed.
- No accounts, no personalization, no tracking in v1.

## User flows

1. **Lookup.** Type a ZIP, address, city or `lat, lon`; or press locate; or
   click the map. The map drops a marker and draws the service contours of
   every station covering the point. The list shows full-power stations
   first, then Class A, each sorted by transmitter distance.
2. **Watch.** A station with an indexed stream has a primary "Watch" button
   that opens the stream in a new tab (NewsON today). Others get a search
   link until a better index exists.
3. **Follow the money.** "Political ad buys" opens the station's FCC public
   political file. "FCC file" opens the station profile.
4. **Share.** The URL hash carries the location, so a link reproduces the
   lookup.
5. **Filter.** "Only stations with a live stream" narrows the list.

## Data model

One static JSON file, `web/data/stations.json`:

```
{ "generated": "YYYY-MM-DD",
  "stations": [ {
    "call": "KCCI", "fac": 33710, "svc": "DTV" | "DCA",
    "city": "Des Moines", "state": "IA",
    "rf": "8", "vchan": "8", "erp": "44.6 kW", "licensee": "Hearst Properties Inc.",
    "tx": [lat, lon],
    "slug": "kcci",                       # publicfiles.fcc.gov/tv-profile/<slug>
    "bbox": [minLat, minLon, maxLat, maxLon],
    "polys": [ [[lat, lon], ...], ... ],  # 72 points + closing point; one per DTS site
    "newson": { "id": "6", "name": "KCCI - Des Moines/Ames", "logo": "..." }   # optional
  } ] }
```

Size today: 2,147 stations, 217 with NewsON entries, 3.2 MB uncompressed.

## Pipeline

`scripts/build_data.py` joins three inputs:

| Input | Source | Refresh |
| --- | --- | --- |
| Station list | FCC TV Query, per state, services DTV and DCA, licensed only | monthly is plenty |
| Contours | FCC `TV_service_contour_current.zip` | daily upstream; weekly is fine |
| Stream index | NewsON search API per state (`scripts/fetch_newson.py`) | weekly; unofficial API |

Join keys: TV Query column 39 (LMS application ID) to contour column 3.
NewsON matched by base call sign (strip `-TV`, `-DT`, `-CD`...).

## Architecture (v0)

- Static HTML, CSS and vanilla JS. Leaflet 1.9 for the map.
- Point-in-polygon runs in the browser: bounding-box prefilter, then ray
  casting over 72-point polygons. Sub-millisecond per lookup.
- Geocoding and reverse geocoding call Nominatim directly from the browser.
- Tiles from tile.openstreetmap.org.
- Served by any static file host. Dev: `python3 -m http.server 8765 --directory web`.

## v1 plan

Must
- **Own geocoder and tiles.** Nominatim and OSM tiles forbid production use
  at scale. Options: Protomaps or MapTiler for tiles; Census Geocoder (free,
  US, addresses) plus a ZIP centroid table for ZIPs; or a hosted Nominatim.
- **Network affiliation** on each card (ABC, CBS, NBC, FOX, PBS, other).
  Source still open: LMS facility table (blocked to scripts), Wikipedia
  station lists, or a one-time manual download kept in the repo.
- **Broader stream index.** Add Zeam (Gray, plus the NewsON catalog) and the
  network city pickers (NBC, CBS, FOX) so Nexstar, Gray and Sinclair stations
  stop showing "Find stream". Store the stream URL per station with a source
  tag and a last-checked date.
- **Political file summary.** Fetch each station's political-file folder
  listing (public) and show document counts by year and the most recent
  upload date on the card, so the card itself says "this station has 1,893
  political documents this year, last one today".

Should
- **Postgres behind the data.** The ingest pipeline writes SQLite for the
  pilot. Once the full crawl exists, move `files` and `docs` to Postgres via
  docker compose (one `postgres` service, a volume, a loader that reads the
  SQLite or writes directly) so pivots and visualizations can run real SQL.
  Keep the schema identical in both; `ingest/db.py` is the only place that
  knows the engine. DuckDB over the SQLite file is a zero-setup bridge for
  analysis in the meantime.
- **Market view.** Group results by Nielsen DMA and offer "whole market" as
  an alternative to point coverage.
- **Newscast schedule.** NewsON's station detail already lists live and
  recent programs; show "live now" or "next newscast at 5:00 pm CT" on the
  card.
- **Keyboard channel flipping.** Up/down to move through the list,
  left/right to jump between saved locations. The "wormhole" feel.
- **Pre-computed lookups.** Serve a vector tile or a county-level index so
  the client does not download 3 MB up front on mobile.

Could
- Parse political file PDFs into buyer, dates and dollars (hard; see
  research). Start with the FCC's own order-form PDFs, which are the most
  uniform.
- Pair each station's ad buyers with the campaigns' own YouTube uploads of
  the spots.
- Local radio (FCC publishes FM contours in the same format).

## Risks

| Risk | Mitigation |
| --- | --- |
| NewsON API or URL scheme changes | Store last-known-good links; nightly link check; multiple stream sources |
| FCC changes TV Query or contour formats | Both are decades old; pin column indexes with a test row |
| Nominatim or OSM rate limits during an election spike | Replace before launch (v1 must) |
| Station terms of use objection to deep links | Links are plain links to public pages; no framing, no scraping of video |
| Contours mislead users about actual reception | Already labeled "predicted"; keep it |

## Success criteria for v1

- Any US ZIP returns the correct full-power stations for that market, with
  affiliation, in under one second on a phone.
- At least 80% of full-power commercial stations in the top 100 markets have
  a working "Watch" link.
- Every station card shows a political-file count and last-upload date.
- Hosting cost under $20 per month at 10,000 lookups a day.

## Political-file ingest (added 2026-10-24)

Pipeline, all under `ingest/`, state in Postgres (see docs/design.md), PDFs under
`data/pdfs/<facility>/<year>/`, OCR text under `data/ocr/`:

| Step | Module | What it does |
| --- | --- | --- |
| crawl | `ingest.crawl` | walks `Political Files/<year>` per station via the OPIF API, records every file, downloads PDFs (resumable) |
| update | `ingest.update` | applies the global file-history feed (new/delete/move/rename/purge) from the last sync date; the daily delta mechanism |
| ocr | `ingest.ocr` | pypdfium2 render + tesseract for PDFs with no text layer; cached per file |
| parse | `ingest.parse` | classifies each PDF and extracts order number, advertiser, agency, flight, gross, net, spots, per-spot Ad-IDs, PB-19 form fields |
| aggregate | `ingest.aggregate` | spend per station per buyer; exports `web/data/spend/<facility>.json` and `index.json` |

Templates seen so far
- **WideOrbit text PDFs** (Hearst, Tegna): orders and invoices parse at ~99%.
- **WideOrbit image PDFs** (Nexstar): same layout printed to image; OCR then a
  tolerant regex set. Totals sit on an inner page.
- **Katz/Sinclair contracts** (Sinclair): image PDFs with inline labels
  (`Contract #`, `Advertiser:`, `Total $:`, `Flight:`).
- **NAB PB-19 / issue-ad forms**: AcroForm fields; candidate, committee,
  agency, party, office, election date, treasurer, sponsor.

Spend rule: per order number, sum of invoices if any exist (what aired), else
the latest order revision's gross (what was booked). Cancellations are $0
orders. Both figures are kept so "booked vs invoiced" is visible; invoices lag
airing by a billing cycle, so invoiced totals keep rising into December.

Keeping it current: run `python3 -m ingest.update --download --parse --aggregate`
daily from cron or launchd. Orders keep arriving through election day and
invoices for a month after.

## Visualizations to build next

- **Spenders**: ranked buyers per station and per location, split
  federal / state / local / issue; already in the map cards.
- **Spend per person**: population inside each contour from the Census
  Gazetteer county file (population + centroid, public domain), centroids
  summed inside the polygon. Directional by design; no Nielsen DMA data.
- **Ads actually aired**: Ad-ID creative codes from invoices with air date and
  time. Rank creatives by airings per station or buyer; a word cloud or ranked
  list. The four-character Ad-ID prefix identifies the advertiser company.
  Video lives on campaigns' YouTube channels, not in the FCC file.
- **Who the buyers are**: join committee names from PB-19 forms to OpenFEC
  (federal committees, donors), FollowTheMoney (state candidates) and
  OpenSecrets (PACs, outside groups). Agency names on orders cluster buyers
  by consultant.
- **Postgres** once the crawl goes beyond the pilot, via docker compose, so
  these pivots are plain SQL.

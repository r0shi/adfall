# Research log

Feasibility pass done 2026-10-23, eleven days before the midterm election.
This records what was checked, what was found, and what tripped us up, so
nobody has to rediscover it.

## The question

A podcast guest said the way to understand the country is to watch local
newscasts around it, including the local political ads. Idea: a map of the US
where you pick a spot, see which stations reach it, and watch them. Before
building: is it done already, is it legal, is it practical, could it pay for
its own hosting?

## Short answers

| Question | Answer |
| --- | --- |
| Done already? | The "watch any market's newscast" half: yes, NewsON and Zeam. The coverage-map half: no. |
| Legal? | Linking to station-run streams: yes. Retransmitting the broadcast signal: no, settled law. |
| Political ads visible on streams? | No. Verified live. Ad breaks are replaced with a slate or digital ads. |
| Self-funding? | A link-out site costs almost nothing to run. Revenue is plausible only as a niche paid tool. |

## Prior art

- **NewsON** (newson.us). Free, no login, web plus iOS, Android, Roku. About 285
  stations. Any market viewable from anywhere in the US; it located us by IP in
  New York and played Atlanta two clicks later. Sinclair sold it to Zeam in
  August 2025. Branded "NewsON, Powered by Zeam".
- **Zeam** (zeam.com). Owned by Zeam Media and Gray. Deals with Gray, Tegna, CBS
  stations and smaller groups. With NewsON folded in, claims every measured
  market. Finds stations by your location; no browse-by-map.
- **Haystack News, Local Now.** Aggregators with a local-news slice. Location
  driven, not map driven.
- **Network city pickers.** NBC News Watch, CBS Local, LiveNOW from FOX each
  list their own stations by city.
- **TV Garden** (tv.garden, renamed Famelack in 2026). The globe-of-channels UI
  the idea was reaching for, but sourced from community IPTV lists, not
  affiliate newscasts. tv.garden now 301-redirects to famelack.com.
- **RabbitEars Signal Search Map, FCC DTV Reception Map, AntennaWeb.** Solve
  "what can I receive here" for antenna buyers. No link to streams or ads.
- **Internet Archive Political TV Ad Archive.** Recorded local TV ads in about
  20 markets in 2016. Not active for recent cycles.
- **AdImpact.** Commercial. Spend, placement and a catalog of 1.6 million
  creatives across all 210 markets. Wesleyan Media Project switched to it as
  their data source in 2025. No published pricing.

Nothing combines a coverage map, stream links and the political-ad money
trail. That combination is the only open slot.

## Legal picture

- **Aereo** (Supreme Court, 2014): capturing broadcast signals and streaming
  them to subscribers is a public performance; infringing.
- **Locast** (SDNY, 2021): a nonprofit that geofenced streams to the home
  market lost because its donation nags made it not truly free under the
  Section 111 exemption. $32M consent judgment, permanent injunction.
- **LocalBTV / Didja**: did it with station consent and geofencing, went dark
  in November 2023 and has not returned.
- Conclusion: never touch the broadcast signal. Only station-produced streams
  that the station itself publishes, by link, or by license.
- Station terms of use: Gray's terms (republished on every Gray site) only
  disclaim framed third-party sites; nothing seen that explicitly permits
  framing. Most station players set frame-blocking headers anyway. Treat
  iframe embedding as unavailable; link out.
- Geo-restriction: none observed inside the US. NewsON streams from any state
  to any state. Some station streams block non-US IPs.

## The ad finding, with evidence

Watched WXIA Atlanta's live afternoon newscast on NewsON from a New York IP.
At the commercial break the player showed a static "11Alive+" slate for more
than two minutes, then returned to the newscast. The stream manifest came from
`vinson-newson-vsms.triple-it.nl` (Triple IT's server-side ad-insertion
platform) with a discontinuity sequence in the thousands, while media segments
came from the station's own origin at `newson.11alive.com`. So the station
feeds its program, and the platform cuts the breaks and fills them (or not)
with digital inventory.

Why, per industry reporting: broadcast spots are sold with broadcast rights
only, so stations cannot stream them; digital rights are a separate
negotiation; local spots are not loaded into digital feeds at all. Political
buys are the same as any other local buy.

Implication: the "see the local political ads" goal cannot be met by any
stream. The substitute is the FCC political file, which every station must
keep: who bought, what dates, how much, which programs. That data exists for
every station in the dataset.

## Data sources that worked

### FCC TV Query (station list)

Pipe-delimited export, one request per state and service:

```
https://transition.fcc.gov/fcc-bin/tvq?state=IA&serv=DTV&vac=3&list=4&size=9
```

`serv=DTV` is full power (1,752 licensed), `serv=DCA` is Class A (397).
Columns, 0-indexed after the leading empty field:

| Index | Field |
| --- | --- |
| 1 | call sign (e.g. `WOI-DT`, `KCCI`, `WXIA-TV`) |
| 3 | service code |
| 4 | RF channel |
| 9 | status (`LIC` = licensed) |
| 10, 11 | community of license city, state |
| 13 | LMS file number |
| 14 | ERP |
| 16 | HAAT |
| 18 | facility ID |
| 19–26 | transmitter lat/lon as N/S deg min sec, W/E deg min sec |
| 27 | licensee |
| 37 | application ID (matches the contour file's first column; `0` for 496 stations) |
| 38 | virtual channel (`-` for some Class A) |
| 39 | LMS application ID, 32 hex chars (matches the contour file's third column; always present) |

No network affiliation in this export.

### FCC TV service contour points

```
https://transition.fcc.gov/bureaus/mb/databases/map/TV_service_contour_current.zip
```

Updated daily around 10:00 Eastern. 27 MB zipped, 87 MB text, 11,397 records.
Header then one 7,633-character line per record:
`application_id|service|lms_application_id|dts_site_number|transmitter_site|0|1|...|359|^|`
with a `lat ,lon` pair per azimuth degree. F(50,90) noise-limited service
contour. "No restrictions are set on the use of this data." Includes LPTV
and translators (`LPD`, `LPT`), full power (`DTV`), Class A (`DCA`), DTS sites
(`DTS`). One record per DTS transmitter site, so group by application.

Join on `lms_application_id`, not `application_id`: 2,147 of 2,148 stations
match. The capitalized URL printed on the FCC page returns 403; the lowercase
path above works.

### NewsON API

Discovered from the web app's network calls. Unofficial, no key.

```
https://newson-api.triple-it.nl/v5api/search?query=Iowa&platformType=website
https://newson-api.triple-it.nl/v5api/detail/station/259?platformType=website
```

Searching each state name returns that state's stations (278 total, 216 of
them broadcast call signs after dropping radio and cable channels). Station
page URL is `https://www.newson.us/stationDetails/{id}`. Treat this as
scrape-grade: it can change without notice.

### FCC public inspection files

Profile URL is the call sign lowercased, suffix included:
`https://publicfiles.fcc.gov/tv-profile/woi-dt`, `/kcci`, `/wxia-tv`,
`/kdit-cd`. All slugs tested resolved. Political files live under
`/political-files`, with year folders; KCCI's 2026 folder held 1,893 entries.

### Geocoding

Nominatim (`nominatim.openstreetmap.org/search`, `/reverse`) with
`countrycodes=us`. Handles ZIPs, addresses, city names. Free, with a usage
policy that forbids heavy use; fine for a prototype, not for production.

## Data sources that did not work

- **LMS bulk database** (`enterpriseefiling.fcc.gov/dataentry/api/download/dbfile/...`).
  The only public source of network affiliation. Akamai returns 403 to every
  scripted request tried, with or without browser-like headers. Would need a
  real browser session or a different source (Wikipedia station lists, or a
  one-time manual download).
- **FCC contours API** (`geo.fcc.gov/api/contours/`). `coverage.json`
  demands `serviceType`, then `nradial`, and was not pursued further;
  `entity.json` returned a Postgres "CONNECT privilege" error. The bulk file is
  better anyway.
- **publicfiles.fcc.gov JSON API** (`/api/service/tv/facility/search/{term}.json`).
  Responds, but returned no results for any call sign tried. The profile
  pages are server-rendered with no XHR to copy.
- **fcc.gov HTML pages** return 403 to curl without a browser User-Agent; with
  one they work.
- **TV Query column key page** (`/media/radio/am-fm-tv-textlist-key`) did not
  parse usefully; columns above were determined empirically.
- **NewsON `/terms`** is a 404; terms are hosted by Zeam.
- **publicfiles.fcc.gov year deep links** (`/political-files/2026`) render an
  empty table when opened directly, though the folder has data. Link to the
  `/political-files` root.

## Pitfalls and gotchas

- The contour file's first column is `0` for about a quarter of stations.
  Joining on it quietly produced a 1.3 GB JSON with hundreds of polygons per
  station before the LMS id join was used.
- A station's licensee string is all caps in TV Query. `str.title()` turns
  `LLC` into `Llc`, `II` into `Ii`. Keep a small set of tokens uppercase.
- Class A stations sort before full power if sorted by service code string
  (`DCA` < `DTV`). Rank explicitly.
- Hash-only navigation in the browser does not reload scripts. Bust the
  cache with a query string when testing.
- NewsON's site serves a mobile-only landing page below about 800 px width.
- `tv.garden` is now `famelack.com`; links in older articles redirect.
- NewsON's station IDs are not call signs; "WSB Radio" and "News 12" cable
  channels are in the same list and must be filtered.
- Contour simplification to every fifth azimuth (72 points) keeps the data
  at 3.2 MB for 2,147 stations with no visible loss at state zoom.

## Monetization view

Infra for a link-out site is a static host and a few MB of data. Nominatim
and OSM tiles must be replaced before any real traffic (both have usage
policies). Plausible revenue is a small paid tier for journalists, campaign
staff and political obsessives, strongest in the final weeks of a cycle.
Ads on a political-research tool are a poor fit. The incumbents own the
streams and have no incentive to build the money-trail layer, which is the
part that would be ours.

## Open questions

- Is there a legitimate bulk route to network affiliation?
- Does Zeam have a public station directory to supplement NewsON for Gray,
  Nexstar and Sinclair stations?
- How far can the political file be parsed? Buys are PDFs of varying shape;
  ProPublica crowdsourced this in 2012 and Wesleyan licenses commercial data
  rather than parsing it.
- Would AdImpact license creative metadata to a small product at any price?

## Political file deep dive (2026-10-23, evening)

Question: can the FCC political files be bulk-downloaded legally, and how big
are they? Short answer: yes, and about 400,000 PDFs per election year for
full-power TV, roughly 150 GB.

### Legal and terms

- The files are public records that stations must keep under 47 CFR 73.1943
  and 73.3526. The FCC hosts them and publishes the API it built the site on
  (`publicfiles.fcc.gov/developer`), "free for use by anyone" under the FCC
  API terms. The terms require the notice "This product uses the FCC Data API
  but is not endorsed or certified by the FCC", allow commercial use, and
  reserve a right to rate-limit or block abusive use.
- There is no robots.txt (the path returns the site's error page).
- Precedent for bulk use: ProPublica Free the Files (2012), Sunlight's
  Political Ad Sleuth, Center for Responsive Politics Ad Data (2016), the
  Internet Archive, Wesleyan Media Project.
- The documents contain agency contact names, phone numbers and signatures.
  Low sensitivity, but worth not indexing by person.

### The API, as actually used

Base `https://publicfiles.fcc.gov/api/manager`. All GET, JSON, no key.

| Call | Purpose |
| --- | --- |
| `folder/path.json?entityId=<facility>&sourceService=tv&folderPath=Political Files/2026` | folder id for a station-year |
| `folder/id/<folderId>.json?entityId=<facility>&sourceService=tv` | subfolders, files (with `file_size`, `file_manager_id`, `create_ts`) and `file_count` for the subtree |
| `file/history.json?startDate=&endDate=&count=500&offset=` | every file added, deleted, moved or purged across **all** stations and services in a date range, with path, size, callsign and licensee. The incremental-sync primitive. |
| `https://files.fcc.gov/download/<file_manager_id>.pdf` | the PDF itself (the `api/manager/download/<folder>/<file>.pdf` form 302s here) |

Pitfalls
- The edge (Akamai) returns 403 to Python `urllib` even with a browser
  User-Agent, while curl with the same header works. Shell out to curl or
  use a client with a browser-like TLS/header profile.
- `file/history` with `count=5000` returns 503; 500 per page is safe. A
  single day's listing can run to 14,000 rows (29 pages). `sourceService` is
  ignored on this endpoint.
- Results for 2026-10-22 came back dominated by `purge` rows and truncated by
  a server error at page 6; treat per-day totals as approximate.
- `folder/path` returns `file_count: null`; `folder/id` on the same folder
  returns the real count.

### Volume, measured

Per-station folder counts for all 1,750 licensed full-power stations
(`data/political_doc_counts.csv`, 7,000 API calls, 17 minutes with 6 workers):

| | 2024 (full year) | 2026 (through Oct 23) |
| --- | --- | --- |
| Documents, full-power TV | 408,081 | 410,345 |
| Mean / median per station | 234 / 51 | 234 / 72 |
| 90th percentile station | 779 | 722 |
| Busiest station | KYW-TV Philadelphia, 3,401 | 2,864 |
| Stations with zero | 638 | 652 |
| Top 100 stations' share | 37% | 31% |
| Top 500 stations' share | 87% | 83% |

2024 by state: PA 42.5k, MI 28.1k, WI 26.6k, OH 22.7k, NC 22.4k, TX 21.5k.
Swing states dominate, as expected.

File sizes, from a full walk of KCCI's 2026 folder (1,913 PDFs, 88 folder
calls): total 520 MB, mean 272 KB, median 123 KB, max 13.7 MB. From one
peak day in 2024 across all services: mean 465 KB, median 250 KB. Every file
sampled was a PDF.

Estimates that follow
- One election year, full-power TV only: ~400k PDFs, 120 to 190 GB. Extracted
  text ~4 GB, metadata under 1 GB.
- All services (cable, radio, DBS, LPTV): TV was 28% of new political
  documents on the 2024 peak day, so roughly 1.4M documents and 500 to 650 GB
  per election year.
- Everything since the online file began (2012 for TV): several TB across all
  services; 1 to 2 TB for TV alone.
- Crawl cost: about one folder call per 22 documents, so a full TV year is
  ~19k listing calls (1 to 2 hours) plus 400k downloads (overnight at a
  polite rate). Daily upkeep via `file/history` is a few thousand rows.

### Granularity and parseability

- Documents per contract: KCCI's 1,913 files collapse to ~1,017 distinct
  order numbers. Kinds: 606 orders/contracts, 516 invoices, 488 NAB PB-19
  disclosure forms, 266 revisions, 37 cancellations.
- **Orders and invoices** are WideOrbit/traffic-system PDFs with a text layer.
  They carry advertiser, agency, product, flight dates, demographic, total
  ratings, and per-line program, daypart, spots, rate and amount. Invoices
  add **per-spot air date, air time and the Ad-ID creative code**
  (e.g. `JTFI2000HW1`). That is the link from dollars to a specific ad.
- **NAB PB-19 forms** are fillable PDFs whose values live in AcroForm fields,
  not page text: candidate, committee, agency, party, office sought, election
  date, treasurer, signatories. `pypdf.get_fields()` reads them directly.
- All 17 sampled PDFs had text layers. Scanned documents exist in the corpus
  (the 13.7 MB outlier is probably one) but are a minority; OCR is a
  long-tail job, not the main path.
- Parsing plan: deterministic parsers for the two or three dominant traffic
  system layouts (WideOrbit is the big one), form-field extraction for
  PB-19s, and an LLM only for the residue that fails validation (totals that
  don't sum, missing flight dates). A full year is on the order of a billion
  tokens if every page went to a model, so routing matters.
- Ad-ID lookup: the registry's search needs an account; no free public API.
  The code still clusters spend by creative, and the same code appears in
  CTV/online ad tags, which is a path to the video.

### Normalizing to people

For $/person, use population inside the station's contour: sum Census
block-group populations (ACS 5-year, TIGER centroids, both public domain)
whose centroids fall inside the polygon. That avoids Nielsen DMA boundaries,
which are proprietary. Counties-to-DMA crosswalks circulate but their
licensing is unclear.

## Ingest pilot: Des Moines, 2026 (2026-10-24)

Five commercial full-power stations, all 2026 political files: 5,892 PDFs,
about 1.6 GB, crawled in 25 minutes with 4 download workers.

| Station | Group | Docs | Booked (orders) | Invoiced | Buyers |
| --- | --- | --- | --- | --- | --- |
| KCCI | Hearst | 1,913 | $40.2M | $16.9M | 77 |
| WHO-DT | Nexstar | 1,410 | $35.4M | $12.8M | 69 |
| WOI-DT | Tegna | 1,223 | $9.8M | $6.1M | 71 |
| KDSM-TV | Sinclair | 998 | $7.9M | (invoices unlinked) | 65 |
| KCWI-TV | Tegna | 348 | $0.35M | $0.12M | 27 |

Total booked: $93.6M, eleven days before the election, orders still arriving.
Top buyers at KCCI: WinSenate $3.0M, Rob Sand for Governor $3.0M, Senate
Leadership Fund $2.7M, Congressional Leadership Fund $2.3M, VoteVets $2.3M.
Single largest order: $656,000 for eight NFL and Big Ten spots in the final
week (Lower Costs Now).

### Parse coverage

| Kind | OK | Partial | Failed |
| --- | --- | --- | --- |
| Orders | 3,101 | 80 | 7 |
| Invoices | 1,692 | 2 | 0 |
| PB-19 forms | 449 | 0 | 134 |
| Other / unrecognized | 417 | | |

Over 90% of documents parse. The 134 failed forms are image-only forms with
no AcroForm fields; they carry no dollar amounts. The 417 "other" are mostly
NAB supplements, rebate forms and station certifications.

### What each station group files

- **Hearst, Tegna**: WideOrbit orders and invoices as text PDFs. Parse rate
  about 99%. Invoices list each aired spot with Ad-ID.
- **Nexstar**: the same WideOrbit documents printed to image-only PDFs. OCR
  (pypdfium2 at ~160 dpi, tesseract psm 6) then tolerant regexes: the
  advertiser is prefixed `POL/`, the slash in "Contract / Revision" reads as
  7 or |, decimal points sometimes read as colons, a ratings number sometimes
  precedes the spot count on the Totals line. 1,006 of 1,076 OCR'd orders
  parsed with an amount. Invoices are text PDFs.
- **Sinclair**: Katz contracts as image PDFs (inline labels: `Contract #`,
  `Advertiser:`, `Total $:`, `Flight:`), a few ePort revision summaries, and
  text-PDF "OFFICIAL BILLING INVOICE" documents whose header values
  (advertiser, invoice and contract numbers, period) are not in the text
  layer, only the totals and per-spot lines. The invoice's contract number is
  a Sinclair number, not the Katz contract number, so invoices cannot be
  linked to orders; they are reported separately as unlinked invoiced
  amounts. KDSM's invoice Ad-IDs are still captured.

### OCR cost

1,939 image PDFs took about 70 minutes on 8 cores (M-series Mac), ~2 seconds
per page. For a national crawl, roughly a third of documents will need OCR;
budget a few hundred CPU-hours per election year, or route only the first
and totals pages.

### Creatives

Distinct Ad-ID codes seen on invoices: KCCI 1,867, WOI 2,376, WHO 453, KCWI
450, KDSM 25 (its invoices use short internal codes). The most-aired
creatives at KCCI ran 45 times each in a billing month. Ad-ID prefixes group
by advertiser (e.g. `RSFI` = Rob Sand for Iowa, `ONIA` = One Iowa).

### Pitfalls found here

- Buyer folders differ in depth by station group: Hearst files
  `Federal/US House/<candidate>`, Tegna adds `FLIGHT <dates>` leaf folders,
  Sinclair uses `State/<candidate>`. The aggregator strips office-level
  folders above the buyer and flight folders below it.
- `str.title()` on licensee and folder names is lossy; keep the station's own
  capitalization for buyers.
- Orders are revised often: 1,034 KCCI order documents collapse to ~650
  order numbers. Take the latest print date per order number; never sum
  revisions.
- pypdf parsing runs about 8 PDFs per second; OCR is the real cost.

## Buyer identity (2026-10-24)

Problem: each station labels buyers its own way. Across the first 200
stations, 2,411 distinct folder labels described far fewer real buyers:
Abdul El-Sayed appeared under 28 spellings ("Abdul DSCC", "ABDUL EL-SAYED
DEM", "Abdul for US Senate"...), Mike Rogers under 26, Roy Cooper under 17.

Approach (`ingest/identity.py`), in order:

1. **Manual overrides** from `data/buyer_overrides.yaml` (`label: Canonical`
   or `category|label: Canonical`). Empty so far; this is where corrections go.
2. **FEC candidate match** for federal labels. Tokens left after stripping
   party committees (DCCC, NRSC...), office words, state names and
   order-number noise are compared with the FEC candidate master for the
   cycle, restricted to the station's state unless the label names another
   state ("Keith Gross for Florida"). Evidence tiers: two name tokens
   overlap, or a multi-word surname (strong); surname exact or fuzzy ≥ 88
   (medium); label's first token equals the candidate's first name and the
   second token resembles the surname (weak). Ties between different people
   are left unmatched; ties between two filings of the same person (House
   incumbent running for Senate) are broken by the office in the label.
3. **FEC committee match** for issue groups and unmatched federal labels:
   token-sort fuzzy match ≥ 93 against 20,950 committee names.
4. **Name rule** for everything else: the stripped name tokens, title-cased,
   merged within category. Handles "Josh Shapiro-D- Governor" / "JOSH
   SHAPIRO FOR GOVERNOR-D" / "Josh Shapiro" without any registry.

Result on the current corpus (200 stations): 2,505 labels → 1,228 buyers,
496 of them merged from two or more labels. By method: 1,689 labels by
name rule, 523 to FEC candidates, 287 to FEC committees, 6 manual. A
surname-and-nickname clustering pass (same category and state, one
distinct first name allowing Rick/Richard, Josh/Joshua) merged 71 more
buyers, e.g. "Rick Jackson" / "Richard Jackson" / "Jackson" into one
$89M Georgia governor buyer. The top federal
buyers all resolve to FEC candidate IDs with their familiar names (Jon
Ossoff $22.1M, Roy Cooper $20.0M, Abdul El-Sayed $7.7M, Mike Rogers $5.9M,
Ashley Hinson $4.6M across the stations crawled so far).

Folder parsing matters as much as matching: some stations nest an office
level ("Federal/House of Representatives/<candidate>"), which had been
read as a buyer called "House of Representatives" holding 30 campaigns.
The rule is now: an intermediate folder with no name tokens, or a county /
city / school-district folder, is a level above the buyer; a leaf keeps
its name.

FEC naming surprise: the 2026 committee master lists the big super PACs
under short legal names (HMP, CLF, SLF PAC, SMP). The overrides file maps
`fec C00495028: House Majority PAC` so the id attaches and the familiar
name displays; labels like "SLF" and "CLF26" map there too.

Sources: FEC bulk master files `cn26`, `cm26`, `ccl26` from
fec.gov/files/bulk-downloads/2026/ (redirect to S3; follow it). No key, no
rate limit, refreshed weekly by the FEC. The OpenFEC API needs an api.data.gov
key and was not needed.

Known limits
- State and local candidates have no registry here; the name rule merges
  spellings but cannot confirm identity. FollowTheMoney (NIMSP) has an API
  with a key if that becomes worth it.
- "Michigan Victory Fund - Rogers" is a joint fundraising committee buying
  for Rogers; it is merged into the candidate, which is what a reader wants
  but not what the FEC filing says. The alias row keeps the original label.
- Agencies occasionally appear as buyers because a station filed under the
  agency name ("MHB Media 841287 7-21-2026"). Override material.
- FEC names are legal names: "Jonathan Ossoff", "Michael Rogers". Display
  nicknames are a later nicety.

## Pipeline hardening (2026-10-24, night)

Audit of every ingest stage for silent failures, then a rebuild of the plumbing so nothing can
fail quietly, everything resumes after a kill, and `make status` shows the whole picture. The
parsers were validated and extended, and the national 2026 crawl was launched (see the next
section for numbers and the operations notes for how to watch it).

### What was failing silently before

| Stage | Problem found | Fix |
| --- | --- | --- |
| crawl | A folder walk that died mid-way left the station looking "listed"; re-runs skipped it forever. | `listing` table per station-year: complete / partial / failed / empty. Partial walks are redone. The API's own `file_count` is recorded and compared. |
| crawl | A download that failed was simply not marked downloaded; no reason, no count, retried on every run. 54 files were in this state with no record of why. | `download_attempts` / `download_error` per file, retried up to 5 times then reported as given up (`crawl --retry-given-up` resets). Counts of ok/failed/adopted in the summary. |
| crawl | A killed `curl` could leave a half-written PDF that `exists and size > 0` accepted. | Downloads go to `.part`, are checked for a `%PDF` header and a trailer, hashed (sha256), then renamed. Files on disk but unmarked (killed between curl and the DB write) are verified and adopted. |
| crawl | The FCC's listed `file_size` does not match the bytes served for 99.6% of files, so a size check against the listing is useless. | `local_size` records the real size; `crawl --verify` re-checks files on disk. |
| crawl | A file the FCC answers with 401/404/410 (removed or restricted by the station) was retried five times and, when it was the only work left for a state, its failures alone failed the state (seen on CA after the Postgres cutover: 23 such files, 0 other work). | Given up on the first attempt, counted as `downloads_gone`, listed by `ingest.status` as given up, not counted as a stage failure. |
| crawl | A blocked edge (403, 503 storms) produced thousands of quick failures. | Backoff on 429/503, stop on 403; 25 consecutive download failures pause two minutes, 150 abort the stage as failed. |
| update | A day whose feed could not be read stopped the run but the sync marker could still move; errors went to stderr only. | The marker advances only through days that were applied; failures are recorded per day. |
| ocr | Errors were printed and forgotten; the same broken PDF was retried on every run; a document with 20 pages was cut at 12 and lost its totals page. | `ocr` ledger table (engine, status, attempts, pages, seconds, error), three attempts then given up and listed by status; when a document exceeds the page cap the first pages plus the last two are read. |
| parse | 244 documents failed with "cryptography>=3.1 is required for AES" (missing dependency), recorded only as a per-document error string. kind=other documents were stored with `parse_status=ok`, so 32k unrecognised documents counted as successes. pypdf's "Ignoring wrong pointing object" flooded the logs. | `cryptography` is a requirement; parser crashes are counted and fail the stage above a threshold; unrecognised documents get `parse_status=unrecognized`; pypdf's logger is silenced. |
| crawl | Files for stations missing from `stations.json` were dropped without a count (in `load_pg`). | The crawl refuses stations that are not in the `station` table and reports each as a failure; `make stations` loads the list. |
| entities | Could "succeed" with zero orders if upstream broke. | Fails if documents exist but no orders were built. |
| scripts/*.sh | `>> log` without exit codes; polled a log file for a sentinel; could print "done" with stages skipped. | Replaced by `ingest.batch` (per-stage exit codes, run ledger, resume). |
| all | No locks, no run history, counts only on stderr. | `ingest.runlog.Stage`: `data/logs/<stage>-<ts>.log` + stderr, `pipeline_run` row in Postgres, per-stage lock in `data/locks/`, non-zero exit above a failure threshold, dead "running" rows marked killed on the next run. |

### Operations

- `make status` prints files listed / downloaded / pending / given up, parse counts by
  kind, template and status, OCR done / pending / failed, Postgres entity counts, the last run
  of every stage with its counts and log path, which stages hold a lock right now, and a
  problems list (given-up downloads, OCR failures, partial listings, failed stages, stale
  running rows). `make status STATE=TX` adds a per-station table sorted by pending work.
- `make coverage` compares the local store with `data/political_doc_counts.csv` (the national
  per-station counts for 2024 and 2026) by state and year; `MISSING=1` lists uncrawled
  stations, biggest first.
- `make validate` runs the parse invariants over `document.raw` in Postgres and prints failure
  rates per template with the worst examples and their file ids (`data/pdfs/<fac>/<year>/<id>.pdf`).
- Logs: `data/logs/<stage>-<timestamp>.log`. Every stage ends with one line
  `== SUMMARY stage=... status=OK|FAILED elapsed=... failures=N <counts> log=...`.
  `grep SUMMARY data/logs/*.log` is the run history in one screen.
- Locks: `data/locks/<stage>.lock` holds `pid N since <time>`; a second instance of the same
  stage exits immediately with the holder's pid. The batch driver holds `pipeline.lock`.
- National crawl: `make batch` runs `ingest.batch` detached. For each state in
  `data/crawl_targets_2026_national.txt` (53 states, 1,098 stations with 2026 documents,
  biggest states first): crawl (list + download, 6 workers) -> parse -> ocr (Vision, 4 workers)
  -> parse --only-failed, then the entity refresh (entities, identity, entities, marts) in a
  background thread while the next state downloads. Follow it with
  `tail -f data/logs/batch-*.log` (one line per stage per state, with ETA) or `make status`.
- Resume: rerun `make batch`. States with an ok `batch_state` run are skipped; inside a state
  the crawl skips complete listings and pending downloads only, OCR skips cached text, parse
  skips documents already at the current parser version. Kill with `kill <pid>` from the lock
  file; nothing needs cleaning up. `--all` redoes finished states (cheap), `--states TX,OH`
  picks a subset.
- Daily upkeep after the crawl: `make update` applies the FCC change feed since the last sync
  (adds, deletes, moves) and downloads new files; then `make parse`, `make ocr`, `make parse`,
  `make refresh`, and the owner's `make export`.
- Postgres migrations: `make migrate`, with no stage running: an `ALTER TABLE` waits for every open
  transaction on the table (entities holds one for minutes by design) and, while it waits, queues
  readers such as a mart refresh behind it. Every stage checks `schema_migrations` against
  `db/migrations/` on connect and refuses to run against a schema that is behind.

### OCR engine choice

Benchmark on 48 image-only PDFs (214 pages: WideOrbit contract scans, Katz contracts, scanned
NAB forms, unrecognised scans), single process, M-series Mac, 10 cores:

| Engine | Render scale | s/page | Order numbers found | Totals found | Notes |
| --- | --- | --- | --- | --- | --- |
| tesseract 5.5 psm 6 | 2.2 (~160 dpi) | 0.98 | 32 / 32 | 32 / 32 | baseline; garbage on rotated pages |
| Apple Vision (ocrmac) accurate | 2.2 | 0.41 | 32 / 32 | 32 / 32 | |
| Apple Vision accurate | 1.5 | **0.21** | 32 / 32 | 32 / 32 | chosen |
| Apple Vision fast | 1.5 | 0.16 | 0 / 32 | 0 / 32 | unusable |
| Apple Vision accurate | 1.0 | 0.15 | 26 / 32 | 24 / 32 | too lossy |

With 4 worker processes Vision reaches 0.09 wall-seconds per page (11 pages/s); 8 workers
give 0.08, so it saturates at four (the Neural Engine is the shared resource). Vision read
four landscape-rotated contracts that tesseract had turned into noise, found advertisers on
six more documents, and produces cleaner header lines. Two quirks: it writes thousands
separators as periods ("$22.525.00") and appends stray glyphs (ł, ą, Ạ) to digits; the OCR
stage strips non-Latin-1 characters and the money parser treats the last separator as the
decimal point. Image-only documents average 4.0 pages, so the national load of roughly 110k
image PDFs is about 440k pages, or 11 hours of OCR at 4 workers, running alongside the
downloads. Tesseract would have needed about 120 hours of CPU. The cached tesseract text
from the first crawl (24.8k documents) is still used; `ocr --redo-legacy` re-reads those with
Vision and `parse --only-failed` picks up any document whose OCR is newer than its parse.

### Parser v5: layouts found by clustering the unrecognised documents

Clustering the 32k `kind=other` and 14k failed forms by station group and the first words of
their text gave a short list of layouts, in order of size:

1. **WideOrbit "Order" print** (text): header `Order / Rev:`, `Flight Dates:`, `Estimate:`,
   values in a block after `Original Date / Rev:`. Gray, Nexstar, Scripps, Allen Media and a
   dozen independents file this instead of the "Contract" print the parser knew. Carries
   order number, flight, advertiser, agency, estimate, per-line programs and amounts, gross
   and net. A Univision variant puts each label and value on its own line.
2. **Scanned NAB agreement forms** (OCR): "CANDIDATE ADVERTISEMENT AGREEMENT FORM", "ISSUE
   (Non-candidate) ADVERTISEMENT AGREEMENT FORM", the 2024 PB-19, Graham's "SUPPLEMENT TO
   ORDER", NBC's "POLITICAL INQUIRY RECORD", Fox's disclosure form. Signed scans have no
   AcroForm fields, so the form parser read nothing. The text parser takes the value after
   each stable label (candidate name, authorized committee, agency, party, office, election
   date, treasurer, sponsor) with cleanup for checkbox debris and glued addresses.
3. **WideOrbit "Order" print scanned** (OCR, inline labels): Gray's WALB/WSAW scans.
4. **Katz ECR confirmation contract** (text, Sinclair stations): `External #`, `Grand Total:`.
   The OCR'd "Sinclair contract" scans (WSMH, WWMT, WCTI) are the same report.
5. **Locality "CONTRACT WORKSHEET REPORT"** (OCR): rep-firm contracts at WWMT, WGTA.
6. **PDF portfolios** (Hearst): a one-page cover whose real order is an attachment; the
   extractor now unpacks attachments.
7. **NAB supplements and addenda** (ISCI codes, no money): recognised as `nab-supplement`
   so they stop looking like gaps.

Two bugs in the existing WideOrbit contract parser also surfaced: line items with no space
before the `:30` length token were skipped (4.7% of orders failed the lines-sum check, e.g.
"COMICS UNLEASHED NETWORK:30"), and a line number glued to the previous program name was
missed. The invoice "Order #" linking check shows 42% of WideOrbit invoices reference an order
number with no order document at the same station; that is how stations file, not a parse error.

### station_group

86 of the 200 crawled stations (41k documents) had no group because the licensee regexes
knew only parent company names. Sinclair's licensees are "<CALL> Licensee, LLC" or
"<City> (<CALL>-TV) Licensee, Inc."; Allen Media's are "<City> TV License Company, LLC";
Tegna's are legacy Belo and Gannett companies ("Combined Communications of Oklahoma" is
WZZM, "Multimedia Holdings" is KPNX); CBS's are "<City> Television Station <CALL> Inc.".
The rules in `ingest/stations.py` were checked against all 860 distinct licensee strings and
confirmed against the document templates each station files (every "Licensee, LLC" station
files Sinclair invoices or Katz contracts). Public and religious broadcasters are grouped as
such; the rest are "Independent" (five crawled stations). No station is NULL.

### Parse coverage, before and after (same 93,985 documents, 202 stations)

Before = parser v4 as loaded on the morning of 2026-10-24; after = parser v5 the same night.
"ok" means the fields the kind needs were all found (order number and gross for orders and
invoices, an advertiser for forms). Unrecognised documents were counted as `other/ok` before.

| | Before | After |
| --- | --- | --- |
| ok | 41,888 (44.6%) | 79,395 (84.5%) |
| partial | 2,731 | 5,675 |
| failed | 17,114 (14,401 of them forms) | 1,934 |
| unrecognised | 32,017 (as `other/ok`) + 244 crashes | 6,981 |
| orders ok | 24,878 | 45,926 |
| forms ok | 4,914 | 20,027 |
| invoices ok | 12,096 | 12,384 |
| parser crashes | 244 (missing `cryptography`) | 0 |
| Postgres: orders / order lines | 14,640 / 277,538 | 28,661 / 573,887 |
| Postgres: invoices / spots / creatives | 12,939 / 275,610 / 24,746 | 14,493 / 517,362 / 49,563 |
| stations with no group | 86 (41,138 docs) | 0 |

By station group after: Gray 91% ok (13,816 docs, was unparsed), Nexstar 89%, Tegna 92%,
Allen Media 95%, Sinclair 66% (its Katz invoices carry no linkable order number, so they are
"partial" by construction), Heritage 7% and Morris 14% (their scans were OCR'd by tesseract as
noise; the Vision redo at the end of the national batch fixes those).

Invariant checks after the fixes (`make validate`, `data/validate-2026-10-24.json`):

| Template | Check | Fail rate | Reading |
| --- | --- | --- | --- |
| wideorbit-contract | lines sum to gross | 0.7% (was 4.7%) | remaining: lines with a wrapped program name |
| wideorbit-contract | net = 85% or 100% of gross | 0.0% (was 0.2%, and 101 orders over $2M from a glued-rating misread during v5 development) | |
| wideorbit-order | lines sum to gross | 0.6% | truncated lines without an end date |
| wideorbit-invoice | Total Spots = aired lines | 11.1% (was 88.8% before lowercase Ad-ID suffixes) | makegoods and credits are listed without an Ad-ID |
| wideorbit-invoice | order number has an order at the station | 7.3% unlinked | the station did not upload that order |
| sinclair-invoice | order number has an order | 35.7% unlinked | Sinclair contract scans still being OCR'd |
| nab-text | yields an advertiser | 6.7% | handwritten or badly scanned forms |
| OCR orders | order number taken from the file name | 256 documents, flagged `order_no_from_filename` | rotated or low-quality scans |
| katz-ecr | net ratio | 3.8% | ECR shows net before and after commission; parser takes the first |

`order_no_filename` (a 7-digit number in the station's file name differs from the parsed
order number) fails on 5% of WideOrbit contracts, almost all of them Hearst/Tegna files named
by the Katz or agency estimate number; it is kept as an indicator, not a parser error.

### Coverage before the national crawl (2026-10-24 23:40)

| | 2026 | 2024 |
| --- | --- | --- |
| Full-power stations | 1,750 | 1,750 |
| Stations with documents | 1,098 | 1,108 |
| Stations crawled | 202 | 0 |
| Documents nationally (FCC folder counts, 2026 through Oct 23) | 410,345 | 408,081 |
| Documents downloaded | 93,985 (22.9%), 37.8 GB | 0 |
| Parsed ok | 79,395 | |

States at 100% of their 2026 documents: MI (23,625), GA (17,898), WI (12,866), NC (11,805),
PA (10,362), AZ (6,926), NV (4,330); IA 32% (Des Moines pilot); GU 100% (batch driver test).
Everything else 0%. 2024 has not been crawled at all; the target list and the crawl take a
`--years` argument, so a 2024 pass is the same command with `--years 2024` once 2026 is in.

### National 2026 crawl: launched 2026-10-24 23:47

`ingest.batch` over `data/crawl_targets_2026_national.txt`, 52 remaining states, 1,096 stations,
~316k documents to fetch, biggest states first (TX 36.6k, OH 24.9k, CA 22.0k, FL 18.2k...).
Settings: 6 download workers, 4 Vision OCR workers, 6 parse workers, Postgres refresh after
every state in the background, legacy tesseract text redone with Vision at the end
(`--redo-legacy-at-end`). Expected: downloads at the earlier rate (88k in 2.5 h) take about
9 hours; OCR of roughly 85k image PDFs about 9 hours alongside; so the crawl should be
complete within a day, with the Postgres entity rebuild (now about 4 minutes per refresh,
growing with the corpus) trailing each state.

How to watch and resume:

```bash
make status                         # one screen; "RUNNING" marks the stages holding locks
tail -f data/logs/batch-stdout.log  # one line per stage per state with exit code, duration and ETA
grep SUMMARY data/logs/*.log | tail # every stage's closing line
make coverage                       # per-state progress against the national counts
cat data/locks/pipeline.lock        # pid of the driver; kill <pid> to stop (nothing to clean up)
make batch                          # resume: finished states are skipped, pending work only
```

Known soft spots to keep an eye on: the FCC edge returning 503 on the history feed for the
current day (seen 2026-10-24; the updater records the day as failed and does not advance).

### Postgres as the only store (2026-10-25)

Until the national crawl, `crawl`, `parse` and `ocr` wrote `data/political.sqlite` and `load_pg`
copied it into Postgres after every state. SQLite's single writer made a running parse block the
updater or a second crawl ("database is locked"), the copy step was pure overhead, and the run
ledger lived apart from the data it described. Migration `008_pipeline_store.sql` moves the
remaining state into Postgres and the stages write there directly:

| was (SQLite) | now (Postgres) |
| --- | --- |
| `files` | `opif_file` with `downloaded`, `local_size` added to the existing `sha256`, `downloaded_at`, `download_attempts`, `download_error`; `deleted` is `deleted_at IS NOT NULL` |
| `docs` | `document`: `raw` holds the whole extraction (`order_no` ... `ad_ids`, `fields`); `template`, `source`, `parse_status`, `parser_version`, `parsed_at`, `ocr_engine`, `error` are columns; `needs_ocr` is a generated column from `raw->'fields'->>'needs_ocr'` |
| `listing` | `opif_listing` |
| `ocr` | `ocr` (engine, status, attempts, pages, chars, seconds, error, ocr_at) |
| `pipeline_run` | `pipeline_run`, ids from a sequence; timestamps are `timestamptz` (SQLite stored local wall-clock text, which the mirror had read as UTC) |
| `meta` | `meta` (`last_history_sync`, `entities_built_at`) |

`ingest.db.connect()` returns a psycopg connection whose rows index by position and by name, and
refuses a schema that is behind `db/migrations/`. Parse and OCR workers never touch the database:
they read PDFs and return results, the parent process upserts (one connection per process). The
OCR stage now also adopts cached text that has no ledger row (engine `cached`), so text produced by
a killed run is parsed instead of lying unused. `ingest/load_pg.py` is gone; its station loader is
`ingest/stations.py` (`make stations`), and the crawl refuses stations that are not in `station`.
`ingest/migrate_sqlite.py` copied the SQLite store idempotently (130,618 files, 130,548 documents,
305 listings, 923 OCR rows, 37 runs when first run) and compares row counts at the end.

Checked on a copy of the live database before the switch: `make status`, `make coverage`,
`make validate` unchanged in content; crawl with downloads, parse, OCR, `parse --only-failed`
(picks up OCR newer than the parse), `update --since`, `make refresh`; a crawl downloading and a
parse writing at the same time showed no lock waits in `pg_stat_activity` (row locks on different
tables; the parse's foreign-key check takes `KEY SHARE`, compatible with the crawl's updates); a
crawl killed mid-download resumed with the pending files only and no `.part` leftovers, a parse
killed mid-way resumed with the documents not yet at the parser version, and the killed runs were
marked `killed` on the next run of the stage.

### Next

- 2024 crawl (`--years 2024`) for the comparison cycle.
- Remaining layouts in the 6,981 unrecognised documents and the 1,934 failures, re-clustered
  after the national crawl (`make validate` lists them by template).
## From Ad-ID to video (2026-10-25)

Question: the invoices name every aired spot by its Ad-ID. Can we show the ad?

Short answer: often, for the big buyers, via the campaign's own YouTube
channel. There is no registry from Ad-ID to video, so the chain is
buyer → channel → upload, scored on dates, length and release order.
`ingest/video.py` builds it; `data/video_overrides.yaml` corrects it; the
app's Ads tab has a thumbnail wall and creative pages embed the match.

### What an Ad-ID looks like in this corpus

- The registry form is a four-character advertiser prefix plus a
  seven-character code, with `H` for HD (`RSFI2615000H`). The prefix maps
  cleanly to buyers here (`RSFI` = Rob Sand, 997 creatives; 568 of 781
  prefixes belong to one buyer).
- The running number is usually sequential by release: Rob Sand's spots
  are `RSFI261000H`, `262000H` ... `2625000H`, one every one to two
  weeks, first airing in that order. Ossoff's are date-coded (`JO0826`).
  Release order is therefore a usable matching signal.
- **Parser artefact, large:** several invoice layouts glue the weekday
  column and a slot digit onto the Ad-ID (`RSFI2615000HTu1`,
  `RSFI2615000HW2`, `ZLFG0916TVHSa2`). 49,563 rows in `creative` are
  about 2,200 real spots. `ingest.video.family()` strips the
  `(M|Tu|W|Th|F|Sa|Su)\d*` tail and the HD suffix; the export carries
  `family` on every creative and the wall shows one tile per family. The
  right fix is in the parser (split the cell), noted for the pipeline
  session.
- Program names leak into the Ad-ID column on some layouts ("Tennis",
  "GUNSMOKE", one airing each); the matcher skips keys with lowercase
  letters or with no digits and fewer than three airings.

### Sources tried, and their terms

| Source | What it gives | Terms / limits |
|---|---|---|
| YouTube Data API v3 | channel search, upload lists with exact `publishedAt`, durations, thumbnails | API key per project; 10,000 units/day, a channel search costs 100, so ~90 buyers/day. Terms require attribution and forbid storing beyond 30 days except ids. Not configured yet: set `YOUTUBE_API_KEY` in `.env` and the matcher switches to it. |
| yt-dlp (metadata only) | keyless search (`ytsearch15:`), flat channel listings with exact durations and approximate dates ("2 months ago"), thumbnails | Reads public pages; YouTube's ToS disallow automated access without permission, so this is a research-grade fallback, rate-limited to one request per listing and nothing downloaded. One listing ≈ 1.5 s. |
| YouTube watch page `uploadDate` | exact publish date for an upload | one GET per ad-length upload, 4 in parallel, cached forever under `data/video_cache/dates/` |
| YouTube RSS (`feeds/videos.xml?channel_id=`) | exact dates for the latest 15 uploads | returned 404 for the channels tried on 2026-10-25; not used |
| Google Ads Transparency Center | per-advertiser page listing every political ad with a playable creative (`/advertiser/AR…?region=US&political`) | the site is a JS app with no name-based deep link; advertiser ids come only from the BigQuery public dataset `google_political_ads` (needs a GCP project; no `bq`/`gcloud` on this machine) or the site's internal RPC. Used since 2026-10-26 through the public bundle (below), not BigQuery. |
| iSpot.tv | public ad pages (`ispot.tv/ad/<id>/<slug>`) with a player for many political spots | search is JS-only (`/search?q=` renders no results), brand ids are internal; usable only as an override URL (kept as a link-out, never embedded or scraped) |
| Ad-ID registry (ad-id.org) | the authoritative prefix → advertiser table | members only; no video |

Embedding uses the platforms' own players only (`youtube-nocookie.com`
iframe); nothing is downloaded or rehosted.

### Method

1. **Buyer → channel.** For buyers ordered by airings, query the buyer's
   names (canonical, FEC committee name, "<name> for <office>", "<name>
   <state> <office> ad"). Channels behind the results are scored: token-set
   similarity of the channel title to the names, with a 40% penalty per
   title token that is neither a name token (nicknames expanded:
   Rick/Richard, Mike/Michael…) nor campaign filler ("for Governor",
   "official", the buyer's state); hits across queries; the name appearing
   in the title; the surname appearing in the result titles. News and
   station channels (call signs, "ABC15", "News") are excluded. Accepted at
   ≥ 0.6, confidence and evidence stored in `buyer_channel.matched_by`.
2. **Channel → uploads.** Ad-length uploads (10–95 s) since 60 days before
   the buyer's first airing, exact dates fetched per upload.
3. **Creative → upload.** Spot families sorted by first airing are aligned
   with uploads sorted by date by a no-crossing dynamic programme (release
   order is preserved, gaps free). Pair score = date score (upload within
   −7…+3 days of first airing = 1.0, ±7 d 0.85, ±14 d 0.6, ±30 d 0.3,
   after the last airing 0) × (0.5 + 0.35·length + 0.15·title), where
   length is 1 for the buyer's billed length (`order_line.length_sec`) or a
   standard TV length and 0.35 for digital cuts (19 s, 53 s, 65 s), and
   title is 1 when the title names the buyer or says "ad"/":30". Confidence
   = pair score × a margin factor (1.0 when the runner-up is ≥ 0.2 behind,
   0.55 on a dead tie such as five spots posted the same day), capped at
   0.6 when the length disagrees with what the station billed and at 0.45
   when only an approximate date is known. Tiers: high ≥ 0.7, medium ≥
   0.4, low below. Best and runner-up are stored per creative.
4. **Overrides** (`data/video_overrides.yaml`: `AD-ID or family: video
   url`, `buyer slug: channel url`) are applied last and win.

Rob Sand, as the worked example: 26 families, 23 ad-length uploads with
exact dates, 21 aligned. `RSFI262000H` (first aired 2026-05-01) ↔ "Sand
Family Tradition" (uploaded 2026-05-01, 31 s) at 1.0; the five spots
posted together on 2026-06-23 tie at 0.6; `RSFI2614000H` lands on a 19 s
"Serving Lunch at Cattleman's" at 0.45, which is probably wrong and shows
why digital cuts are penalised. Ossoff's channel carries 47–72 s digital
versions, not the 30 s TV cuts, so his matches cap at 0.65.

### Results (top 300 buyers by airings, 2026-10-25 02:30, 866 buyers / 64,978 creatives / 2,797 spot families / 707,127 airings in Postgres)

Measured before the parser fix for the glued weekday tails (see "Invoice
Ad-ID tails" below): the creative counts here are inflated, the airing
shares count each glued copy. The re-run on the corrected creatives
(12,539 rows, 953,118 airings after more states loaded) gives 46% of airings
with a rank-1 upload and 9% high confidence; the tables below stand as the
first measurement.

Channels: 178 of the top 300 buyers resolved to a channel (5 wrong picks
blocked by hand in the overrides file: "Victory Fund" for two state victory
funds, a jiu-jitsu channel for a Brian Wrightson, the City of Reno for a
local buyer called "Reno"). By category:

| Category | Buyers with creatives | With a channel | Channel has ad-length uploads |
|---|---|---|---|
| Federal | 156 | 57 | 47 |
| State | 334 | 88 | 67 |
| Issue | 325 | 33 | 21 |
| Local | 51 | 0 | 0 |

Issue groups are the weak spot: super PACs rarely keep a public channel
under the name on the NAB form ("Texans for a Conservative Majority" has
one but posts nothing ad-length). Local buyers were not in the top 300.

Match rates, counted on creatives (invoice rows) and on airings:

| Tier | Creatives | Airings | Share of all airings |
|---|---|---|---|
| High (≥ 0.7) | 4,747 | 77,481 | 11% |
| Medium (0.4–0.7) | 10,889 | 156,196 | 22% |
| Low (< 0.4) | 12,538 | 156,310 | 22% |
| Any match | 28,174 of 64,978 | 389,987 of 707,127 | 55% |

| Category | Airings | With a playable match | High tier |
|---|---|---|---|
| Federal | 187,056 | 115,941 (62%) | 20,376 (11%) |
| State | 329,912 | 230,928 (70%) | 53,862 (16%) |
| Issue | 185,378 | 43,118 (23%) | 3,243 (2%) |
| Local | 4,781 | 0 | 0 |

Share of airings with a playable match for two places (stations whose
contour covers the ZIP, all invoiced airings on them):

| Place | Stations | Airings | Playable | High | Medium or better |
|---|---|---|---|---|---|
| Des Moines 50309 | 10 | 59,797 | 39,548 (66%) | 11,502 (19%) | 24,198 (40%) |
| Atlanta 30303 | 20 | 81,768 | 58,585 (72%) | 6,908 (8%) | 28,131 (34%) |

Atlanta is dominated by Richard Jackson (80k airings, 4,254 creative rows,
one channel, 28 ad-length uploads for 28 real spot families once the junk
rows are dropped): most of his airings get a medium-tier match because
several spots were posted on the same day.

The tail: the top 15 buyers are 37% of all airings, the top 100 are 73%,
the top 300 are 92%. Below #300 the buyers have under 350 airings each and
mostly no channel worth finding (a local PAC, a county race, a school
board). Running `--top 600` would add at most a few points of coverage;
the better lever is the issue groups in the top 100 that have a channel
under a different name (override material: `issue-<slug>: <channel url>`).

Why "low" is big: the alignment leaves a family unassigned when the DP
preferred a neighbour, and the family then keeps its nearest upload as a
low guess (shown as "guess" in the app) rather than nothing; and campaigns
batch-post (five spots on one day), which the margin rule scores 0.55.
Both are honest; a reader sees the badge.

### Quota, terms and keeping it fresh

- Without an API key the matcher makes one yt-dlp listing per channel
  (cached 24 h), one search per query (cached 14 d) and one watch-page GET
  per ad-length upload, sequential at ~1/s with a 90 s pause on a 429
  (YouTube rate-limits bursts; a 4-wide parallel fetch got 429s within a
  minute). The first top-300 run took 30 min; reruns from cache take
  10 min.
- With `YOUTUBE_API_KEY` in `.env` the same run costs about 100 units per
  buyer searched plus 2 per 50 uploads: ~20,000 units for 300 buyers, so
  two days on the default 10,000/day quota (searches are cached; reruns
  are nearly free). The API path gives exact dates for every upload and is
  the one the Data API terms cover. Ask Google for the key through the
  Cloud console (YouTube Data API v3, API key, no OAuth needed).
- Embeds: `youtube-nocookie.com` iframe, the platform's own player, no
  download, no rehost. Thumbnails are YouTube's `mqdefault.jpg` hotlinked.
- Freshness: `make video` (or `python3 -m ingest.video all --top 300`)
  after the crawl adds creatives. It re-lists channels older than a day,
  re-aligns every family of each buyer (new families attach to new uploads;
  earlier matches can move if a better alignment appears), keeps overrides
  on top, and survives the entity rebuild (migration 008 keys channels by
  buyer slug, not buyer_id, which the rebuild reassigns). Then
  `scripts/safe_export.sh --only creatives,pages,details`.
- The Google step (`ingest.video google-ads`, also part of `all`) re-downloads
  the bundle only when Google's copy is newer (conditional GET), then
  re-extracts and re-matches in about 30 s. iSpot pages go in as overrides.

### Second source: Google's political ads bundle (2026-10-26)

`https://storage.googleapis.com/political-csv/google-political-ads-transparency-bundle.zip`
is no longer the empty stub it was on 2026-10-25: 313 MB zipped, 3.3 GB of
CSV, regenerated daily, public, no account or key. It is the same data as
the BigQuery dataset `bigquery-public-data.google_political_ads`, so
BigQuery access is not needed. Useful tables:

- `creative-stats`: every election ad Google served (YouTube included) with
  advertiser, type (VIDEO / TEXT / IMAGE), first and last served dates,
  impression and spend buckets, geo targeting (ZIPs, counties, states), and
  a link to the ad's page in the Ads Transparency Center. 128,814 US video
  ads ran between 2025-07-01 and 2026-10-26.
- `advertiser-stats`: `Public_IDs_List` carries the FEC committee id for
  federal committees ("FEC ID C00…"), a state registration for state ones,
  an EIN for most others. 16,638 of 17,889 US advertisers have one.
- `advertiser-declared-stats`: the name and regulatory id the advertiser
  declared, a second name to match on.

It has no YouTube video id, so a Google match is a link-out (Google's page
plays the ad), never an embed. `ingest/video_google.py`:

1. Buyer → advertiser: FEC id first (confidence 0.95), else the best name
   match over advertiser and declared names, with guards: every distinctive
   token of the buyer's name must appear in the advertiser's (rejects
   "Democratic Lieutenant Governors Association" → "Democratic Governors
   Association" and "Texans for a Conservative Majority" → "Texas
   Conservative Majority PAC"), a buyer named only with generic words ("US
   Senate", "Action Fund") does not match by name, and the advertiser must
   target the buyer's state when the buyer has one.
2. Per spot family: the advertiser's video ads that started serving within
   5 days of the first airing and target a state the spot aired in. Where
   YouTube already matched, a Google launch within 5 days of the upload date
   adds the signal `google` and +0.05, and the best candidate is stored as a
   rank-3 "also ran on Google" link. Where YouTube did not, the best
   candidate becomes the rank-1 link-out at 0.55 × date score / √candidates.
   Big PACs run several variants a week, so most of these are "guess".

Results (2026-10-26 23:30; 2,228 buyers, 24,593 creatives, 7,284 spot
families, 2,022,297 airings, top 300 buyers = 71% of airings):

| Top-300 buyers | Buyers | Google advertiser | by FEC id |
|---|---|---|---|
| Federal | 87 | 73 | 70 |
| Issue | 100 | 76 | 36 |
| State | 110 | 25 | 0 |
| Local | 3 | 0 | 0 |

| Airings | All | Playable on YouTube | Google link only | Any link |
|---|---|---|---|---|
| Federal | 547,725 | 263,784 (48%) | 70,926 (13%) | 61% |
| Issue | 634,083 | 146,011 (23%) | 140,141 (22%) | 45% |
| State | 810,106 | 476,773 (59%) | 6,692 (1%) | 60% |
| Local | 30,383 | 3,098 (10%) | 0 | 10% |
| Total | 2,022,297 | 889,666 (44%) | 217,759 (11%) | 55% |

High-confidence YouTube matches cover 166,805 airings (8%). The Google
launch date confirmed 475 YouTube family matches. Google helps most where
YouTube was weakest: issue groups and super PACs register with Google to run
election ads even when they keep no public channel. State candidates mostly
advertise on Google under committee names that rarely carry an FEC id, so
Google adds little there.

| Place | Airings | Playable | High | Medium or better | Any link |
|---|---|---|---|---|---|
| Des Moines 50309 | 59,797 | 39,605 (66%) | 10,843 (18%) | 25,699 (43%) | 44,164 (74%) |
| Atlanta 30303 | 81,768 | 59,163 (72%) | 9,512 (12%) | 32,587 (40%) | 64,307 (79%) |

Two caveats on these numbers. From the 134th buyer of the run on, YouTube
served a stripped watch page (HTTP 200, no metadata) instead of the upload
date, without a 429: a soft block after about 1,500 page fetches in 45
minutes. Those 40 buyers matched on approximate listing dates, which caps
their confidence at 0.45. With a Data API key in `.env` (2026-10-26 23:44)
the 56 buyers whose channels lacked exact dates were re-run through the API
(`ingest.video videos --approx`, 65 s, a few hundred quota units): all 56
now have exact dates for every ad-length upload. High-confidence YouTube
matches went from 166,805 to 187,890 airings (8.3% to 9.3%), medium from
404,504 to 426,769, low down from 536,116 to 500,775; playable airings
from 889,666 to 897,937 (44%). Atlanta 30303 high tier: 9,512 to 10,006.
The API is now the default path whenever the key is set (shell-style
`export YOUTUBE_API_KEY=...` lines are read too). And the spot
family rule (`ingest.video.family()`) is still needed after the parser fix:
bare weekday tails with no slot digit (`SSUBCAR111HSa`, `JADP2601HW`)
survive it, and the rule now strips at most a two-digit slot so real codes
such as `MADF2602` keep their identity.

### After the parser's weekday-tail fix (2026-10-27 00:15)

The pipeline session now strips bare weekday tails too (`SSUBCAR111HSa`,
`JADP2601HW`): `creative` fell from 24,593 rows to 8,639, multi-code spot
families from 3,098 to 401. `ingest.video` pruned the 13,218 match rows
whose Ad-IDs no longer exist and re-matched the top 300 buyers that have a
channel (no new channel searches: through the API each costs 100 units).

One regression found and fixed on the way: the API's uploads playlist
(`UU…`) includes Shorts, which the keyless Videos-tab listing never did.
Shorts are under 60 s, so they flooded the ad-length candidates (106 of Tom
Tiffany's 144 uploads) and pushed high-confidence matches down to medium.
`api_uploads()` now reads `UULF…`, the long-form playlist, and falls back to
`UU…` only if a channel has none.

| Airings (2,090,672) | Count | Share |
|---|---|---|
| Playable on YouTube | 942,256 | 45% |
| of which high confidence | 198,189 | 9.5% |
| of which medium | 462,355 | 22% |
| Google link only | 241,719 | 12% |
| Any link | 1,183,975 | 57% |

| Place | Airings | Playable | High | Medium or better | Any link |
|---|---|---|---|---|---|
| Des Moines 50309 | 59,801 | 39,619 (66%) | 10,147 (17%) | 27,670 (46%) | 44,178 (74%) |
| Atlanta 30303 | 82,494 | 60,301 (73%) | 11,887 (14%) | 41,492 (50%) | 65,471 (79%) |

108 of the current top 300 buyers have no channel on record (most entered
the top 300 as the crawl grew). Searching them through the API costs about
10,800 units, one day's default quota; `ingest.video channels --top 300`
then `videos` does it, best spread over two days.

### Channel search through the API, prefix fallback, office channels (2026-10-27 03:15)

Channel search for the top-300 buyers without one, through the Data API in
two quota days: 70 searches (7,000 units) before the 03:00 EDT reset, 86
(8,600 units) after it. 38 channels found, mostly issue groups and PACs (A
Stronger Michigan, Put Progress First, Kansans for Democracy, Missouri
Promise, Civic Progress Fund). Budget rules: a new search is 100 units; a
buyer's queries stop at the first that finds a channel; names under four
letters are not searched; a spent budget or quota defers the remaining
buyers instead of recording "no channel". A channel title must now contain
a distinctive token of the buyer's names, which rejected "Maga Ky" → "Ky";
"Ky PAC" → "Pac- Ky" and "Alliance for Economic Freedom" → "Economic
Freedom Alliance" were blocked by hand.

Two corrections came out of checking the result:

- **Prefix fallback.** Duplicate station labels ("Steyerdgovernor" for Tom
  Steyer, "Win Senate" for WinSenate) and junk folders ("US Senate", holding
  Graham, Barr, Cassidy and Husted spots) have no channel of their own. The
  Ad-ID prefix identifies the advertiser, so a spot family whose buyer has
  no channel now borrows the channel of the buyer that carries at least 60%
  of that prefix's airings among channel holders (confidence × 0.9, signal
  `prefix`). No searches, so it runs over every buyer: 267 buyers, 130,574
  airings.
- **Office channels dropped.** 20 channels were officeholders' government
  channels ("Senator Jon Husted", "USSenLindseyGraham", "Governor Kathy
  Hochul", "Rep. Ron Estes"): office videos, not campaign ads ("Cassidy
  Secures Over $1.3 Billion for Louisiana" had matched a TV spot). Channel
  scoring now rejects them, and every run drops any that remain along with
  their matches (95 here). Those buyers need a new search for their campaign
  channel.

| Airings (2,090,672) | Count | Share |
|---|---|---|
| Playable on YouTube | 1,024,016 | 49% |
| of which high confidence | 230,944 | 11% |
| of which medium | 498,725 | 24% |
| of which through the prefix fallback | 130,574 | 6% |
| Google link only | 233,773 | 11% |
| Any link | 1,257,789 | 60% |

| Place | Airings | Playable | High | Medium or better | Any link |
|---|---|---|---|---|---|
| Des Moines 50309 | 59,801 | 43,420 (73%) | 13,679 (23%) | 31,174 (52%) | 47,979 (80%) |
| Atlanta 30303 | 82,494 | 61,932 (75%) | 13,905 (17%) | 44,083 (53%) | 66,556 (81%) |

84 of the top 300 buyers still have no channel: about 70 were searched and
nothing passed, and about 14 lost an office channel and wait for a search
on the next quota day (~2,000 units).

### Known limits

- No video for buyers without a channel; no channel for most issue groups.
- A match says "this is the upload that lines up"; it can be the wrong one
  of two spots released the same week (both 30 s, same channel). The
  runner-up is stored and shown on the creative page for exactly that case.
- The invoice tail bug multiplies creatives; airings are the right unit for
  every rate above.
- Deleted or private uploads keep their rows until the next listing.

## Invoice Ad-ID tails (2026-10-25)

The ad-video session noticed that "49,563 creatives" was mostly one bug:
several invoice layouts (WideOrbit and the Sinclair variant, where the
spot line is `date time ... SPOT <code>`) print the weekday column and a
slot digit hard against the Ad-ID, so the parser captured `RSFI2615000HTu1`
and `JTFI2000HW1` as codes. One real creative then appeared as up to
fourteen (seven weekdays times a slot digit), and every airing-count rate
on the video chain was computed against the inflated families.

Fix (parser v5, no version bump): `clean_ad_id` in `ingest/parse.py` strips
a `(Mo|Tu|W|Th|F|Sa|Su|M)<1-2 digits>` tail **only when the weekday agrees
with the spot's air date**. `RSFI267000H` on a Tuesday is untouched (no tail);
`RSFI2615000HTu1` on a Tuesday becomes `RSFI2615000H`; the same token on a
Wednesday is left alone, since then it is not a weekday glue. Codes ending in
a bare letter plus digits that genuinely belong to the Ad-ID survive unless
they happen to spell the air weekday, which is the residual risk and is
rare (Ad-ID codes end in a letter, not a letter-digit pair).

Applied with `python -m ingest.parse --kind invoice --no-lock` (both new
options: `--kind` reparses only documents currently of that kind; `--no-lock`
lets a maintenance reparse run beside the batch driver, whose own parse
stage would otherwise fail on the held lock) rather than bumping
PARSER_VERSION, which would have queued a 4.5-hour reparse of every
document in the middle of the national crawl. The next entity refresh
collapses the duplicate creatives:

| | before | after |
|---|---|---|
| distinct Ad-IDs on invoices | 73,000 | 13,452 |
| weekday-glued tokens left | 72,610 | 2 (both disagree with the air date, kept) |
| creative rows | 73,000 | 12,539 |
| Rob Sand families | hundreds | 164 (top code RSFI2610000H, 617 airings) |
| airings with a playable upload (after re-aligning video) | 55% of inflated families | 46% of 953,118 airings; 9% high confidence |

The video rate fell, not rose: the old figure counted each glued copy of a
matched family as matched, so one aligned upload scored up to fourteen
times. The new number is the honest one. Video matches are keyed by Ad-ID,
so after any change to how codes are read `ingest.video videos` must run
again (it works from the cached channel listings, about 13 minutes).

Mixed-case tokens (`CONl0430HTu3`, `WakingUpHTu1`) carry the same tail, so
the code part of the pattern is `[A-Za-z0-9]{4,14}`; the weekday check is
what keeps `KCOXSHERIFF30` on a Monday intact.

### OCR stall (2026-10-25, 11:29)

During the Iowa batch one Vision worker hung inside `VNRecognizeTextRequest` at 0% CPU for
over 15 minutes (document 1300 of 2567). `ProcessPoolExecutor.map` has no per-task timeout,
so the three idle workers and the whole batch waited on it. `ingest.ocr` now runs jobs through
its own loop: each worker leaves a `data/ocr/<id>.txt.start` marker while reading a document;
the parent treats a marker older than `--timeout` (default 300 s) as a hang, records the
document as a failed attempt ("timeout ... OCR engine hung"), kills the pool and starts a new
one for the rest. A worker that dies the same way loses only the documents that had markers;
queued ones are re-run. A watchdog line every 60 s shows in-flight and queued counts and the
oldest age, so a stall is visible in the log instead of silent. Tested with a fake hanging
job and a fake dying worker (`scratchpad/hangtest.py` during the session) and on four real
documents. The hung Iowa run has to be killed by hand once; `make batch` resumes it with the
1,300 finished pages cached.

## Newscast blocks (2026-10-25)

Alex asked for a per-place "tonight's news" view: the political spots in each station's news
programs. What the filings support:

- **Orders name the newscast and its clock window.** 354,000 of 1.69 million order lines (21%) name
  a news program, and 95% of all lines carry a window ("Action News at 6p 6p-7p", "M-F Late News
  11:00 PM-11:35 PM", "M-F News CH8 @ 430-5A"). A line is one week of a flight with that week's spot
  count, so the expected spots on one night are the week's count divided by the nights the line's
  day pattern allows (M-F, MTWTF, Sa/Su, or a 7-character mask like `---T---`). 98,749 lines across
  7,079 orders covered today when this was measured.
- **Invoices confirm what aired, late.** Every aired spot has a time but no program name; the invoice
  reaches the FCC file a median 17 days after the air date (10 at the 25th percentile, 48 at the
  90th). The newest confirmed airing was four days old. Spots are placed into news blocks by air time.
- `ingest/newscasts.py` classifies program strings (window regex handling "530a-6a", "10-1035P",
  "6-7A", "12:35 XM-1:00 XM"; network newscasts tagged) and writes `web/data/newscasts/<fac>.json`:
  blocks, scheduled lines for a 60-day window either side of today, and confirmed airings for the
  last 60 days, plus `index.json`. 173,137 news lines matched, 12,153 had no parsable window.
- The Newscasts tab in the pin popover defaults to tonight, offers last night and any date, groups by
  Morning / Midday / Evening / Late, and shows the schedule until a station's `confirmed_through`
  reaches the chosen night, then the confirmed spots with Ad-IDs and video thumbnails. Under a
  scheduled buyer it shows that buyer's three most recent creatives on that station as "likely".

Limits: preemptions and make-goods are invisible until the invoice; a line whose program string
has no window is dropped (7%); the files are large for big markets (KCCI 740 KB) because of the
60-day confirmed window.


## Tract population and resolution-8 cells (2026-10-26)

Zoomed-in views were not finer than a county: cell population came from county totals spread by
area, so every cell inside a county had the same density and the res-7 layer only redrew the county
map at 5 km². Two changes, both in `ingest/geo.py`:

- **Population from Census tracts.** `cb_2023_us_tract_500k` (85,186 tracts, 58 MB) plus ACS
  2019-2023 five-year total population, table B01003, from the table-based summary file
  (`acsdt5y2023-b01003.dat`, 18 MB, every geography in one pipe-delimited file; the Census API
  wants a key for tract-wide pulls, this file does not). Both cached under `data/geo/`. ACS is a
  period estimate (335.6M including Puerto Rico), the county table is the 2024 vintage (340.1M),
  so each tract keeps its ACS share of its county and is rescaled to the county's 2024 total;
  Puerto Rico has tracts but no county estimate and keeps its ACS counts. A cell's population is
  the sum over the tracts it intersects of tract population × overlap area / tract area; tracts
  wholly inside a cell and cells wholly inside a tract skip the polygon intersection, which is why
  1.8 million cells allocate in about 30 s. Check logged by the stage: over counties with a 2024
  estimate the res-5 national total is 337,830,067 by tracts against 334,683,719 by counties,
  0.94% apart (the tract method keeps people that the county method lost in the empty land
  outside any station contour; 341,084,952 with Puerto Rico's tracts). The county table stays for
  names and labels.
- **Resolution 8 ("metro" scope).** The seven children of every res-7 cell whose tract-derived
  density is at least `METRO_DENSITY` = 150 people per km². The budget was ~500,000 cells; the
  stage logs the density that would hit it exactly (140/km² today) so the constant can be retuned.
  Result: 68,315 res-7 parents → 478,205 res-8 cells. Two surprises on the way: the first run used
  30/km², chosen from the old 269k-cell res-7 layer, but the national crawl has made 1,098 stations
  active and the res-7 layer is now 1,297,859 cells, so 30/km² meant 1.46 million res-8 cells and
  the run was cancelled; and 150/km² is small-town density, not "metro" — inside crawled contours
  a 500k budget cannot reach down to rural land, which is the point.
- **Money at res 8** (`db/migrations/009_tract_res8.sql`, the `hex_total` mart): res 8 covers only
  part of a station's footprint, so its spread is normalised by the station's complete res-7
  population reach. Dollars per person is identical at res 7 and res 8; a res-8 cell holds only the
  share of the station's money that reaches its people, and the rural remainder stays at res 7.
- **Tiles as a mosaic.** `hex7` cells whose children exist carry `fine=1`; from zoom 9.3 the app
  draws `hex8` on top of the `hex7` cells without that flag (`layersFor`/`filterFor` in
  `app/src/lib/hexlayers.js`), so dense areas are 0.7 km² cells and the countryside around them
  stays at 5 km² with no double painting and no holes (every res-8 cell is emitted, money or not).
  Zooms: hex5 3–8, hex7 6–10 (was 6–11), hex8 9–13. `/map` gains a "Finest" chip when
  `tiles/meta.json` lists res 8; legend maxima stay per resolution from that file.
- `web/data/hex/total_r<res>.json` is now written for res 5 only: the app reads cells from PMTiles,
  and the res-7 file would have grown from 9.5 MB to ~50 MB in git with the national crawl.

Wall times and sizes on the M-series laptop, Homebrew Postgres (`make geo`, `make marts`,
`python -m ingest.export --only hex,methods`, `make tiles`, `npm --prefix app run build`):

| step | wall time | result |
| --- | --- | --- |
| geo: counties + tracts load | 14 s | 3,235 counties, 85,186 tracts |
| geo: polyfill + population (res 5, 7, 8) | 79 s (allocation itself 31 s + 11 s) | 29,196 + 1,297,859 + 478,205 cells |
| geo: station_hex | 121 s | 11,390,545 rows (was 1,514,897) — whole stage 3 m 35 s |
| marts | 2 m 37 s (44 s with empty spend_daily, see below) | hex_total 1,805,249 rows |
| export --only hex,methods | 2 s | methods.json, hex/total_r5.json |
| tiles | 1 m 18 s | hex5 7.3 MB (23,968 cells), hex7 140.4 MB (1,110,818 cells with buys, 49 s), hex8 111.2 MB (478,205 cells, 25 s), contours 7.8 MB |
| app build | 36–47 s | `app/build` 896 MB, almost all of it the copied `web/data` (tiles 267 MB) |

Hosting note: Cloudflare Pages caps a single asset at 25 MB, so none of the hex PMTiles can ship
with the static site; they belong in R2 (or any range-request host) with the app pointed at that
origin instead of `location.origin` in `hexlayers.js`. The res-7 file alone is over the cap after
the national crawl, independent of res 8.

Two things to know when reading the result. $/person is flat inside a station's footprint at every
resolution by construction, so the zoomed-in view only varies on Money, Spots and $/spot; the
Des Moines z11 tile holds 316 res-8 cells with 0 to 2,221 people and $0 to $158k booked, the
downtown half of them above the res-8 legend maximum ($46k, the 98.5th percentile of all
478,205 cells nationwide), so a heavy market saturates the ramp in its core and the variation
shows at the edges and in parks, river and airport cells. And a bug found while checking: both
map pages learned the zoom only from `zoomend`, which a camera set from the URL hash before the
map's load event never fires, so a shared link to zoom 11 drew res-5 cells; the pages now seed the
zoom from the map when it is ready.

Collision log for the same night: the daily job's hand run (scripts/daily.sh) reached its marts
step one second after this session's `make marts` took the lock, so its marts and export-tiles
steps failed with "already running", and this session's marts began one second before the daily
job's entities rebuild committed, which left `spend_daily` empty until a second marts run at
00:57. Nothing wrong in the stages themselves; two drivers on one database need one queue.

### The change feed cannot do daily updates; folder counts can (2026-10-26)

Three nightly runs in a row failed the same way: `file/history.json` for one day answers 503
after offset ~3,000. Probing shows why. The feed is sorted newest-first and each page past
offset 2,500 takes about a minute server-side (52 s for 500 rows at offset 2,500, 57 s for
100 rows at offset 3,000), so the gateway times out before a day of 10,000 to 14,000 rows is a
quarter read; `sourceService` and sort parameters are ignored. The marker `last_history_sync`
therefore never advanced and the overnight job never brought anything in.

Replacement, now the default in `ingest.update`: for each tracked station-year, read the FCC's
own `file_count` for the year folder (`folder/id/<id>.json`, 0.3 s; the folder id is cached in
`opif_listing.folder_id`), compare it with the non-deleted files we hold, and re-walk only the
station-years that differ. A complete walk marks the files it did not see as deleted. The check
over all 1,098 stations takes about six minutes with four threads; the re-walks cost roughly 20
API calls per changed station. `--all` re-walks everything (weekly safety net against an add
and a delete cancelling out in the count); `--mode feed` keeps the old path for small windows.
First run on four stations: three had grown (+14 files), listed and downloaded in 71 seconds.

First full run of the count-check update (2026-10-26, 22:47 to 23:36): 1,098 station-years
checked in 55 seconds, 623 changed, re-listed with four threads in 38 minutes (297,668 files
walked, 7,880 new, 77 removed, 16 walk-versus-count mismatches logged), 8,451 files
downloaded (3.4 GB) with 2 transient 504s that the daily chain's own pass then fetched. The
daily chain after it (`scripts/daily.sh`) took 24 minutes end to end: parse 3.6 min, OCR of
2,015 image PDFs 7.8 min, entities twice plus identity 3.4 min, marts 2.7 min, export and
tiles 2.4 min, site build 44 s. Store after the run: 419,678 documents from 1,098 stations,
84.8% parsed ok, 126,584 orders, 63,943 invoices, 2.09 million spots.

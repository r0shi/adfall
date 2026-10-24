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

# Design pass: making Adfall (then TV Wormhole) fun to play with

Date: 2026-10-24. Status: proposal for review before more building. Written
as a data scientist and a product designer in the same room, looking at the
current views and the data underneath them.

## The thing in one sentence

A map you drop a pin on, and everything else is an answer to "what reaches
here": which stations, whose money, which ads, when. The pin is the state of
the whole app; every view is a lens on the same place and the same time.

## What's wrong today (honest audit)

- **The panel is the app and the map is wallpaper.** Half the screen is a
  sidebar of cards; the map only draws contours. The pin should be the
  center of gravity, and the information should hang off it.
- **Time is a separate tab.** "Over time" is a view, so time is something
  you go to rather than something every view has. Money, ads and buyers all
  have a time axis; the scrubber belongs to the app, not one page.
- **Every list is a list.** Buyers, ads, stations: ranked bars and cards.
  Useful, but nothing invites pivoting: by party, by category, by station
  group, by daypart, by week. The data supports all of it today.
- **No comparison anywhere.** The most interesting questions are
  differential: this place versus that place, this week versus last, D versus
  R, booked versus the invoiced reality. Nothing is side-by-side.
- **The animation is a sparkler, not a story.** Weekly frames blink on and
  off. Money booked in June still exists; the viewer wants to see it
  accumulate, or fade slowly, and to be told what week it is.
- **Numbers without grain.** "$89M" with no sense of whether that is booked
  or invoiced, orders or airings. The grain is in the data; it should be in
  the type.
- **Coverage is uneven and invisible.** A third of documents are unparsed
  layouts; a place with a Gray station looks quieter than it is. The UI
  should show confidence, not hide it.

## Design principles

1. **Map first, pin as state.** The whole screen is the map. The pin owns a
   popover; views are tabs inside that popover or drawers that slide in,
   never a static sidebar that pushes the map aside.
2. **Time is global.** One timeline bar across the bottom of the map on
   every view: current date, a scrubline, play, speed, window (day / week /
   cumulative). Every number and layer answers "as of" or "during" that
   window.
3. **Pivot, don't page.** Every table has a "by" control: buyer, party,
   category, station, station group, daypart, week. Every chart sorts by
   clicking an axis. Filters are chips that stack and live in the URL.
4. **Compare.** Two pins (A and B) with mirrored panels. Two time windows.
   A "difference" mode on the map (A minus B, D minus R, booked minus
   invoiced).
5. **Show the grain and the confidence.** Booked / invoiced / aired is a
   visible legend, not a tooltip. Parse coverage per station shows as a
   small ring or bar on every station mention.
6. **Small multiples beat one big chart.** A grid of tiny weekly sparklines
   per buyer or per station reads faster than one stacked area.
7. **Everything links out.** Every number traces to the FCC document in two
   clicks. That is the trust model.

## Information architecture

```
Map (always)
 ├─ Pin popover (what reaches here)        ← Stations · Money · Ads · Over time, scoped to the pin
 ├─ Layer picker (top-left)                ← Coverage · Money · $/person · Ads · $/spot · Difference
 ├─ Timeline bar (bottom)                  ← date, scrubline, play, window, accumulate
 ├─ Explore drawer (right)                 ← pivots over the whole corpus; SQL under the hood
 └─ Entity pages (route change)            ← buyer, station, creative; same timeline bar
About · Search (places, stations, buyers, Ad-IDs in one box)
```

Mobile: the map is the top 40%; the popover becomes a bottom sheet with the
same tabs; the timeline bar sits between them.

## View by view

### Map (home)

- Full-bleed map. Top-left: search box and layer picker. Bottom: timeline
  bar. No sidebar.
- Drop a pin → a popover anchored to the pin: header ("Des Moines, IA · 10
  stations · $93M booked this cycle"), category bar, tabs. Draggable,
  collapsible to a pill, remembered in the URL.
- Layers are the density tiles already built, plus **Difference**: pick two
  of (D, R, issue, booked, invoiced, week A, week B) and color diverging.
- Hover a cell: a compact readout with the chosen metric and a sparkline of
  that cell's weekly money.
- Click a station contour: highlight it and open its tab in the popover.
- Pin A / Pin B: a second pin opens a second popover; panels mirror and show
  deltas ("Atlanta gets 3.1× the $/person of Des Moines this week").

### Pin popover tabs

- **Stations**: today's cards, denser. Call, group, parse-confidence ring,
  booked/invoiced two-tone bar, top three buyers as chips, stream and FCC
  links. Sort by distance, money, airings.
- **Money**: buyers reaching the pin. Default a treemap (category → buyer)
  that answers "who dominates here" at a glance; toggle to ranked bars.
  Pivot chips: party, category, station group, agency. Clicking a buyer
  filters every other tab and the map layer to that buyer.
- **Ads**: creatives aired on these stations in the time window. Cloud by
  buyer (current), list by creative, and a **daypart heatmap** (hour × day
  of week) of airings, because "what are people actually seeing at 6pm" is
  the question.
- **Over time (here)**: stacked weekly area by category or party for the
  stations reaching the pin, booked as line and invoiced as area, with the
  global timeline driving the cursor.

### Timeline bar (global)

- Translucent band across the bottom of the map: big date on the left
  ("Week of Oct 19"), a scrubline for the whole cycle with ticks for
  primaries and election day, play/pause, speed, and a window switch:
  **Day · Week · Cumulative**.
- Layers respond: Day and Week show that window's money with a slow decay
  (previous frames fade over about four frames instead of vanishing);
  Cumulative accumulates. A "trails" toggle keeps decay on when scrubbing
  by hand.
- The scrubline is itself a sparkline of total money for the current pin
  (or national), so the shape of the cycle is visible before pressing play.

### Buyers (corpus-wide)

Becomes the Explore drawer's default pivot rather than a page: rows =
buyer, columns = state or station group or week, cells = booked with a bar
in each cell, flip to a heatmap. Filters: category, party, state, agency,
text. Downloadable. The buyer page stays as the deep link.

### Buyer page

- Header with identity provenance (FEC id, match method, raw labels),
  because identity is where errors hide.
- Small multiples: one sparkline per station, sorted by money.
- Daypart heatmap of airings; creatives with first/last aired and station
  count; agencies.
- "Compare to" picker: overlay another buyer's weekly line (the opponent).

### Station page

- Header with group, stream and FCC links, parse-coverage bar ("97% of
  1,913 documents parsed").
- Buyer treemap, weekly area by category, daypart heatmap, creatives.
- "Nearby stations" from contour overlap, each with its money.

### Creative page

- Airings by day with a station legend, by hour, by station; buyer and
  identity link; an "also aired with" list of creatives sharing days and
  stations (co-flighting), which is how campaigns rotate spots.

### Explore

- Keep SQL, add a **pivot builder** above it that writes the SQL: rows,
  columns, measure, filters, time window. Users get pivots without typing;
  power users see and edit the query.
- A query lives in the URL hash, so it can be shared.

### Search

One box: places (ZIP, city), stations (call sign), buyers, Ad-IDs. Results
grouped by kind. Enter on a place drops the pin; on a buyer opens the page.

## Visual system

- **Color is meaning.** Keep the category palette (federal red, state
  orange, local gold, issue blue). Party is a secondary encoding only where
  it is the question (D blue / R red, diverging), and category red never
  shares a screen with party red. Money intensity gets a single-hue ramp
  (cream → oxblood); difference maps a diverging ramp with a neutral middle.
- **Type carries grain.** Booked regular, invoiced bold, aired as a count
  with its own glyph; a three-item legend lives in the timeline bar.
- **One theme for map and panels.** The current mix (light basemap, dark
  UI in dark mode) reads unfinished. Proposal: a muted dark basemap with
  light popovers, so the density ramp pops.
- **Motion with a purpose.** Pin drop, popover grow, layer crossfade (300
  ms), frame decay. Nothing else moves.
- **Density.** Tabular numbers everywhere; 13px body, 11px meta; cards
  become rows once a list exceeds ten.

## Data layer changes this needs

| Need | Change |
| --- | --- |
| Daily frames per place | `station_daily` is daily already; compute cell frames client-side from station_daily × station_hex (fast: ~200 stations × ~150 cells) or export day-level res-5 frames (~7 MB) |
| Cumulative mode | prefix sums in the client over the same frames |
| Difference maps | per-cell party split: add booked_D / booked_R / booked_issue to `hex_total` and the frames |
| Daypart heatmaps | hour and weekday columns derived from `spot.aired_time`, in the spot mart and per-entity exports |
| Co-flighting | a small mart of spot pairs sharing (station, day) |
| Parse confidence per station | already in `spend/<fac>.json`; surface it |
| Two pins | no data change; the URL carries both |
| Pivot builder | nothing new; it writes SQL over the marts |
| Search | a tiny index of call signs, buyer names and Ad-ID prefixes alongside places.json |

The parser gap matters more than any of this: a third of documents are
unrecognized layouts (Gray and several smaller groups). Until those parsers
exist, half the swing-state map is under-counted, and no design fixes that.
Proposed order: Gray's template first (31 stations, 13.8k documents), then
the long tail by document count.

## Proposed build order

1. Timeline bar with decay and accumulate, on daily frames: the "watch the
   money move" promise, done properly.
2. Map-first layout with the pin popover; sidebar pages become popover
   tabs; mobile bottom sheet.
3. Treemap and daypart heatmap components, used in the popover, buyer and
   station pages.
4. Difference layer and Pin B.
5. Pivot builder over Explore; unified search.
6. Parsers for Gray and the next groups (data work, in parallel with 1–5).

Each step ships on its own, and the About page updates itself as the data
changes.

## Visual system (2026-10-25): Adfall

The product is now Adfall; a place's *airshed* is the set of stations reaching it, its *adfall*
the money and spots those stations drop on it. The weather lean is deliberately limited to color
and visual impression, nothing decorative, so the data-journalism audience is not put off.

- Magnitude (money, $ per person, spots, the timeline frames) uses one precipitation ramp, pale sky to
  deep indigo, defined once in `app/src/lib/palette.js` and reused by MapLibre (`rampExpr`), deck.gl
  (`rampRGBA`) and the legends (`rampCss`). Lightness-monotone, one hue family, so it reads as "more"
  without a rainbow.
- Differences are warm against cool (amber / teal) for momentum and booked-minus-invoiced; party keeps
  conventional blue and red and is the only place those two hues appear, so red never reads as partisan
  elsewhere. The accent moved from red to a storm indigo for the same reason.
- Buyer categories use the dataviz skill's validated steps: violet, green, yellow, magenta, gray, with
  separate dark-mode steps. All pass the categorical validator in both modes (light and dark, all pairs);
  yellow and magenta sit under 3:1 on white, which is allowed because every category mark sits beside
  its label.
- Pin A is ink, pin B is amber, so contours stop competing with the blue data layers.
- Small charts (daypart heatmaps, explore cells) switched from the red scheme to blues to match the map.

### Color by office level or party (2026-10-25, evening)

Alex: in a political product any blue or red tile is read as a party signal, so category colors must
not look partisan, and a real party coloring should be a deliberate switch. Done as a global toggle in
the nav ("Color by: Office level | Party", remembered per browser) behind one helper,
`app/src/lib/color.svelte.js`, that every buyer-level mark uses: treemap tiles, bars, dots, the share
bars under a station, the video wall, the Plot charts (`plotColor()` + `keyOf`) and the `Legend`
component.

- Office level is one indigo ramp: federal darkest, state, local lightest (validated as an ordinal
  ramp in both modes); issue groups are sand; other is gray. Nothing blue-blue or red.
- Party uses blue and red, sand for issue groups (the form asks only candidates), gray for the rare
  independents and nonpartisan races, and a hatched gray for unknown (blank forms), so an unknown can
  never pass for a class. The four real classes pass the validator in both modes; the two grays are
  always next to their labels and are under 1% of money.
- Coverage when this was built: federal candidates 97% labeled by dollars, state candidates 65%,
  issue groups 51% of all money with no party by design. A curated "leaning" list for the top issue
  buyers is the obvious next step and is not in the data yet.


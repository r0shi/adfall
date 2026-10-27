<script>
  // Every number here comes from /data/methods.json, written by ingest/export.py from the live database on each
  // pipeline run, and the pipeline descriptions are the ingest modules' own docstrings. Prose lives here only.
  import { get, usd, num } from '$lib/data.js';
  let m = $state(null);
  get('methods.json').then(x => m = x);
  let h = $state(null);                      // web/data/health.json from scripts/health.sh (hourly); absent on a fresh checkout
  get('health.json').then(x => h = x).catch(() => {});
  const pct = (a, b) => b ? `${Math.round(100 * a / b)}%` : '–';
  const kinds = $derived.by(() => {
    if (!m) return [];
    const out = {};
    for (const [k, n] of Object.entries(m.documents.by_kind_status)) { const [kind, st] = k.split('/'); out[kind] ||= { kind, ok: 0, partial: 0, failed: 0 }; out[kind][st] += n; }
    return Object.values(out).sort((a, b) => (b.ok + b.partial + b.failed) - (a.ok + a.partial + a.failed));
  });
  const withAmount = $derived(m ? (m.documents.by_kind_status['order/ok'] || 0) + (m.documents.by_kind_status['order/partial'] || 0) + (m.documents.by_kind_status['invoice/ok'] || 0) + (m.documents.by_kind_status['invoice/partial'] || 0) : 0);
  const idLabel = { 'fec-candidate': 'matched to an FEC candidate', 'fec-committee': 'matched to an FEC committee', 'name-rule': 'merged by name rule', 'manual': 'manual override', 'raw': 'kept as filed' };
</script>
<svelte:head><title>About · Adfall</title></svelte:head>
<div class="shell wide"><aside class="panel" style="border:0;max-width:860px">
  <header>
    <h1>About the data and methods</h1>
    <p class="tag">What this site shows, where every number comes from, how documents become dollars, and what it gets wrong. Figures update with each data build.</p>
    <p class="small">Code, pipeline and design notes: <a href="https://github.com/r0shi/adfall" target="_blank" rel="noopener">github.com/r0shi/adfall</a> (MIT).</p>
    {#if m}<div class="muted small">Data build {m.generated} · uploads from {m.documents.first_upload} to {m.documents.last_upload} · spending dated {m.money.first_day} to {m.money.last_day}</div>{/if}
    {#if h}<div class="muted small">Pipeline health {h.ok ? 'ok' : 'failing'} at {h.checked_at.slice(0, 16).replace('T', ' ')}: {Object.entries(h.checks).map(([k, c]) => `${k} ${c.ok ? 'ok' : 'FAIL'} (${c.detail})`).join(' · ')}</div>{/if}
  </header>
  {#if !m}<section class="muted">Loading…</section>{:else}
  <section>
    <h2>What this is</h2>
    <p>Pick a place in the United States and see the broadcast TV stations whose predicted signal reaches it, watch their local newscasts, and follow the political advertising money each station is taking: who is buying, how much, when, and which ads actually aired. The money comes from the stations' own filings, which federal law requires them to publish.</p>
    <p>Two words recur. A place's <b>airshed</b> is the set of stations whose predicted signal reaches it, like a watershed for broadcast. <b>Adfall</b> is what lands on it: the political money and spots those stations carry, spread over the people in their footprint.</p>
    <p>It is a research prototype. Amounts are what stations filed, parsed by software, and should be read as directional. Links to every underlying document are one click away so you can check.</p>

    <h2>Coverage right now</h2>
    <ul>
      <li><b>{num(m.stations.licensed)}</b> licensed full-power and Class A stations with FCC service contours, nationwide; <b>{num(m.stations.with_streams)}</b> have an indexed newscast stream.</li>
      <li>Political files crawled for <b>{num(m.stations.with_documents)}</b> stations in {m.stations.states.join(', ')}: <b>{num(m.documents.total)}</b> documents, of which {num(m.documents.ocr)} were image-only PDFs that went through OCR.</li>
      <li><b>{usd(m.money.booked)}</b> booked across <b>{num(m.entities.orders)}</b> orders; <b>{usd(m.money.invoiced)}</b> invoiced; <b>{num(m.entities.spots)}</b> individual aired spots with <b>{num(m.entities.creatives)}</b> distinct creatives; <b>{num(m.entities.buyers)}</b> buyers.</li>
    </ul>

    <h2>Where the data comes from</h2>
    <ul>{#each m.sources as s}<li><a href={s.url} target="_blank" rel="noopener">{s.name}</a>: {s.what}{#if s.terms} (<a href={s.terms} target="_blank" rel="noopener">terms</a>){/if}</li>{/each}</ul>
    <p class="small muted">{m.fcc_notice}</p>

    <h2>Which stations reach a place</h2>
    <p>The FCC publishes a predicted service contour for every station: the area where its digital signal is expected to be receivable, computed from transmitter power, antenna height and the FCC's F(50,90) propagation curves. A place "is reached" by a station when the point falls inside that polygon. Contours are predictions, not measurements; terrain and buildings make real reception better or worse. The site simplifies each contour to 72 points.</p>

    <h2>How documents become numbers</h2>
    <p>Each station keeps a political file: orders (contracts), revisions, cancellations, invoices and the NAB disclosure forms a buyer signs. The crawler lists and downloads every document through the FCC's public API, then parsers extract what each kind says.</p>
    <table class="small" style="border-collapse:collapse;margin:8px 0">
      <thead><tr><th style="text-align:left;padding:4px 10px 4px 0">Document kind</th><th style="text-align:right;padding:4px 10px">parsed</th><th style="text-align:right;padding:4px 10px">partial</th><th style="text-align:right;padding:4px 10px">not parsed</th></tr></thead>
      <tbody>{#each kinds as k}<tr><td style="padding:3px 10px 3px 0">{k.kind === 'other' ? 'unrecognized / other' : k.kind}</td><td style="text-align:right;padding:3px 10px">{num(k.ok)}</td><td style="text-align:right;padding:3px 10px">{num(k.partial)}</td><td style="text-align:right;padding:3px 10px">{num(k.failed)}</td></tr>{/each}</tbody>
    </table>
    <p><b>{pct(withAmount, m.documents.total)}</b> of all documents yielded a dollar amount. Orders and invoices are the ones that carry money; forms carry identity (candidate, committee, office); "other" includes certifications, supplements and traffic-system layouts the parsers do not yet recognize, which means stations whose documents fall there are <b>under-counted</b>, not zero. Recognized layouts: WideOrbit text and image prints, Katz and ePort contracts, Sinclair billing invoices.</p>
    <ul class="small">{#each m.stations.by_group as g}<li>{g.group}: {g.stations} station{g.stations === 1 ? '' : 's'}, {num(g.docs)} documents</li>{/each}</ul>

    <h2>Booked, invoiced, aired</h2>
    <p><b>Booked</b> is the gross amount on the latest revision of each order; a cancellation makes it zero. <b>Invoiced</b> is the gross on invoices, which stations issue on billing cycles after spots air, so it lags booked by weeks and is incomplete until a month or two after the election. <b>Aired spots</b> are the individual airings listed on invoices, each with a date, a time and the creative's Ad-ID code. {num(m.entities.invoices_linked)} of {num(m.entities.invoices)} invoices could be tied to their order; the rest are reported separately rather than added to booked totals.</p>
    <p>Over time, booked dollars are placed on the days they were scheduled: by each order's schedule lines when the order lists them ({num(m.entities.orders_with_lines)} of {num(m.entities.orders)} do), otherwise spread evenly over the order's flight dates. Invoiced dollars spread over the invoice period. Aired spots are exact.</p>

    <h2>Money on the map</h2>
    <p>A dollar booked at a station is spread across the station's contour in proportion to population. {#if m.geography.population}Population is the {m.geography.population.source} ({num(m.geography.population.tracts)} tracts, {num(m.geography.population.rescaled_total)} people against {num(m.geography.population.county_total)} in the county estimates); {m.geography.population.cell_rule}.{:else}Population is Census county population allocated to cells by land area.{/if} Cells are H3 hexagons at {Object.entries(m.geography.resolutions || Object.fromEntries(Object.entries(m.geography.hex_cells).map(([r, n]) => [r, { cells: n }]))).map(([r, x]) => `resolution ${r}${x.km2 ? ` (~${x.km2} km²)` : ''}: ${num(x.cells)} cells${x.where ? `, ${x.where}` : ''}`).join('; ')}; {num(m.geography.coverage_rows)} station-cell coverage shares. "Money reaching here" is therefore the sum over every station covering a cell: a dollar can count in several cells, which is the right reading for "what reaches this place" and the wrong one for adding cells up. Dollars per person is flat inside any one station's footprint by construction and only varies where coverage overlaps.</p>

    <h2>Who the buyers are</h2>
    <p>Stations label buyers in their own words, so the same campaign appears under many spellings. Labels are merged into buyers in four steps: manual overrides, matching federal labels to the FEC candidate master for the cycle (state-scoped, by surname and first-name evidence), matching issue groups to the FEC committee master, and a name rule for everyone else, followed by a surname-and-nickname clustering within category and state. Of {num(m.entities.buyers)} buyers: {Object.entries(m.entities.identity).map(([k, [n, l]]) => `${num(n)} ${idLabel[k] || k} (${num(l)} station labels)`).join('; ')}. {m.entities.manual_overrides} manual overrides are in effect. State and local candidates have no registry here, so their identity is by name only.</p>

    <h2>Known limits</h2>
    <ul>
      <li>Unrecognized document layouts under-count the stations that use them (see the table above). Parsers are added group by group.</li>
      <li>Only full-power and Class A television is covered; cable, satellite, radio and digital advertising are not in these files at all.</li>
      <li>Political-file folders are organized by station staff; a mislabeled folder becomes a mislabeled buyer until an override fixes it.</li>
      <li>Contours are predictions. Population is {m.geography.population ? 'tract-level, spread into cells by overlap area' : 'county-level, spread by area'}. Nielsen market definitions are not used; the market named for a pin is the community most of its stations are licensed to.</li>
      <li>Streams are the stations' own; ad breaks on them are replaced, so the political ads themselves cannot be watched there. Ad-ID codes identify creatives, but the video is not in the FCC file.</li>
    </ul>

    <h2>Pipeline, as the code describes itself</h2>
    {#each Object.entries(m.modules) as [name, doc]}
      <details><summary style="cursor:pointer;font-family:ui-monospace,monospace">ingest/{name}.py</summary><pre class="small" style="white-space:pre-wrap;color:var(--muted);margin:4px 0 10px 16px">{doc}</pre></details>
    {/each}
    <p class="small muted" style="margin-top:14px">Source and design notes: <a href="https://github.com/r0shi/adfall/blob/main/docs/research.md" target="_blank" rel="noopener">docs/research.md</a>, <a href="https://github.com/r0shi/adfall/blob/main/docs/design.md" target="_blank" rel="noopener">docs/design.md</a> and <a href="https://github.com/r0shi/adfall/blob/main/README.md#sources-methods-and-limits" target="_blank" rel="noopener">the README</a> in the repository.</p>
  </section>
  {/if}
</aside></div>

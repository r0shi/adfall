<script>
  import MapView from '$lib/Map.svelte';
  import Chart from '$lib/Chart.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { weeklyHex, stationDaily, usd, num } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), weekly = $state(null), daily = $state(null), wi = $state(0), playing = $state(false), metric = $state('booked');
  weeklyHex().then(w => { weekly = w; wi = Object.keys(w.weeks).length - 1; });
  stationDaily().then(d => daily = d);
  const weeks = $derived(weekly ? Object.keys(weekly.weeks).sort() : []);
  const week = $derived(weeks[wi]);
  const METRICS = { booked: ['Booked $ reaching each cell', (r) => r[1]], perperson: ['Booked $ per person', (r) => r[4] ? r[1] / r[4] : 0], spots: ['Spots aired', (r) => r[3]], invoiced: ['Invoiced $', (r) => r[2]] };
  const valueOf = $derived(METRICS[metric][1]);
  const maxV = $derived.by(() => { let m = 0; if (weekly) for (const rows of Object.values(weekly.weeks)) for (const r of rows) m = Math.max(m, valueOf(r)); return m || 1; });
  const facsHere = $derived(new Set(loc.found.map(s => s.fac)));
  const series = $derived.by(() => {
    if (!daily) return [];
    const by = new Map();
    for (const [fac, day, booked, invoiced, spots] of daily.rows) {
      if (loc.p && !facsHere.has(fac)) continue;
      const wk = weekOf(day); const e = by.get(wk) || { week: new Date(wk), booked: 0, invoiced: 0, spots: 0 };
      e.booked += booked; e.invoiced += invoiced; e.spots += spots; by.set(wk, e);
    }
    return [...by.values()].sort((a, b) => a.week - b.week);
  });
  function weekOf(day) { const d = new Date(day + 'T00:00:00Z'); const dow = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - dow); return d.toISOString().slice(0, 10); }
  let timer;
  $effect(() => { clearInterval(timer); if (playing) timer = setInterval(() => { wi = (wi + 1) % weeks.length; if (wi === weeks.length - 1) playing = false; }, 450); return () => clearInterval(timer); });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); } });
  $effect(() => {
    if (!api || !weekly || !week) return;
    const rows = weekly.weeks[week]; const v = valueOf; const mx = maxV; const m = metric; const wk = week;
    import('@deck.gl/geo-layers').then(({ H3HexagonLayer }) => api.setDeckLayers([new H3HexagonLayer({
      id: 'hex', data: rows, getHexagon: r => r[0], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.75,
      getFillColor: r => { const t = Math.sqrt(v(r) / mx); return t <= 0 ? [0, 0, 0, 0] : [200, 16 + 120 * (1 - t), 46 + 150 * (1 - t), 40 + 200 * t]; },
      updateTriggers: { getFillColor: [m, wk] }
    })]));
  });
</script>
<svelte:head><title>Over time · TV Wormhole</title></svelte:head>
<div class="shell">
  <aside class="panel">
    <header>
      <h1>Watch the money move</h1>
      <p class="tag">Booked dollars placed on the days they were scheduled to air, spread over each station's coverage by population. One frame per week.</p>
      <div class="scrub">
        <button class="ghost" onclick={() => playing = !playing} disabled={!weeks.length}>{playing ? '❚❚' : '▶'}</button>
        <input type="range" min="0" max={Math.max(0, weeks.length - 1)} bind:value={wi} />
        <b style="min-width:92px;text-align:right">{week ? `wk of ${week.slice(5)}` : '…'}</b>
      </div>
      <div class="chips">{#each Object.entries(METRICS) as [k, [label]]}<span class="chip" class:on={metric === k} onclick={() => metric = k} role="button" tabindex="0">{label}</span>{/each}</div>
    </header>
    <section>
      <h2>{loc.p ? `Stations reaching ${loc.label}` : 'All crawled stations'} · by week</h2>
      {#if series.length}
        <Chart height={200} make={(Plot, width, height) => Plot.plot({
          width, height, marginLeft: 48, x: { label: null }, y: { label: '$ booked (week)', tickFormat: 's', grid: true },
          marks: [
            Plot.areaY(series, { x: 'week', y: 'booked', fill: 'var(--accent)', fillOpacity: 0.15 }),
            Plot.lineY(series, { x: 'week', y: 'booked', stroke: 'var(--accent)' }),
            Plot.lineY(series, { x: 'week', y: 'invoiced', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
            week ? Plot.ruleX([new Date(week)], { stroke: 'var(--fg)', strokeOpacity: 0.5 }) : null,
            Plot.tip(series, Plot.pointerX({ x: 'week', y: 'booked', title: d => `week of ${d.week.toISOString().slice(0, 10)}\n${usd(d.booked)} booked · ${usd(d.invoiced)} invoiced · ${num(d.spots)} spots aired` }))
          ]
        })} />
        <div class="legend"><span><span class="dot" style="background:var(--accent)"></span>booked</span><span><span class="dot" style="background:var(--muted)"></span>invoiced (lags a billing cycle)</span></div>
      {:else}<div class="muted small">Loading…</div>{/if}
      <p class="muted small">Cells are H3 resolution 5 (~250 km²). Color scales with the square root of the week's value so the early weeks stay visible. Click the map to change place.</p>
    </section>
  </aside>
  <div class="mapwrap"><MapView onready={a => api = a} onclick={p => setLocation(p)} zoom={4} /></div>
</div>

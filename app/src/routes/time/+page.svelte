<script>
  // "Watch the money move": full-bleed map, frames composed in the client, the global timeline bar below.
  import MapView from '$lib/Map.svelte';
  import Timeline from '$lib/Timeline.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { tl, setRange } from '$lib/time.svelte.js';
  import { stationDaily, hexWeights, usd, num } from '$lib/data.js';
  import { Framer } from '$lib/frames.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), framer = $state.raw(null), daily = $state.raw(null), weights = $state.raw(null), scope = $state('all'), hover = $state.raw(null);  // big data stays non-reactive
  Promise.all([stationDaily(), hexWeights(5)]).then(([d, w]) => { daily = d; weights = w; });
  const METRICS = { booked: ['Booked $', 2], invoiced: ['Invoiced $', 3], spots: ['Spots aired', 4] };
  $effect(() => {
    if (!daily || !weights) return;
    const f = new Framer(daily, weights, METRICS[tl.metric][1]);   // local: reading `framer` here would make this effect depend on its own write
    const days = f.dayList;
    framer = f;
    setRange(days[0], days[days.length - 1]);
  });
  const facsHere = $derived(scope === 'here' && loc.p ? new Set(loc.found.map(s => s.fac)) : null);
  const series = $derived(framer ? framer.series(tl.window === 'cumulative' ? 'cumulative' : 'day', facsHere) : []);
  // stable color scale per window/metric: 98th percentile of cell values over all frames (sampled every 7th day)
  const scaleMax = $derived.by(() => {
    if (!framer) return 1; const vals = []; const win = tl.window;
    const keep = framer.shown.slice();
    for (let i = 0; i < framer.dayList.length; i += 7) { framer.reset(); for (const [, v] of framer.frame(framer.dayList[i], win)) vals.push(v); }
    framer.shown.set(keep);
    vals.sort((a, b) => a - b); return vals[Math.floor(vals.length * 0.98)] || 1;
  });
  let lastDay = null, cellIndex = null, layerMod = $state.raw(null);
  import('@deck.gl/geo-layers').then(m => layerMod = m);
  $effect(() => {
    if (!api || !framer || !tl.day || !layerMod) return;
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.93 : 0.85) : 0;   // per step; a trail lasts ~15-20 steps
    if (!decay) framer.reset();
    framer.frame(tl.day, tl.window, { decay, facs: facsHere });
    const mx = scaleMax, shown = framer.shown, raw = framer.raw, cells = framer.cells;
    if (!cellIndex || cellIndex.length !== cells.length) cellIndex = Array.from(cells, (_, i) => i);   // stable data identity: one row per cell, always
    api.setDeckLayers([new layerMod.H3HexagonLayer({
      id: 'frame', data: cellIndex, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.85,
      getFillColor: i => { const t = Math.sqrt(Math.min(1, shown[i] / mx)); return [200, 16 + 120 * (1 - t), 46 + 150 * (1 - t), Math.round(255 * Math.min(1, t * 1.4))]; },
      onHover: ({ object }) => { hover = object == null ? null : [cells[object], shown[object], raw[object]]; },
      onClick: ({ object }) => { if (object != null) import('h3-js').then(h3 => { const [lat, lng] = h3.cellToLatLng(cells[object]); setLocation([lat, lng]); }); },
      transitions: { getFillColor: { duration: Math.min(650, 600 / tl.speed), easing: t => t } },   // per-cell interpolation between frames
      updateTriggers: { getFillColor: [tl.day, tl.window, tl.metric, mx, tl.trails] }
    })]);
  });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); } });
  const fmt = (v) => tl.metric === 'spots' ? num(v) : usd(v);
</script>
<svelte:head><title>Over time · TV Wormhole</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={a => api = a} onclick={p => setLocation(p)} zoom={4} />
  <div class="float">
    <b>Watch the money move</b>
    <div class="muted small">{METRICS[tl.metric][0]} reaching each cell, {tl.window === 'cumulative' ? 'accumulated through' : tl.window === 'week' ? 'in the week ending' : 'on'} the date below. Click a cell or the map to pick a place.</div>
    <div class="chips" style="margin:8px 0 0">{#each Object.entries(METRICS) as [k, [l]]}<span class="chip" class:on={tl.metric === k} onclick={() => tl.metric = k} role="button" tabindex="0">{l}</span>{/each}</div>
    <div class="chips" style="margin:4px 0 0"><span class="muted small">Scrubline:</span>
      <span class="chip" class:on={scope === 'all'} onclick={() => scope = 'all'} role="button" tabindex="0">All crawled</span>
      <span class="chip" class:on={scope === 'here'} onclick={() => scope = 'here'} role="button" tabindex="0" title={loc.p ? '' : 'Pick a place first'}>{loc.p ? `Reaching ${loc.label}` : 'Reaching a place'}</span></div>
    {#if hover}<div class="small" style="margin-top:8px"><b>{fmt(hover[2])}</b> this {tl.window === 'cumulative' ? 'cumulative' : tl.window}{tl.trails && hover[1] > hover[2] * 1.01 ? ` · shown ${fmt(hover[1])} with trail` : ''}</div>{/if}
    <div class="legend" style="display:block;margin-top:8px"><div style="height:8px;border-radius:4px;background:linear-gradient(90deg, rgba(200,136,196,.25), rgb(200,16,46))"></div>
      <div class="row" style="font-size:11px"><span>0</span><span style="margin-left:auto">{fmt(scaleMax)}+</span></div></div>
  </div>
  {#if framer}<Timeline {series} label={facsHere ? `${facsHere.size} stations` : `${framer.byStation.size} stations`} />{/if}
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 300px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 78%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  @media (max-width: 800px) { .float { width: calc(100% - 24px); } }
</style>

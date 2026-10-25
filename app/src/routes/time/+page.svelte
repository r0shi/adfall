<script>
  // "Watch the money move": full-bleed map, frames composed in the client, the global timeline bar below.
  import MapView from '$lib/Map.svelte';
  import Timeline from '$lib/Timeline.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { tl, setRange } from '$lib/time.svelte.js';
  import { stationDaily, hexWeights, usd, num } from '$lib/data.js';
  import { Framer } from '$lib/frames.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), framer = $state(null), daily = $state(null), weights = $state(null), scope = $state('all'), hover = $state(null);
  Promise.all([stationDaily(), hexWeights(5)]).then(([d, w]) => { daily = d; weights = w; });
  const METRICS = { booked: ['Booked $', 2], invoiced: ['Invoiced $', 3], spots: ['Spots aired', 4] };
  $effect(() => { if (daily && weights) { framer = new Framer(daily, weights, METRICS[tl.metric][1]); const days = framer.dayList; setRange(days[0], days[days.length - 1]); } });
  const facsHere = $derived(scope === 'here' && loc.p ? new Set(loc.found.map(s => s.fac)) : null);
  const series = $derived(framer ? framer.series(tl.window === 'cumulative' ? 'cumulative' : 'day', facsHere) : []);
  // stable color scale per window/metric: 98th percentile of cell values over all frames (sampled every 7th day)
  const scaleMax = $derived.by(() => {
    if (!framer) return 1; const vals = []; const f = new Framer(daily, weights, METRICS[tl.metric][1]);
    for (let i = 0; i < f.dayList.length; i += 7) for (const [, v] of f.frame(f.dayList[i], tl.window)) vals.push(v);
    vals.sort((a, b) => a - b); return vals[Math.floor(vals.length * 0.98)] || 1;
  });
  let lastDay = null;
  $effect(() => {
    if (!api || !framer || !tl.day) return;
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.9 : 0.78) : 0;
    if (!decay) framer.reset();
    const rows = framer.frame(tl.day, tl.window, { decay, facs: facsHere });
    const mx = scaleMax;
    import('@deck.gl/geo-layers').then(({ H3HexagonLayer }) => api.setDeckLayers([new H3HexagonLayer({
      id: 'frame', data: rows, getHexagon: r => r[0], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.8,
      getFillColor: r => { const t = Math.sqrt(Math.min(1, r[1] / mx)); return t <= 0.02 ? [0, 0, 0, 0] : [200, 16 + 120 * (1 - t), 46 + 150 * (1 - t), 40 + 215 * t]; },
      onHover: ({ object }) => { hover = object || null; },
      onClick: ({ object }) => { if (object) import('h3-js').then(h3 => { const [lat, lng] = h3.cellToLatLng(object[0]); setLocation([lat, lng]); }); },
      transitions: { getFillColor: 250 },
      updateTriggers: { getFillColor: [tl.day, tl.window, tl.metric, mx] }
    })]));
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

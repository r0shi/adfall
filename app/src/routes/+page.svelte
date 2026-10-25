<script>
  // Map first. The pin is the state; everything about the place hangs off it in a popover.
  import MapView from '$lib/Map.svelte';
  import Search from '$lib/Search.svelte';
  import Popover from '$lib/Popover.svelte';
  import Timeline from '$lib/Timeline.svelte';
  import StationsTab from '$lib/tabs/StationsTab.svelte';
  import MoneyTab from '$lib/tabs/MoneyTab.svelte';
  import AdsTab from '$lib/tabs/AdsTab.svelte';
  import TimeTab from '$lib/tabs/TimeTab.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { tl, setRange } from '$lib/time.svelte.js';
  import { spendIndex, usd, CATS, get, stationDaily, hexWeights } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  import { installHexLayers, setHexLayer, METRICS } from '$lib/hexlayers.js';
  import { Framer } from '$lib/frames.js';
  import { makeFrameLayer, frameScale } from '$lib/framelayer.js';
  let api = $state(null), idx = $state.raw({ stations: {}, year: new Date().getFullYear() }), meta = $state.raw(null), zoom = $state(3.6);
  let layer = $state('coverage'), tab = $state('stations'), collapsed = $state(false), hover = $state.raw(null);
  let framer = $state.raw(null), layerMod = $state.raw(null), lastDay = null;
  spendIndex().then(d => idx = d); get('tiles/meta.json').then(m => meta = m);
  const LAYERS = [['coverage', 'Coverage'], ['booked', 'Money'], ['pp', '$ / person'], ['spots', 'Spots'], ['ps', '$ / spot'], ['animate', 'Over time ▶']];
  const res = $derived(zoom >= 6.3 ? 7 : 5);
  function ready(a) { api = a; installHexLayers(a.map); a.onZoom(z => zoom = z); a.map.on('mousemove', e => { if (layer === 'coverage' || layer === 'animate') return; const f = a.map.queryRenderedFeatures(e.point, { layers: [`hex${res}-fill`] })[0]; hover = f ? f.properties : null; }); }
  $effect(() => { if (api?.map?.getLayer('hex5-fill')) setHexLayer(api.map, { visible: layer !== 'coverage' && layer !== 'animate', res, metric: layer === 'coverage' || layer === 'animate' ? 'booked' : layer, meta }); });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); if (api.map.getZoom() < 6) api.flyTo(loc.p, 6.5); } else if (api) { api.setContours({ type: 'FeatureCollection', features: [] }); api.setMarker(null); } });
  // animate layer: load frame data on first use
  $effect(() => { if (layer === 'animate' && !framer) Promise.all([stationDaily(), hexWeights(5), import('@deck.gl/geo-layers')]).then(([d, w, m]) => { layerMod = m; const f = new Framer(d, w, 2); const days = f.dayList; framer = f; setRange(days[0], days[days.length - 1]); }); });
  const scale = $derived(framer && layer === 'animate' ? (tl.window, frameScale(framer, tl.window)) : 1);
  const series = $derived(framer ? framer.series(tl.window === 'cumulative' ? 'cumulative' : 'day', loc.p ? new Set(loc.found.map(s => s.fac)) : null).filter(s => s[0] <= tl.last) : []);
  $effect(() => {
    if (!api || !layerMod) return;
    if (layer !== 'animate' || !framer || !tl.day) { api.setDeckLayers([]); return; }
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.937 : 0.865) : 0;
    if (!decay) framer.reset();
    framer.frame(tl.day, tl.window, { decay });
    api.setDeckLayers([makeFrameLayer(layerMod.H3HexagonLayer, framer, { max: scale, speed: tl.speed, triggers: [tl.day, tl.window, scale, tl.trails],
      onHover: h => hover = h, onClick: h3 => import('h3-js').then(m => { const [lat, lng] = m.cellToLatLng(h3); setLocation([lat, lng]); }) })]);
  });
  const covered = $derived(loc.found.filter(s => idx.stations[s.fac]?.total));
  const total = $derived(covered.reduce((t, s) => t + idx.stations[s.fac].total, 0));
  const byCat = $derived.by(() => { const m = {}; for (const s of covered) for (const [c, v] of Object.entries(idx.stations[s.fac].by_category)) m[c] = (m[c] || 0) + v; return m; });
  const TABS = [{ id: 'stations', label: 'Stations' }, { id: 'money', label: 'Money' }, { id: 'ads', label: 'Ads' }, { id: 'time', label: 'Over time' }];
  const fmtHover = (p) => layer === 'animate' ? `${usd(p.raw)} this ${tl.window}` : `${METRICS[layer]?.[0]}: ${layer === 'pp' ? '$' + (+p.pp).toFixed(2) : layer === 'spots' ? p.spots : layer === 'ps' ? '$' + p.ps : usd(p.booked)} · ${Number(p.pop).toLocaleString()} people · ${p.stations} stations with buys`;
</script>
<svelte:head><title>TV Wormhole</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={ready} onclick={p => setLocation(p)} />
  <div class="float">
    <Search />
    <div class="chips" style="margin:6px 0 0">{#each LAYERS as [k, l]}<span class="chip" class:on={layer === k} onclick={() => layer = k} role="button" tabindex="0">{l}</span>{/each}</div>
    {#if layer !== 'coverage' && layer !== 'animate'}<div class="muted small" style="margin-top:6px">{METRICS[layer][1]}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
    {:else if layer === 'animate'}<div class="muted small" style="margin-top:6px">Booked $ reaching each cell, by the window on the bar below.{hover ? ' ' + fmtHover(hover) : ''}</div>{/if}
  </div>
  {#if loc.p}
    <Popover {api} anchor={loc.p} title={loc.label} sub="{loc.found.length} stations reach here{covered.length ? ` · ${usd(total)} booked ${idx.year}` : ''}" tabs={TABS} bind:active={tab} bind:collapsed onclose={() => { loc.p = null; loc.found = []; history.replaceState(null, '', location.pathname); }}>
      {#if covered.length}<div class="catbar" style="margin:0 0 10px">{#each Object.entries(byCat).sort((a, b) => b[1] - a[1]) as [c, v]}<i style="width:{(100 * v / total).toFixed(1)}%;background:{CATS[c] || CATS.Other}" title="{c}: {usd(v)}"></i>{/each}</div>{/if}
      {#if tab === 'stations'}<StationsTab found={loc.found} p={loc.p} {idx} {api} />
      {:else if tab === 'money'}<MoneyTab found={loc.found} all={loc.all} {idx} />
      {:else if tab === 'ads'}<AdsTab found={loc.found} />
      {:else}<TimeTab found={loc.found} />{/if}
    </Popover>
  {/if}
  {#if layer === 'animate' && framer}<Timeline {series} label={loc.p ? `${loc.found.length} stations here` : `${framer.byStation.size} stations`} />{/if}
  <div class="credit muted">Contours: FCC · Streams: NewsON · Money: FCC public political files · <a href="/about">About</a> · This product uses the FCC Data API but is not endorsed or certified by the FCC.</div>
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 360px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  .credit { position: absolute; left: 12px; bottom: 6px; z-index: 3; font-size: 10.5px; max-width: 60%; }
  @media (max-width: 800px) { .float { width: calc(100% - 24px); } .credit { display: none; } }
</style>

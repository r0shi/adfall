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
  import { loc, locB, setLocation, setLocationB, clearA, clearB } from '$lib/location.svelte.js';
  import { DIFFS, stationDiffs, composeDiff, makeDiffLayer, diffScale } from '$lib/difflayer.js';
  import { tl, setRange } from '$lib/time.svelte.js';
  import { spendIndex, usd, CATS, get, stationDaily, hexWeights } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  import { installHexLayers, setHexLayer, METRICS } from '$lib/hexlayers.js';
  import { Framer } from '$lib/frames.js';
  import { makeFrameLayer, frameScale } from '$lib/framelayer.js';
  let api = $state(null), idx = $state.raw({ stations: {}, year: new Date().getFullYear() }), meta = $state.raw(null), zoom = $state(3.6);
  let layer = $state('coverage'), tab = $state('stations'), tabB = $state('stations'), collapsed = $state(false), collapsedB = $state(false), hover = $state.raw(null), pickingB = $state(false), weights = $state.raw(null);
  let framer = $state.raw(null), layerMod = $state.raw(null), lastDay = null;
  spendIndex().then(d => idx = d); get('tiles/meta.json').then(m => meta = m);
  const LAYERS = [['coverage', 'Airshed'], ['booked', 'Money'], ['pp', '$ / person'], ['spots', 'Spots'], ['ps', '$ / spot'], ['animate', 'Over time ▶'], ['dr', 'D − R'], ['bi', 'Booked − invoiced'], ['wk', 'Week vs last']];
  const isDiff = $derived(layer in DIFFS);
  const isTile = $derived(!(layer === 'coverage' || layer === 'animate' || isDiff));
  const res = $derived(zoom >= 6.3 ? 7 : 5);
  function ready(a) { api = a; installHexLayers(a.map); a.onZoom(z => zoom = z); a.map.on('mousemove', e => { if (!isTile) return; const f = a.map.queryRenderedFeatures(e.point, { layers: [`hex${res}-fill`] })[0]; hover = f ? f.properties : null; }); }
  $effect(() => { if (api?.map?.getLayer('hex5-fill')) setHexLayer(api.map, { visible: isTile, res, metric: isTile ? layer : 'booked', meta }); });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); if (api.map.getZoom() < 6) api.flyTo(loc.p, 6.5); } else if (api) { api.setContours({ type: 'FeatureCollection', features: [] }); api.setMarker(null); } });
  $effect(() => { if (!api) return; if (locB.p) { api.setContoursB(toGeoJSON(locB.found)); api.setMarkerB(locB.p); } else { api.setContoursB({ type: 'FeatureCollection', features: [] }); api.setMarkerB(null); } });
  function onMapClick(p) { if (pickingB) { pickingB = false; setLocationB(p); } else setLocation(p); }
  $effect(() => { if ((isDiff || layer === 'animate') && !weights) hexWeights(5).then(w => weights = w); });
  $effect(() => { if (layer === 'wk' && !framer) Promise.all([stationDaily(), hexWeights(5), import('@deck.gl/geo-layers')]).then(([d, w, m]) => { layerMod = m; const f = new Framer(d, w, 2); const days = f.dayList; framer = f; setRange(days[0], days[days.length - 1]); }); });
  $effect(() => { if (isDiff && !layerMod) import('@deck.gl/geo-layers').then(m => layerMod = m); });
  const diffValues = $derived(isDiff && weights && (layer !== 'wk' || (framer && tl.day)) ? composeDiff(weights, stationDiffs(layer, idx, framer, tl.day)) : null);
  const diffScaleV = $derived(diffValues ? diffScale(diffValues) : 1);
  // animate layer: load frame data on first use
  $effect(() => { if (layer === 'animate' && !framer) Promise.all([stationDaily(), hexWeights(5), import('@deck.gl/geo-layers')]).then(([d, w, m]) => { layerMod = m; const f = new Framer(d, w, 2); const days = f.dayList; framer = f; setRange(days[0], days[days.length - 1]); }); });
  const scale = $derived(framer && layer === 'animate' ? (tl.window, frameScale(framer, tl.window)) : 1);
  const series = $derived(framer ? framer.series(tl.window === 'cumulative' ? 'cumulative' : 'day', loc.p ? new Set(loc.found.map(s => s.fac)) : null).filter(s => s[0] <= tl.last) : []);
  $effect(() => {
    if (!api || !layerMod) return;
    if (isDiff) { if (!diffValues) return; api.setDeckLayers([makeDiffLayer(layerMod.H3HexagonLayer, weights, diffValues, diffScaleV, layer, { triggers: [layer, diffScaleV, tl.day], onHover: h => hover = h, onClick: h3 => import('h3-js').then(m => { const [lat, lng] = m.cellToLatLng(h3); onMapClick([lat, lng]); }) })]); return; }
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
  const sumOf = (found) => found.reduce((t, s) => t + (idx.stations[s.fac]?.total || 0), 0);
  const totalB = $derived(sumOf(locB.found));
  const ratio = (a, b) => b ? (a / b).toFixed(a / b >= 10 ? 0 : 1) + '×' : (a ? '∞' : '–');
  const cmpA = $derived(locB.p ? ` · vs B: ${ratio(total, totalB)}` : '');
  const cmpB = $derived(locB.p ? `${locB.found.length} stations · ${usd(totalB)} booked · ${ratio(totalB, total)} of A` : '');
  const fmtHover = (p) => isDiff ? `${p.value > 0 ? DIFFS[layer].pos : DIFFS[layer].neg} by ${usd(Math.abs(p.value))}` : layer === 'animate' ? `${usd(p.raw)} this ${tl.window}` : `${METRICS[layer]?.[0]}: ${layer === 'pp' ? '$' + (+p.pp).toFixed(2) : layer === 'spots' ? p.spots : layer === 'ps' ? '$' + p.ps : usd(p.booked)} · ${Number(p.pop).toLocaleString()} people · ${p.stations} stations with buys`;
</script>
<svelte:head><title>Adfall</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={ready} onclick={onMapClick} />
  <div class="float">
    <Search />
    <div class="chips" style="margin:6px 0 0">{#each LAYERS.slice(0, 6) as [k, l]}<span class="chip" class:on={layer === k} onclick={() => layer = k} role="button" tabindex="0">{l}</span>{/each}</div>
    <div class="chips" style="margin:4px 0 0"><span class="muted small" style="align-self:center">Difference:</span>{#each LAYERS.slice(6) as [k, l]}<span class="chip" class:on={layer === k} onclick={() => layer = k} role="button" tabindex="0">{l}</span>{/each}</div>
    {#if isTile}<div class="muted small" style="margin-top:6px">{METRICS[layer][1]}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
    {:else if isDiff}<div class="muted small" style="margin-top:6px">{DIFFS[layer].desc}.{layer === 'wk' && tl.day ? ` Week ending ${tl.day}.` : ''} {hover ? fmtHover(hover) : ''}</div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({DIFFS[layer].negColor.join(',')})">■ {DIFFS[layer].neg}</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({DIFFS[layer].negColor.join(',')}), rgba(255,255,255,.1), rgb({DIFFS[layer].posColor.join(',')}))"></span><span style="color:rgb({DIFFS[layer].posColor.join(',')})">{DIFFS[layer].pos} ■</span></div>
    {:else if layer === 'animate'}<div class="muted small" style="margin-top:6px">Booked $ reaching each cell, by the window on the bar below.{hover ? ' ' + fmtHover(hover) : ''}</div>{/if}
    {#if pickingB}<div class="small" style="margin-top:6px;color:var(--pin-b)"><b>Click the map to drop pin B.</b> <span class="chip" onclick={() => pickingB = false} role="button" tabindex="0">cancel</span></div>{/if}
  </div>
  {#if loc.p}
    <Popover {api} anchor={loc.p} badge={locB.p ? 'A' : ''} title={loc.label} sub="{loc.found.length} stations reach here{covered.length ? ` · ${covered.length} with filings · ${usd(total)} booked ${idx.year}` : ' · none crawled yet'}{cmpA}" tabs={TABS} bind:active={tab} bind:collapsed onclose={() => { clearA(); clearB(); }}
      oncompare={locB.p ? null : () => pickingB = true} compareLabel="Compare…">
      {#if covered.length}<div class="catbar" style="margin:0 0 10px">{#each Object.entries(byCat).sort((a, b) => b[1] - a[1]) as [c, v]}<i style="width:{(100 * v / total).toFixed(1)}%;background:{CATS[c] || CATS.Other}" title="{c}: {usd(v)}"></i>{/each}</div>{/if}
      {#if tab === 'stations'}<StationsTab found={loc.found} p={loc.p} {idx} {api} />
      {:else if tab === 'money'}<MoneyTab found={loc.found} all={loc.all} {idx} />
      {:else if tab === 'ads'}<AdsTab found={loc.found} {idx} />
      {:else}<TimeTab found={loc.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if locB.p}
    <Popover {api} anchor={locB.p} badge="B" accent="#c96a0a" title={locB.label} sub={cmpB} tabs={TABS} bind:active={tabB} bind:collapsed={collapsedB} onclose={clearB}>
      {#if tabB === 'stations'}<StationsTab found={locB.found} p={locB.p} {idx} {api} />
      {:else if tabB === 'money'}<MoneyTab found={locB.found} all={loc.all} {idx} />
      {:else if tabB === 'ads'}<AdsTab found={locB.found} {idx} />
      {:else}<TimeTab found={locB.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if (layer === 'animate' || layer === 'wk') && framer}<Timeline {series} label={loc.p ? `${loc.found.length} stations here` : `${framer.byStation.size} stations`} />{/if}
  <div class="credit muted">Contours: FCC · Streams: NewsON · Money: FCC public political files · <a href="/about">About</a> · This product uses the FCC Data API but is not endorsed or certified by the FCC.</div>
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 360px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  .credit { position: absolute; left: 12px; bottom: 6px; z-index: 3; font-size: 10.5px; max-width: 60%; }
  @media (max-width: 800px) { .float { width: calc(100% - 24px); } .credit { display: none; } }
</style>

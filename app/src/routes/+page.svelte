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
  import NewsTab from '$lib/tabs/NewsTab.svelte';
  import { shares } from '$lib/color.svelte.js';
  import { DEM, REP, MID } from '$lib/palette.js';
  import { ui } from '$lib/url.svelte.js';
  import { loc, locB, setLocation, setLocationB, clearA, clearB } from '$lib/location.svelte.js';
  import { DIFFS, stationDiffs, composeDiff, makeDiffLayer, diffScale, composeParty, makePartyLayer } from '$lib/difflayer.js';
  import { tl, setRange } from '$lib/time.svelte.js';
  import { spendIndex, usd, num, CATS, get, stationDaily, hexWeights } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  import { installHexLayers, setHexLayer, resForZoom, layersFor, METRICS } from '$lib/hexlayers.js';
  import { Framer } from '$lib/frames.js';
  import { makeFrameLayer, frameScale, makePartyFrameLayer, partyFrameScale } from '$lib/framelayer.js';
  import { rampCss } from '$lib/palette.js';
  let api = $state(null), idx = $state.raw({ stations: {}, year: new Date().getFullYear() }), meta = $state.raw(null), zoom = $state(3.6);
  let collapsed = $state(false), collapsedB = $state(false), hover = $state.raw(null), pickingB = $state(false), weights = $state.raw(null);
  let layerMod = $state.raw(null), lastDay = null, timeData = $state.raw(null);
  // one Framer per metric over the same daily rows (party = a Democratic and a Republican framer sharing the decay)
  const COL = { booked: 2, invoiced: 3, spots: 4 }, ANIM = [['booked', 'Booked $'], ['invoiced', 'Invoiced $'], ['spots', 'Spots aired'], ['party', 'Party share']];
  const cache = new Map();
  function framerFor(metric) { if (!timeData) return null; if (!cache.has(metric)) { const { daily, weights } = timeData; cache.set(metric, metric === 'party' ? { d: new Framer(daily, weights, 5), r: new Framer(daily, weights, 6) } : new Framer(daily, weights, COL[metric] ?? 2)); } return cache.get(metric); }
  const framer = $derived(timeData ? framerFor(ui.layer === 'wk' ? 'booked' : tl.metric) : null);
  const isPartyAnim = $derived(ui.layer === 'animate' && tl.metric === 'party');
  spendIndex().then(d => idx = d); get('tiles/meta.json').then(m => meta = m);
  const LAYERS = [['coverage', 'Airshed'], ['booked', 'Money'], ['pp', '$ / person'], ['spots', 'Spots'], ['ps', '$ / spot'], ['animate', 'Over time ▶'], ['party', 'Party share'], ['bi', 'Booked − invoiced'], ['wk', 'Week vs last']];
  const isDiff = $derived(ui.layer in DIFFS);
  const isTile = $derived(!(ui.layer === 'coverage' || ui.layer === 'animate' || isDiff));
  const res = $derived(resForZoom(zoom, meta));          // 8 (where it exists) from zoom 9.3, 7 from 6.3, else 5
  function ready(a) { api = a; installHexLayers(a.map); zoom = a.map.getZoom(); /* a camera from the URL hash lands before zoomend can fire */ a.onZoom(z => zoom = z); a.map.on('mousemove', e => { if (!isTile) return; const f = a.map.queryRenderedFeatures(e.point, { layers: layersFor(res) })[0]; hover = f ? f.properties : null; }); }
  $effect(() => { if (api?.map?.getLayer('hex5-fill')) setHexLayer(api.map, { visible: isTile, res, metric: isTile ? ui.layer : 'booked', meta }); });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); if (api.map.getZoom() < 6 && Date.now() - ui.camApplied > 1000) api.flyTo(loc.p, 6.5); } else if (api) { api.setContours({ type: 'FeatureCollection', features: [] }); api.setMarker(null); } });
  $effect(() => { if (!api) return; if (locB.p) { api.setContoursB(toGeoJSON(locB.found)); api.setMarkerB(locB.p); } else { api.setContoursB({ type: 'FeatureCollection', features: [] }); api.setMarkerB(null); } });
  function onMapClick(p) { if (pickingB) { pickingB = false; setLocationB(p); } else setLocation(p); }
  $effect(() => { if ((isDiff || ui.layer === 'animate') && !weights) hexWeights(5).then(w => weights = w); });
  $effect(() => { if (isDiff && !layerMod) import('@deck.gl/geo-layers').then(m => layerMod = m); });
  const partyVals = $derived(ui.layer === 'party' && weights ? composeParty(weights, idx) : null);
  const partyScale = $derived(partyVals ? diffScale(partyVals.total) : 1);
  const diffValues = $derived(isDiff && ui.layer !== 'party' && weights && (ui.layer !== 'wk' || (framer && tl.day)) ? composeDiff(weights, stationDiffs(ui.layer, idx, framer, tl.day)) : null);
  const diffScaleV = $derived(diffValues ? diffScale(diffValues) : 1);
  // animate / week-vs-last layers: load the daily rows and weights on first use
  $effect(() => { if ((ui.layer === 'animate' || ui.layer === 'wk') && !timeData) Promise.all([stationDaily(), hexWeights(5), import('@deck.gl/geo-layers')]).then(([d, w, m]) => { layerMod = m; timeData = { daily: d, weights: w }; const days = framerFor('booked').dayList; setRange(days[0], days[days.length - 1]); }); });
  const scale = $derived(!framer || ui.layer !== 'animate' ? 1 : isPartyAnim ? (tl.window, partyFrameScale(framer.d, framer.r, tl.window)) : (tl.window, frameScale(framer, tl.window)));
  const series = $derived.by(() => {
    if (!framer) return [];
    const win = tl.window === 'cumulative' ? 'cumulative' : 'day', facs = loc.p ? new Set(loc.found.map(s => s.fac)) : null, inRange = s => s[0] >= tl.first && s[0] <= tl.last;
    if (isPartyAnim) { const a = framer.d.series(win, facs), b = framer.r.series(win, facs); return a.map((s, i) => [s[0], s[1] + (b[i]?.[1] || 0)]).filter(inRange); }
    return framer.series(win, facs).filter(inRange);
  });
  $effect(() => {
    if (!api || !layerMod) return;
    if (ui.layer === 'party') { if (!partyVals) return; api.setDeckLayers([makePartyLayer(layerMod.H3HexagonLayer, weights, partyVals, partyScale, { triggers: [partyScale], onHover: h => hover = h, onClick: h3 => import('h3-js').then(m => { const [lat, lng] = m.cellToLatLng(h3); onMapClick([lat, lng]); }) })]); return; }
    if (isDiff) { if (!diffValues) return; api.setDeckLayers([makeDiffLayer(layerMod.H3HexagonLayer, weights, diffValues, diffScaleV, ui.layer, { triggers: [ui.layer, diffScaleV, tl.day], onHover: h => hover = h, onClick: h3 => import('h3-js').then(m => { const [lat, lng] = m.cellToLatLng(h3); onMapClick([lat, lng]); }) })]); return; }
    if (ui.layer !== 'animate' || !framer || !tl.day) { api.setDeckLayers([]); return; }
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.937 : 0.865) : 0;
    const fs = isPartyAnim ? [framer.d, framer.r] : [framer];
    if (!decay) fs.forEach(f => f.reset());
    fs.forEach(f => f.frame(tl.day, tl.window, { decay }));
    const opts = { max: scale, speed: tl.speed, triggers: [tl.day, tl.window, tl.metric, scale, tl.trails], onHover: h => hover = h, onClick: h3 => import('h3-js').then(m => { const [lat, lng] = m.cellToLatLng(h3); setLocation([lat, lng]); }) };
    api.setDeckLayers([isPartyAnim ? makePartyFrameLayer(layerMod.H3HexagonLayer, framer.d, framer.r, opts) : makeFrameLayer(layerMod.H3HexagonLayer, framer, opts)]);
  });
  const covered = $derived(loc.found.filter(s => idx.stations[s.fac]?.total));
  const total = $derived(covered.reduce((t, s) => t + idx.stations[s.fac].total, 0));
  const byCat = $derived.by(() => { const m = {}; for (const s of covered) for (const [c, v] of Object.entries(idx.stations[s.fac].by_category)) m[c] = (m[c] || 0) + v; return m; });
  const byParty = $derived.by(() => { const m = {}; for (const s of covered) for (const [c, v] of Object.entries(idx.stations[s.fac].by_party || {})) m[c] = (m[c] || 0) + v; return m; });
  const TABS = [{ id: 'stations', label: 'Stations' }, { id: 'money', label: 'Money' }, { id: 'ads', label: 'Ads' }, { id: 'news', label: 'Newscasts' }, { id: 'time', label: 'Over time' }];
  const sumOf = (found) => found.reduce((t, s) => t + (idx.stations[s.fac]?.total || 0), 0);
  const totalB = $derived(sumOf(locB.found));
  const ratio = (a, b) => b ? (a / b).toFixed(a / b >= 10 ? 0 : 1) + '×' : (a ? '∞' : '–');
  const cmpA = $derived(locB.p ? ` · vs B: ${ratio(total, totalB)}` : '');
  const cmpB = $derived(locB.p ? `${where(locB)}${locB.found.length} stations · ${usd(totalB)} booked · ${ratio(totalB, total)} of A` : '');
  const fmtP = (p) => `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  const where = (l) => (l.market ? `${l.market} market · ` : '') + fmtP(l.p) + ' · ';
  const fmtHover = (p) => ui.layer === 'party' ? (p.total ? `${Math.round(100 * p.share)}% Democratic of ${usd(p.total)} candidate $${p.unk ? ` (+${usd(p.unk)} unknown party)` : ''}` : 'no candidate money') : isDiff ? `${p.value > 0 ? DIFFS[ui.layer].pos : DIFFS[ui.layer].neg} by ${usd(Math.abs(p.value))}` : ui.layer === 'animate' ? (p.party ? (p.total ? `${Math.round(100 * p.share)}% Democratic of ${usd(p.total)} candidate $ this ${tl.window}` : 'no candidate money') : `${tl.metric === 'spots' ? num(p.raw) + ' spots' : usd(p.raw)} this ${tl.window}`) : `${METRICS[ui.layer]?.[0]}: ${ui.layer === 'pp' ? '$' + (+p.pp).toFixed(2) : ui.layer === 'spots' ? p.spots : ui.layer === 'ps' ? '$' + p.ps : usd(p.booked)} · ${Number(p.pop).toLocaleString()} people · ${p.stations} stations with buys`;
</script>
<svelte:head><title>Adfall</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={ready} onclick={onMapClick} />
  <div class="float">
    <Search />
    <div class="chips" style="margin:6px 0 0">{#each LAYERS.slice(0, 6) as [k, l]}<span class="chip" class:on={ui.layer === k} onclick={() => ui.layer = k} role="button" tabindex="0">{l}</span>{/each}</div>
    <div class="chips" style="margin:4px 0 0"><span class="muted small" style="align-self:center">Party, change:</span>{#each LAYERS.slice(6) as [k, l]}<span class="chip" class:on={ui.layer === k} onclick={() => ui.layer = k} role="button" tabindex="0">{l}</span>{/each}</div>
    {#if isTile}<div class="muted small" style="margin-top:6px">{METRICS[ui.layer][1]}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
    {:else if ui.layer === 'party'}<div class="muted small" style="margin-top:6px">{DIFFS.party.desc}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({REP.join(',')})">■ Republican</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({REP.join(',')}), rgb({MID.join(',')}), rgb({DEM.join(',')}))"></span><span style="color:rgb({DEM.join(',')})">Democratic ■</span></div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:4px"><span>less candidate $</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgba(158,160,168,.1), rgba(158,160,168,1))"></span><span>more</span></div>
    {:else if isDiff}<div class="muted small" style="margin-top:6px">{DIFFS[ui.layer].desc}.{ui.layer === 'wk' && tl.day ? ` Week ending ${tl.day}.` : ''} {hover ? fmtHover(hover) : ''}</div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({DIFFS[ui.layer].negColor.join(',')})">■ {DIFFS[ui.layer].neg}</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({DIFFS[ui.layer].negColor.join(',')}), rgba(255,255,255,.1), rgb({DIFFS[ui.layer].posColor.join(',')}))"></span><span style="color:rgb({DIFFS[ui.layer].posColor.join(',')})">{DIFFS[ui.layer].pos} ■</span></div>
    {:else if ui.layer === 'animate'}<div class="chips" style="margin:6px 0 0">{#each ANIM as [k, l]}<span class="chip" class:on={tl.metric === k} onclick={() => tl.metric = k} role="button" tabindex="0">{l}</span>{/each}</div>
      <div class="muted small" style="margin-top:4px">{isPartyAnim ? 'Candidate $ reaching each cell, blue to red by Democratic share, fainter where there is less of it' : `${ANIM.find(a => a[0] === tl.metric)?.[1]} reaching each cell`}, by the window on the bar below.{hover ? ' ' + fmtHover(hover) : ''}</div>
      {#if isPartyAnim}<div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({REP.join(',')})">■ Republican</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({REP.join(',')}), rgb({MID.join(',')}), rgb({DEM.join(',')}))"></span><span style="color:rgb({DEM.join(',')})">Democratic ■</span></div>
      {:else}<div class="legend" style="display:block;margin-top:6px"><div style="height:8px;border-radius:4px;background:{rampCss}"></div><div class="row" style="font-size:11px"><span>0</span><span style="margin-left:auto">{tl.metric === 'spots' ? num(scale) : usd(scale)}+</span></div></div>{/if}{/if}
    {#if pickingB}<div class="small" style="margin-top:6px;color:var(--pin-b)"><b>Click the map to drop pin B.</b> <span class="chip" onclick={() => pickingB = false} role="button" tabindex="0">cancel</span></div>{/if}
  </div>
  {#if loc.p}
    <Popover {api} anchor={loc.p} badge={locB.p ? 'A' : ''} title={loc.label} sub="{where(loc)}{loc.found.length} stations reach here{covered.length ? ` · ${covered.length} with filings · ${usd(total)} booked ${idx.year}` : ' · none crawled yet'}{cmpA}" tabs={TABS} bind:active={ui.tab} bind:collapsed onclose={() => { clearA(); clearB(); }}
      oncompare={locB.p ? null : () => pickingB = true} compareLabel="Compare…">
      {#if covered.length}<div class="catbar" style="margin:0 0 10px">{#each shares({ by_category: byCat, by_party: byParty }) as [c, v, col]}<i style="width:{(100 * v / total).toFixed(1)}%;background:{col}" title="{c}: {usd(v)}"></i>{/each}</div>{/if}
      {#if ui.tab === 'stations'}<StationsTab found={loc.found} p={loc.p} {idx} {api} />
      {:else if ui.tab === 'money'}<MoneyTab found={loc.found} all={loc.all} {idx} />
      {:else if ui.tab === 'ads'}<AdsTab found={loc.found} {idx} />
      {:else if ui.tab === 'news'}<NewsTab found={loc.found} {idx} />
      {:else}<TimeTab found={loc.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if locB.p}
    <Popover {api} anchor={locB.p} badge="B" accent="#c96a0a" prefer="left" title={locB.label} sub={cmpB} tabs={TABS} bind:active={ui.tabB} bind:collapsed={collapsedB} onclose={clearB}>
      {#if ui.tabB === 'stations'}<StationsTab found={locB.found} p={locB.p} {idx} {api} />
      {:else if ui.tabB === 'money'}<MoneyTab found={locB.found} all={loc.all} {idx} />
      {:else if ui.tabB === 'ads'}<AdsTab found={locB.found} {idx} />
      {:else if ui.tabB === 'news'}<NewsTab found={locB.found} {idx} />
      {:else}<TimeTab found={locB.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if (ui.layer === 'animate' || ui.layer === 'wk') && framer}<Timeline {series} label={loc.p ? `${loc.found.length} stations here` : `${(framer.byStation || framer.d.byStation).size} stations`} />{/if}
  <div class="credit muted">Contours: FCC · Streams: NewsON · Money: FCC public political files · <a href="/about">About</a> · This product uses the FCC Data API but is not endorsed or certified by the FCC.</div>
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 360px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  .credit { position: absolute; left: 12px; bottom: 6px; z-index: 3; font-size: 10.5px; max-width: 60%; }
  @media (max-width: 800px) { .float { width: calc(100% - 24px); } .credit { display: none; } }
</style>

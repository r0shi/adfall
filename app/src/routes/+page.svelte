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
  import { tl, ANIM } from '$lib/time.svelte.js';
  import { spendIndex, usd, num, CATS, get, hexWeights, forget } from '$lib/data.js';
  import { td, loadTimeData, retryTimeData, framerFor, geoLayers } from '$lib/timedata.svelte.js';
  import LoadPanel from '$lib/LoadPanel.svelte';
  import ColorBy from '$lib/ColorBy.svelte';
  import { lazy, describe } from '$lib/recover.js';
  import { toGeoJSON } from '$lib/geo.js';
  import { installHexLayers, setHexLayer, resForZoom, layersFor, METRICS } from '$lib/hexlayers.js';
  import { makeFrameLayer, frameScale, makePartyFrameLayer, partyFrameScale } from '$lib/framelayer.js';
  import { rampCss } from '$lib/palette.js';
  let api = $state(null), idx = $state.raw({ stations: {}, year: new Date().getFullYear() }), meta = $state.raw(null), zoom = $state(3.6);
  let collapsed = $state(false), collapsedB = $state(false), hover = $state.raw(null), pickingB = $state(false), weights = $state.raw(null);
  let layerMod = $state.raw(null), lastDay = null, loadErr = $state(null);
  // one Framer per metric over the same daily rows (timedata.svelte.js; party = a Democratic and a Republican framer sharing the decay)
  const framer = $derived(td.status === 'ready' ? framerFor(ui.layer === 'wk' ? 'booked' : tl.metric) : null);
  const isPartyAnim = $derived(ui.layer === 'animate' && tl.metric === 'party');
  spendIndex().then(d => idx = d); get('tiles/meta.json').then(m => meta = m);
  // still layers, then the comparisons; Over time is not in the list: it leads the box as its own button
  const LAYERS = [['coverage', 'Airshed'], ['booked', 'Money'], ['pp', '$ / person'], ['spots', 'Spots'], ['ps', '$ / spot']];
  const COMPARE = [['party', 'Party share'], ['bi', 'Booked − invoiced'], ['wk', 'Week vs last']];
  let stillLayer = 'coverage';                            // where the Over time button returns to when switched off
  function toggleTime() { if (ui.layer === 'animate') ui.layer = stillLayer; else { stillLayer = ui.layer; ui.layer = 'animate'; } }
  const timeLayer = $derived(ui.layer === 'animate' || ui.layer === 'wk');   // layers driven by the timeline bar; their key docks above it
  const isDiff = $derived(ui.layer in DIFFS);
  const isTile = $derived(!(ui.layer === 'coverage' || ui.layer === 'animate' || isDiff));
  const res = $derived(resForZoom(zoom, meta));          // 8 (where it exists) from zoom 9.3, 7 from 6.3, else 5
  function ready(a) { api = a; installHexLayers(a.map); zoom = a.map.getZoom(); /* a camera from the URL hash lands before zoomend can fire */ a.onZoom(z => zoom = z); a.map.on('mousemove', e => { if (!isTile) return; const f = a.map.queryRenderedFeatures(e.point, { layers: layersFor(res) })[0]; hover = f ? f.properties : null; }); }
  $effect(() => { if (api?.map?.getLayer('hex5-fill')) setHexLayer(api.map, { visible: isTile, res, metric: isTile ? ui.layer : 'booked', meta }); });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); if (api.map.getZoom() < 6 && Date.now() - ui.camApplied > 1000) api.flyTo(loc.p, 6.5); } else if (api) { api.setContours({ type: 'FeatureCollection', features: [] }); api.setMarker(null); } });
  $effect(() => { if (!api) return; if (locB.p) { api.setContoursB(toGeoJSON(locB.found)); api.setMarkerB(locB.p); } else { api.setContoursB({ type: 'FeatureCollection', features: [] }); api.setMarkerB(null); } });
  function onMapClick(p) { if (pickingB) { pickingB = false; setLocationB(p); } else setLocation(p); }
  $effect(() => { if ((isDiff || ui.layer === 'animate') && !weights && !loadErr) hexWeights(5).then(w => weights = w).catch(e => loadErr = describe(e)); });
  $effect(() => { if (isDiff && !layerMod && !loadErr) lazy(() => import('@deck.gl/geo-layers')).then(m => layerMod = m).catch(e => loadErr = describe(e)); });
  $effect(() => { if (td.status === 'ready' && !layerMod) layerMod = geoLayers(); });
  // the party / change layers load only the weights and the layer module; a failure there is shown in their panel
  const diffState = $derived(loadErr ? { status: 'error', error: loadErr } : ui.layer === 'wk' ? td : { status: 'idle' });
  function retryDiff() { loadErr = null; weights = null; layerMod = null; forget('hex/weights_r5.json'); if (ui.layer === 'wk') retryTimeData(); }
  const partyVals = $derived(ui.layer === 'party' && weights ? composeParty(weights, idx) : null);
  const partyScale = $derived(partyVals ? diffScale(partyVals.total) : 1);
  const diffValues = $derived(isDiff && ui.layer !== 'party' && weights && (ui.layer !== 'wk' || (framer && tl.day)) ? composeDiff(weights, stationDiffs(ui.layer, idx, framer, tl.day)) : null);
  const diffScaleV = $derived(diffValues ? diffScale(diffValues) : 1);
  // animate / week-vs-last layers: load the daily rows and weights on first use
  $effect(() => { if (ui.layer === 'animate' || ui.layer === 'wk') loadTimeData(); });
  const scale = $derived(!framer || ui.layer !== 'animate' ? 1 : isPartyAnim ? (tl.window, partyFrameScale(framer.d, framer.r, tl.window)) : (tl.window, frameScale(framer, tl.window)));
  const series = $derived.by(() => {
    if (!framer) return [];
    const win = tl.window === 'cumulative' ? 'cumulative' : 'day', facs = loc.p ? new Set(loc.found.map(s => s.fac)) : null, inRange = s => s[0] >= tl.first && s[0] <= tl.last;
    if (isPartyAnim) { const a = framer.d.series(win, facs), b = framer.r.series(win, facs); return a.map((s, i) => [s[0], s[1] + (b[i]?.[1] || 0)]).filter(inRange); }
    return framer.series(win, facs).filter(inRange);
  });
  $effect(() => {
    if (!api || !layerMod) return;
    if (ui.layer === 'party') { if (!partyVals) return; api.setDeckLayers([makePartyLayer(layerMod.H3HexagonLayer, weights, partyVals, partyScale, { triggers: [partyScale], onHover: h => hover = h, onClick: h3 => lazy(() => import('h3-js')).then(m => { const [lat, lng] = m.cellToLatLng(h3); onMapClick([lat, lng]); }) })]); return; }
    if (isDiff) { if (!diffValues) return; api.setDeckLayers([makeDiffLayer(layerMod.H3HexagonLayer, weights, diffValues, diffScaleV, ui.layer, { triggers: [ui.layer, diffScaleV, tl.day], onHover: h => hover = h, onClick: h3 => lazy(() => import('h3-js')).then(m => { const [lat, lng] = m.cellToLatLng(h3); onMapClick([lat, lng]); }) })]); return; }
    if (ui.layer !== 'animate' || !framer || !tl.day) { api.setDeckLayers([]); return; }
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.937 : 0.865) : 0;
    const fs = isPartyAnim ? [framer.d, framer.r] : [framer];
    if (!decay) fs.forEach(f => f.reset());
    fs.forEach(f => f.frame(tl.day, tl.window, { decay }));
    const opts = { max: scale, speed: tl.speed, triggers: [tl.day, tl.window, tl.metric, scale, tl.trails], onHover: h => hover = h, onClick: h3 => lazy(() => import('h3-js')).then(m => { const [lat, lng] = m.cellToLatLng(h3); setLocation([lat, lng]); }) };
    api.setDeckLayers([isPartyAnim ? makePartyFrameLayer(layerMod.H3HexagonLayer, framer.d, framer.r, opts) : makeFrameLayer(layerMod.H3HexagonLayer, framer, opts)]);
  });
  const covered = $derived(loc.found.filter(s => idx.stations[s.fac]?.total));
  const total = $derived(covered.reduce((t, s) => t + idx.stations[s.fac].total, 0));
  // the buyer mix reaching a pin (the share bar under the tabs, next to the Color by switch that recolors it)
  function mixOf(found) {
    const m = { total: 0, by_category: {}, by_party: {} };
    for (const s of found) { const st = idx.stations[s.fac]; if (!st?.total) continue; m.total += st.total;
      for (const [c, v] of Object.entries(st.by_category)) m.by_category[c] = (m.by_category[c] || 0) + v;
      for (const [c, v] of Object.entries(st.by_party || {})) m.by_party[c] = (m.by_party[c] || 0) + v; }
    return m;
  }
  const mixA = $derived(mixOf(loc.found)), mixB = $derived(mixOf(locB.found));
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
{#snippet colorRow(m)}
  <div class="colorrow">{#if m.total}<div class="catbar">{#each shares(m) as [c, v, col]}<i style="width:{(100 * v / m.total).toFixed(1)}%;background:{col}" title="{c}: {usd(v)}"></i>{/each}</div>{:else}<span class="muted small" style="flex:1">No filings yet</span>{/if}<ColorBy /></div>
{/snippet}
<svelte:head><title>Adfall</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={ready} onclick={onMapClick} />
  <div class="float">
    <Search />
    <div class="layers">
      <button class="otbtn" class:on={ui.layer === 'animate'} aria-pressed={ui.layer === 'animate'} onclick={toggleTime} title="Watch the money land day by day; playback is chosen on the bar at the bottom">
        <span class="otico" aria-hidden="true">{#if ui.layer === 'animate'}<svg viewBox="0 0 16 16" width="12" height="12"><rect x="3" y="3" width="10" height="10" rx="1.5" fill="currentColor" /></svg>{:else}<svg viewBox="0 0 16 16" width="12" height="12"><path d="M4 2.2v11.6a.8.8 0 0 0 1.2.7l9.3-5.8a.8.8 0 0 0 0-1.4L5.2 1.5A.8.8 0 0 0 4 2.2z" fill="currentColor" /></svg>{/if}</span>
        <span>Over time</span>
      </button>
      <div class="lchips">
        <div class="chips">{#each LAYERS as [k, l]}<span class="chip" class:on={ui.layer === k} onclick={() => ui.layer = k} onkeydown={e => e.key === 'Enter' && (ui.layer = k)} role="button" tabindex="0">{l}</span>{/each}</div>
        <div class="chips cmp">{#each COMPARE as [k, l]}<span class="chip" class:on={ui.layer === k} onclick={() => ui.layer = k} onkeydown={e => e.key === 'Enter' && (ui.layer = k)} role="button" tabindex="0">{l}</span>{/each}</div>
      </div>
    </div>
    {#if isTile}<div class="desc muted small">{METRICS[ui.layer][1]}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
    {:else if ui.layer === 'party'}<div class="desc muted small">{DIFFS.party.desc}. {hover ? fmtHover(hover) : 'Hover a cell.'}</div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({REP.join(',')})">■ Republican</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({REP.join(',')}), rgb({MID.join(',')}), rgb({DEM.join(',')}))"></span><span style="color:rgb({DEM.join(',')})">Democratic ■</span></div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:4px"><span>less candidate $</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgba(158,160,168,.1), rgba(158,160,168,1))"></span><span>more</span></div>
      <LoadPanel state={diffState} what="the map data" onretry={retryDiff} />
    {:else if ui.layer === 'bi'}<div class="desc muted small">{DIFFS.bi.desc}. {hover ? fmtHover(hover) : ''}</div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:6px"><span style="color:rgb({DIFFS.bi.negColor.join(',')})">■ {DIFFS.bi.neg}</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({DIFFS.bi.negColor.join(',')}), rgba(255,255,255,.1), rgb({DIFFS.bi.posColor.join(',')}))"></span><span style="color:rgb({DIFFS.bi.posColor.join(',')})">{DIFFS.bi.pos} ■</span></div>
      <LoadPanel state={diffState} what="the map data" onretry={retryDiff} />{/if}
    {#if pickingB}<div class="small" style="margin-top:6px;color:var(--pin-b)"><b>Click the map to drop pin B.</b> <span class="chip" onclick={() => pickingB = false} role="button" tabindex="0">cancel</span></div>{/if}
  </div>
  {#if loc.p}
    <Popover {api} anchor={loc.p} badge={locB.p ? 'A' : ''} title={loc.label} sub="{where(loc)}{loc.found.length} stations reach here{covered.length ? ` · ${covered.length} with filings · ${usd(total)} booked ${idx.year}` : ' · none crawled yet'}{cmpA}" tabs={TABS} bind:active={ui.tab} bind:collapsed onclose={() => { clearA(); clearB(); }}
      oncompare={locB.p ? null : () => pickingB = true} compareLabel="Compare…">
      {@render colorRow(mixA)}
      {#if ui.tab === 'stations'}<StationsTab found={loc.found} p={loc.p} {idx} {api} />
      {:else if ui.tab === 'money'}<MoneyTab found={loc.found} all={loc.all} {idx} />
      {:else if ui.tab === 'ads'}<AdsTab found={loc.found} {idx} />
      {:else if ui.tab === 'news'}<NewsTab found={loc.found} {idx} />
      {:else}<TimeTab found={loc.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if locB.p}
    <Popover {api} anchor={locB.p} badge="B" accent="#c96a0a" prefer="left" title={locB.label} sub={cmpB} tabs={TABS} bind:active={ui.tabB} bind:collapsed={collapsedB} onclose={clearB}>
      {@render colorRow(mixB)}
      {#if ui.tabB === 'stations'}<StationsTab found={locB.found} p={locB.p} {idx} {api} />
      {:else if ui.tabB === 'money'}<MoneyTab found={locB.found} all={loc.all} {idx} />
      {:else if ui.tabB === 'ads'}<AdsTab found={locB.found} {idx} />
      {:else if ui.tabB === 'news'}<NewsTab found={locB.found} {idx} />
      {:else}<TimeTab found={locB.found} {idx} />{/if}
    </Popover>
  {/if}
  {#if timeLayer}
    <div class="dock">
      <div class="key">
        {#if ui.layer === 'animate'}
          <div class="keyhead">{isPartyAnim ? 'Candidate $ by Democratic share' : `${ANIM.find(a => a[0] === tl.metric)?.[1]} reaching each cell`}<span class="muted">{` · per ${tl.window === 'cumulative' ? 'cycle to date' : tl.window}`}</span></div>
          {#if isPartyAnim}<div class="keyramp"><span style="color:rgb({REP.join(',')})">Rep.</span><i style="background:linear-gradient(90deg, rgb({REP.join(',')}), rgb({MID.join(',')}), rgb({DEM.join(',')}))"></i><span style="color:rgb({DEM.join(',')})">Dem.</span></div>
            <div class="muted keynote">Fainter where there is less candidate money</div>
          {:else}<div class="keyramp"><span>0</span><i style="background:{rampCss}"></i><span>{tl.metric === 'spots' ? num(scale) : usd(scale)}+</span></div>{/if}
          <LoadPanel state={td} what="the timeline data" onretry={retryTimeData} />
        {:else}
          <div class="keyhead">{DIFFS.wk.desc}</div>
          <div class="keyramp"><span style="color:rgb({DIFFS.wk.negColor.join(',')})">{DIFFS.wk.neg}</span><i style="background:linear-gradient(90deg, rgb({DIFFS.wk.negColor.join(',')}), rgba(255,255,255,.1), rgb({DIFFS.wk.posColor.join(',')}))"></i><span style="color:rgb({DIFFS.wk.posColor.join(',')})">{DIFFS.wk.pos}</span></div>
          <LoadPanel state={diffState} what="the map data" onretry={retryDiff} />
        {/if}
        <div class="keyhover" class:muted={!hover}>{hover ? fmtHover(hover) : 'Hover a cell for its numbers.'}</div>
      </div>
      {#if framer}<Timeline {series} mode={ui.layer} label={loc.p ? `${loc.found.length} stations here` : `${(framer.byStation || framer.d.byStation).size} stations`} />{/if}
    </div>
  {/if}
  <div class="credit muted">Contours: FCC · Streams: NewsON · Money: FCC public political files · <a href="/about">About</a> · This product uses the FCC Data API but is not endorsed or certified by the FCC.</div>
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 416px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  .layers { display: flex; gap: 8px; align-items: stretch; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }
  .otbtn { flex: none; width: 66px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 8px 4px;
    font-size: 12px; line-height: 1.1; white-space: nowrap; color: var(--accent); background: var(--accent-soft); border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 10px; }
  .otbtn:hover { border-color: var(--accent); }
  .otico { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: #fff; }
  .otico svg { margin-left: 1px; }
  .otbtn.on { background: var(--accent); color: #fff; border-color: var(--accent); }
  .otbtn.on .otico { background: #fff; color: var(--accent); }
  .otbtn.on .otico svg { margin-left: 0; }
  .lchips { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; gap: 6px; }
  .lchips .chips { margin: 0; gap: 5px; }
  .lchips .chip { padding: 3px 7px; font-size: 12px; }
  .chips.cmp { padding-top: 6px; border-top: 1px dashed var(--line); }
  .desc { margin-top: 8px; }
  .dock { position: absolute; left: 12px; right: 12px; bottom: 12px; z-index: 4; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; pointer-events: none; }
  .dock > :global(*) { align-self: stretch; }
  .dock > .key { align-self: flex-start; }
  .key { pointer-events: auto; width: 300px; max-width: 100%; padding: 8px 10px; border-radius: 10px; font-size: 12px;
    background: color-mix(in srgb, var(--bg) 80%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); box-shadow: 0 2px 10px rgb(0 0 0 / 0.1); }
  .keyhead { font-weight: 600; line-height: 1.3; }
  .keyhead .muted { font-weight: 400; }
  .keyramp { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .keyramp i { flex: 1; height: 8px; border-radius: 4px; }
  .keynote { font-size: 11px; margin-top: 2px; }
  .keyhover { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--line); font-size: 11.5px; line-height: 1.35; }
  .key :global(.loadpanel) { margin-top: 6px; }
  .colorrow { display: flex; align-items: center; gap: 10px; margin: -2px 0 10px; }
  .colorrow .catbar { flex: 1; min-width: 40px; height: 8px; border-radius: 4px; margin: 0; }
  .credit { position: absolute; left: 12px; bottom: 6px; z-index: 3; font-size: 10.5px; max-width: 60%; }
  @media (max-width: 800px) {
    .float { left: 6px; top: 6px; width: calc(100% - 12px); padding: 8px 10px; }
    .layers { margin-top: 8px; padding-top: 8px; gap: 8px; }
    .dock { left: 6px; right: 6px; bottom: 6px; gap: 6px; }
    .key { width: auto; align-self: stretch; padding: 6px 10px; }
    .keyhover { display: none; }
    .credit { display: none; }
  }
</style>

<script>
  // "Watch the money move": full-bleed map, frames composed in the client, the global timeline bar below.
  // Metrics: booked $, invoiced $, spots aired, or party share (candidate $ colored by Democratic share, faded by amount).
  import MapView from '$lib/Map.svelte';
  import Timeline from '$lib/Timeline.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { tl } from '$lib/time.svelte.js';
  import { usd, num } from '$lib/data.js';
  import { td, loadTimeData, retryTimeData, framerFor, geoLayers } from '$lib/timedata.svelte.js';
  import LoadPanel from '$lib/LoadPanel.svelte';
  import { lazy } from '$lib/recover.js';
  import { makeFrameLayer, frameScale, makePartyFrameLayer, partyFrameScale } from '$lib/framelayer.js';
  import { rampCss, DEM, REP, MID } from '$lib/palette.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), scope = $state('all'), hover = $state.raw(null);
  loadTimeData();   // big data stays non-reactive in timedata.svelte.js; td.status is the signal
  const METRICS = { booked: ['Booked $'], invoiced: ['Invoiced $'], spots: ['Spots aired'], party: ['Party share'] };
  const framer = $derived(td.status === 'ready' ? framerFor(tl.metric) : null);
  const isParty = $derived(tl.metric === 'party');
  const facsHere = $derived(scope === 'here' && loc.p ? new Set(loc.found.map(s => s.fac)) : null);
  const series = $derived.by(() => {
    if (!framer) return [];
    const win = tl.window === 'cumulative' ? 'cumulative' : 'day', inRange = s => (!tl.first || s[0] >= tl.first) && (!tl.last || s[0] <= tl.last);
    if (isParty) { const a = framer.d.series(win, facsHere), b = framer.r.series(win, facsHere); return a.map((s, i) => [s[0], s[1] + (b[i]?.[1] || 0)]).filter(inRange); }
    return framer.series(win, facsHere).filter(inRange);
  });
  // stable color scale per window/metric: 98th percentile of cell values over sampled frames
  const scaleMax = $derived(!framer ? 1 : isParty ? (tl.window, partyFrameScale(framer.d, framer.r, tl.window)) : (tl.window, frameScale(framer, tl.window)));
  let lastDay = null;
  $effect(() => {
    const layerMod = geoLayers();
    if (!api || !framer || !tl.day || !layerMod) return;
    const forward = lastDay && tl.day > lastDay; lastDay = tl.day;
    const decay = tl.trails && forward ? (tl.window === 'day' ? 0.937 : 0.865) : 0;   // per step; a trail lasts ~20 steps
    const fs = isParty ? [framer.d, framer.r] : [framer];
    if (!decay) fs.forEach(f => f.reset());
    fs.forEach(f => f.frame(tl.day, tl.window, { decay, facs: facsHere }));
    const opts = { max: scaleMax, speed: tl.speed, triggers: [tl.day, tl.window, tl.metric, scaleMax, tl.trails, facsHere],
                   onHover: h => hover = h, onClick: h3 => lazy(() => import('h3-js')).then(m => { const [lat, lng] = m.cellToLatLng(h3); setLocation([lat, lng]); }) };
    api.setDeckLayers([isParty ? makePartyFrameLayer(layerMod.H3HexagonLayer, framer.d, framer.r, opts) : makeFrameLayer(layerMod.H3HexagonLayer, framer, opts)]);
  });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); } });
  const fmt = (v) => tl.metric === 'spots' ? num(v) : usd(v);
  const winLabel = $derived(tl.window === 'cumulative' ? 'accumulated through' : tl.window === 'week' ? 'in the week ending' : 'on');
</script>
<svelte:head><title>Over time · Adfall</title></svelte:head>
<div class="shell wide"><div class="mapwrap" style="height:100%">
  <MapView onready={a => api = a} onclick={p => setLocation(p)} zoom={4} />
  <div class="float">
    <b>Watch the money move</b>
    <LoadPanel state={td} what="the timeline data" onretry={retryTimeData} />
    <div class="muted small">{isParty ? 'Candidate $ reaching each cell, blue to red by Democratic share and fainter where there is less of it' : `${METRICS[tl.metric][0]} reaching each cell`}, {winLabel} the date below. Click a cell or the map to pick a place.</div>
    <div class="chips" style="margin:8px 0 0">{#each Object.entries(METRICS) as [k, [l]]}<span class="chip" class:on={tl.metric === k} onclick={() => tl.metric = k} role="button" tabindex="0">{l}</span>{/each}</div>
    <div class="chips" style="margin:4px 0 0"><span class="muted small">Scrubline:</span>
      <span class="chip" class:on={scope === 'all'} onclick={() => scope = 'all'} role="button" tabindex="0">All crawled</span>
      <span class="chip" class:on={scope === 'here'} onclick={() => scope = 'here'} role="button" tabindex="0" title={loc.p ? '' : 'Pick a place first'}>{loc.p ? `Reaching ${loc.label}` : 'Reaching a place'}</span></div>
    {#if hover}<div class="small" style="margin-top:8px">{#if hover.party}<b>{hover.total ? `${Math.round(100 * hover.share)}% Democratic` : 'no candidate money'}</b>{hover.total ? ` of ${usd(hover.total)} candidate $` : ''}{:else}<b>{fmt(hover.raw)}</b> this {tl.window === 'cumulative' ? 'cumulative' : tl.window}{tl.trails && hover.shown > hover.raw * 1.01 ? ` · shown ${fmt(hover.shown)} with trail` : ''}{/if}</div>{/if}
    {#if isParty}
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:8px"><span style="color:rgb({REP.join(',')})">■ Republican</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgb({REP.join(',')}), rgb({MID.join(',')}), rgb({DEM.join(',')}))"></span><span style="color:rgb({DEM.join(',')})">Democratic ■</span></div>
      <div class="legend" style="display:flex;align-items:center;gap:8px;margin-top:4px"><span>less candidate $</span><span style="flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg, rgba(158,160,168,.1), rgba(158,160,168,1))"></span><span>{usd(scaleMax)}+</span></div>
      <div class="muted" style="font-size:11px;margin-top:4px">Issue-group money and unknown-party candidates are left out.</div>
    {:else}
      <div class="legend" style="display:block;margin-top:8px"><div style="height:8px;border-radius:4px;background:{rampCss}"></div>
        <div class="row" style="font-size:11px"><span>0</span><span style="margin-left:auto">{fmt(scaleMax)}+</span></div></div>
    {/if}
  </div>
  {#if framer}<Timeline {series} label={facsHere ? `${facsHere.size} stations` : `${(framer.byStation || framer.d.byStation).size} stations`} />{/if}
</div></div>
<style>
  .float { position: absolute; top: 12px; left: 12px; z-index: 4; width: 300px; padding: 10px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 78%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  @media (max-width: 800px) { .float { width: calc(100% - 24px); } }
</style>

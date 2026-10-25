<script>
  import { rampCss } from '$lib/palette.js';
  // Density map on PMTiles: hex5 (national, z3-8) and hex7 (inside crawled coverage, z6-11) from ingest/tiles.py.
  import MapView from '$lib/Map.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { get, usd, num } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), meta = $state(null), metric = $state('booked'), resMode = $state('auto'), zoom = $state(3.6), hover = $state(null);
  get('tiles/meta.json').then(m => meta = m);
  const METRICS = {
    booked: ['Money reaching here', 'Booked $ spread over each station\'s coverage by population', 'booked', usd],
    pp: ['$ per person', 'Booked $ divided by people in the cell', 'pp', v => `$${(+v).toFixed(2)}`],
    spots: ['Spots aired', 'Invoiced airings reaching the cell, population-weighted', 'spots', num],
    ps: ['$ per spot', 'Booked $ per aired spot (what a spot costs where you live)', 'ps', v => `$${Math.round(v)}`],
    stations: ['Stations with buys', 'How many covering stations have political orders', 'stations', v => String(v)]
  };
  const prop = $derived(METRICS[metric][2]);
  const fmt = $derived(METRICS[metric][3]);
  const res = $derived(resMode === 'auto' ? (zoom >= 6.3 ? 7 : 5) : +resMode);
  const maxFor = (r) => meta?.hex?.[r]?.max?.[prop] || 1;
  const fillExpr = (r) => ['interpolate', ['linear'], ['sqrt', ['min', 1, ['/', ['to-number', ['get', prop]], maxFor(r)]]],
    0, 'rgba(255,240,230,0.15)', 0.35, 'rgba(240,170,170,0.55)', 1, 'rgba(200,16,46,0.9)'];
  function install(a) {
    api = a; const map = a.map;
    for (const r of [5, 7]) {
      map.addSource(`hex${r}`, { type: 'vector', url: `pmtiles://${location.origin}/data/tiles/hex${r}.pmtiles` });
      map.addLayer({ id: `hex${r}-fill`, type: 'fill', source: `hex${r}`, 'source-layer': `hex${r}`, paint: { 'fill-color': fillExpr(r), 'fill-opacity': 0.85 } }, 'contours-fill');
    }
    map.on('mousemove', (e) => {
      const f = map.queryRenderedFeatures(e.point, { layers: [`hex${res}-fill`] })[0];
      hover = f ? f.properties : null; map.getCanvas().style.cursor = f ? 'pointer' : '';
    });
    a.onZoom(z => zoom = z);
  }
  $effect(() => { if (!api?.map?.getLayer('hex5-fill') || !meta) return; for (const r of [5, 7]) { api.map.setPaintProperty(`hex${r}-fill`, 'fill-color', fillExpr(r)); api.map.setLayoutProperty(`hex${r}-fill`, 'visibility', r === res ? 'visible' : 'none'); } });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); } });
  function onclick(p) { setLocation(p); }
  const cells = $derived(meta?.hex?.[res]?.cells || 0);
</script>
<svelte:head><title>Map · Adfall</title></svelte:head>
<div class="shell">
  <aside class="panel">
    <header>
      <h1>Where the money lands</h1>
      <p class="tag">{METRICS[metric][1]}. Click a cell to see which stations reach it.</p>
      <div class="chips">{#each Object.entries(METRICS) as [k, [label]]}<span class="chip" class:on={metric === k} onclick={() => metric = k} role="button" tabindex="0">{label}</span>{/each}</div>
      <div class="chips small"><span class="muted">Cells:</span>
        {#each [['auto', 'Auto'], ['5', 'Coarse'], ['7', 'Fine']] as [k, label]}<span class="chip" class:on={resMode === k} onclick={() => resMode = k} role="button" tabindex="0">{label}</span>{/each}
        <span class="muted">res {res} · {num(cells)} cells with buys</span></div>
      <div class="legend" style="display:block">
        <div style="height:10px;border-radius:5px;background:{rampCss}"></div>
        <div class="row" style="font-size:11.5px"><span>0</span><span style="margin-left:auto">{fmt(maxFor(res))}+</span></div>
      </div>
    </header>
    <section>
      {#if hover}
        <div class="card"><b>{METRICS[metric][0]}: {fmt(hover[prop])}</b>
          <div class="muted small">{num(hover.pop)} people · {hover.stations} station{hover.stations === 1 ? '' : 's'} with political buys</div>
          <div class="muted small">booked {usd(hover.booked)} · invoiced {usd(hover.invoiced)} · {num(hover.spots)} spots aired · ${hover.pp}/person · ${num(hover.ps)}/spot</div></div>
      {:else}<div class="muted small">Hover a cell for its numbers.</div>{/if}
      {#if loc.p}
        <h2>{loc.label}</h2>
        <div class="muted small">{loc.found.length} stations reach this spot. <a href="/">See them →</a></div>
      {/if}
      <p class="muted small" style="margin-top:14px">Fine cells (H3 res 7, ~5 km²) exist only inside crawled stations' coverage; coarse cells (res 5, ~250 km²) are national. Money is spread by population, so $/person is flat inside one station's footprint and changes where coverage overlaps.</p>
    </section>
  </aside>
  <div class="mapwrap"><MapView onready={install} {onclick} /></div>
</div>

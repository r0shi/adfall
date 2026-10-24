<script>
  import MapView from '$lib/Map.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { hexTotal, usd, num } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), data = $state({}), metric = $state('booked'), resMode = $state('auto'), zoom = $state(3.6), hover = $state(null);
  hexTotal(5).then(d => data = { ...data, 5: d });
  const METRICS = {
    booked: ['Money reaching here', 'Booked $ spread over each station\'s coverage by population', r => r[1], usd],
    perperson: ['$ per person', 'Booked $ divided by people in the cell', r => r[4] > 0 ? r[1] / r[4] : 0, v => `$${v.toFixed(2)}`],
    spots: ['Spots aired', 'Invoiced airings reaching the cell, population-weighted', r => r[3], num],
    perspot: ['$ per spot', 'Booked $ per aired spot (what a spot costs where you live)', r => r[3] > 0 ? r[1] / r[3] : 0, v => `$${Math.round(v)}`],
    stations: ['Stations with buys', 'How many covering stations have political orders', r => r[5], v => String(v)]
  };
  const res = $derived(resMode === 'auto' ? (zoom >= 6.3 ? 7 : 5) : +resMode);
  $effect(() => { if (res === 7 && !data[7]) hexTotal(7).then(d => data = { ...data, 7: d }); });
  const cells = $derived(data[res]?.cells || []);
  const valueOf = $derived(METRICS[metric][2]);
  const fmt = $derived(METRICS[metric][3]);
  const scale = $derived.by(() => {
    const vals = cells.map(valueOf).filter(v => v > 0).sort((a, b) => a - b);
    return { max: vals[Math.floor(vals.length * 0.985)] || 1, n: vals.length };
  });
  const colorFor = (t) => t <= 0 ? [0, 0, 0, 0] : [255 - 55 * t, 240 - 224 * t, 230 - 184 * t, 60 + 180 * t];   // cream -> deep red
  $effect(() => {
    if (!api || !cells.length) return;
    const v = valueOf, mx = scale.max, f = fmt, r = res, m = metric;
    import('@deck.gl/geo-layers').then(({ H3HexagonLayer }) => api.setDeckLayers([new H3HexagonLayer({
      id: 'density', data: cells, getHexagon: c => c[0], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.8,
      getFillColor: c => colorFor(Math.sqrt(Math.min(1, v(c) / mx))),
      onClick: ({ object }) => { if (object) import('h3-js').then(h3 => { const [lat, lng] = h3.cellToLatLng(object[0]); setLocation([lat, lng]); }); },
      onHover: ({ object }) => { hover = object || null; },
      updateTriggers: { getFillColor: [m, r] }
    })], ({ object }) => object && { text: `${METRICS[m][0]}: ${f(v(object))}\n${num(object[4])} people · ${object[5]} station${object[5] === 1 ? '' : 's'} with buys\nbooked ${usd(object[1])} · invoiced ${usd(object[2])} · ${num(object[3])} spots` }));
  });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); } });
  const covered = $derived(cells.filter(c => c[1] > 0).length);
</script>
<svelte:head><title>Map · TV Wormhole</title></svelte:head>
<div class="shell">
  <aside class="panel">
    <header>
      <h1>Where the money lands</h1>
      <p class="tag">{METRICS[metric][1]}. Click a cell to see which stations reach it.</p>
      <div class="chips">{#each Object.entries(METRICS) as [k, [label]]}<span class="chip" class:on={metric === k} onclick={() => metric = k} role="button" tabindex="0">{label}</span>{/each}</div>
      <div class="chips small"><span class="muted">Cells:</span>
        {#each [['auto', 'Auto'], ['5', 'Coarse'], ['7', 'Fine']] as [k, label]}<span class="chip" class:on={resMode === k} onclick={() => resMode = k} role="button" tabindex="0">{label}</span>{/each}
        <span class="muted">res {res} · {num(covered)} cells with buys</span></div>
      <div class="legend" style="display:block">
        <div style="height:10px;border-radius:5px;background:linear-gradient(90deg, rgb(255,240,230), rgb(228,128,138), rgb(200,16,46))"></div>
        <div class="row" style="font-size:11.5px"><span>0</span><span style="margin-left:auto">{fmt(scale.max)}+</span></div>
      </div>
    </header>
    <section>
      {#if hover}
        <div class="card"><b>{METRICS[metric][0]}: {fmt(valueOf(hover))}</b>
          <div class="muted small">{num(hover[4])} people · {hover[5]} station{hover[5] === 1 ? '' : 's'} with political buys</div>
          <div class="muted small">booked {usd(hover[1])} · invoiced {usd(hover[2])} · {num(hover[3])} spots aired</div></div>
      {:else}<div class="muted small">Hover a cell for its numbers.</div>{/if}
      {#if loc.p}
        <h2>{loc.label}</h2>
        <div class="muted small">{loc.found.length} stations reach this spot. <a href="/">See them →</a></div>
      {/if}
      <p class="muted small" style="margin-top:14px">Fine cells (H3 res 7, ~5 km²) exist only inside crawled stations' coverage; coarse cells (res 5, ~250 km²) are national. Money is spread by population, so $/person is flat inside one station's footprint and changes where coverage overlaps.</p>
    </section>
  </aside>
  <div class="mapwrap"><MapView onready={a => { api = a; a.onZoom(z => zoom = z); }} onclick={p => setLocation(p)} /></div>
</div>

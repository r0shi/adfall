<script>
  import MapView from '$lib/Map.svelte';
  import Search from '$lib/Search.svelte';
  import StationCard from '$lib/StationCard.svelte';
  import { loc, setLocation } from '$lib/location.svelte.js';
  import { spendIndex, usd, CATS, build } from '$lib/data.js';
  import { toGeoJSON } from '$lib/geo.js';
  let api = $state(null), idx = $state({ stations: {}, year: new Date().getFullYear() }), onlyStream = $state(false), meta = $state({});
  spendIndex().then(d => idx = d); build().then(b => meta = b);
  const shown = $derived(onlyStream ? loc.found.filter(s => s.newson) : loc.found);
  const covered = $derived(loc.found.filter(s => idx.stations[s.fac]?.total));
  const rollup = $derived.by(() => {
    const by = {}; let total = 0;
    for (const s of covered) { const sp = idx.stations[s.fac]; total += sp.total; for (const [c, v] of Object.entries(sp.by_category)) by[c] = (by[c] || 0) + v; }
    return { total, by };
  });
  $effect(() => { if (api && loc.p) { api.setContours(toGeoJSON(loc.found)); api.setMarker(loc.p); if (api.map.getZoom() < 6.5) api.flyTo(loc.p, 7); } });
</script>
<svelte:head><title>Stations · TV Wormhole</title></svelte:head>
<div class="shell">
  <aside class="panel">
    <header>
      <h1>Which stations reach here?</h1>
      <p class="tag">Pick a spot. See the local TV stations that cover it, watch their newscasts, and follow the political money each one is taking.</p>
      <Search />
    </header>
    {#if loc.p}
      <section>
        <b>{loc.label}</b>
        <div class="muted small">{loc.found.length} station{loc.found.length === 1 ? '' : 's'} predicted to reach {loc.p[0].toFixed(3)}, {loc.p[1].toFixed(3)} · {loc.found.filter(s => s.newson).length} with a live stream</div>
        {#if covered.length}
          <div class="rollup"><b>{usd(rollup.total)}</b> in {idx.year} political TV buys filed by {covered.length} of these stations
            <div class="catbar">{#each Object.entries(rollup.by).sort((a, b) => b[1] - a[1]) as [c, v]}<i style="width:{(100 * v / rollup.total).toFixed(1)}%;background:{CATS[c] || CATS.Other}" title="{c}: {usd(v)}"></i>{/each}</div></div>
        {/if}
        <label class="small muted" style="display:block;margin:10px 0"><input type="checkbox" bind:checked={onlyStream} /> Only stations with a live stream</label>
        {#each shown as s (s.fac)}
          <StationCard {s} p={loc.p} spend={idx.stations[s.fac] ? { ...idx.stations[s.fac] } : (Object.keys(idx.stations).length ? null : null)} year={idx.year}
            onhover={fac => api?.highlight(fac)} onzoom={st => api?.fitBounds(st.bbox)} />
        {/each}
      </section>
    {/if}
    <footer class="muted" style="padding:10px 18px;font-size:12px;border-top:1px solid var(--line);margin-top:auto">
      {loc.all.length ? `${loc.all.length} licensed stations` : 'Loading stations…'}{meta.date ? ` · data build ${meta.date}` : ''} · Contours: FCC. Streams: NewsON. Money: FCC public political files. <a href="/about">About the data</a>. This product uses the FCC Data API but is not endorsed or certified by the FCC.
    </footer>
  </aside>
  <div class="mapwrap"><MapView onready={a => api = a} onclick={p => setLocation(p)} /></div>
</div>

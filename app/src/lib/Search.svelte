<script>
  import { geocode } from './geo.js';
  import { setLocation } from './location.svelte.js';
  let { after = null } = $props();                          // an extra control at the end of the row (the map's layer button on phones)
  let q = $state(''), hint = $state('…or click anywhere on the map.'), err = $state(false);
  async function go(e) {
    e.preventDefault(); if (!q.trim()) return;
    hint = 'Looking up…'; err = false;
    try { const g = await geocode(q.trim()); await setLocation(g.p, g.label); hint = '…or click anywhere on the map.'; }
    catch { hint = `Couldn't find "${q}".`; err = true; }
  }
  function locate() {
    if (!navigator.geolocation) { hint = 'Geolocation unavailable.'; err = true; return; }
    navigator.geolocation.getCurrentPosition(pos => setLocation([pos.coords.latitude, pos.coords.longitude]), () => { hint = 'Location permission denied.'; err = true; });
  }
</script>
<form class="search" onsubmit={go}>
  <input type="search" bind:value={q} placeholder="Address, ZIP, city, or lat, lon" autocomplete="off" />
  <button type="submit" class="go">Go</button>
  <button type="button" class="ghost" onclick={locate} title="Use my location" aria-label="Use my location">⌖</button>
  {#if after}{@render after()}{/if}
</form>
<p class="small muted hint" class:err style="margin:4px 0 0" style:color={err ? 'var(--accent)' : ''}>{hint}</p>
<style>
  /* phones: Enter searches, and the hint only shows when something went wrong */
  @media (max-width: 800px) { .go { display: none; } .hint:not(.err) { display: none; } }
</style>

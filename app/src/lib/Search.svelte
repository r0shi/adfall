<script>
  import { geocode } from './geo.js';
  import { setLocation } from './location.svelte.js';
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
  <button type="submit">Go</button>
  <button type="button" class="ghost" onclick={locate} title="Use my location">⌖</button>
</form>
<p class="small muted" style="margin:4px 0 0" style:color={err ? 'var(--accent)' : ''}>{hint}</p>

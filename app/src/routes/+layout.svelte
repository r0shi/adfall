<script>
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loc, fromHash } from '$lib/location.svelte.js';
  let { children } = $props();
  onMount(fromHash);
  const tabs = [['/', 'Stations'], ['/map', 'Map'], ['/buyers', 'Buyers'], ['/ads', 'Ads'], ['/time', 'Over time']];
  const hash = $derived(loc.p ? `#${loc.p[0].toFixed(4)},${loc.p[1].toFixed(4)}` : '');
</script>
<nav class="top">
  <span class="brand">TV Wormhole</span>
  {#each tabs as [href, label]}<a href={href + hash} class:active={href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href)}>{label}</a>{/each}
  <span class="loc">{loc.p ? `${loc.label} · ${loc.found.length} stations` : 'Pick a place'}</span>
</nav>
{@render children()}

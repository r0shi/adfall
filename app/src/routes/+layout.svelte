<script>
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loc, fromHash } from '$lib/location.svelte.js';
  import SearchAll from '$lib/SearchAll.svelte';
  import { view, setColorBy, loadParties, PARTY_NOTE } from '$lib/color.svelte.js';
  let { children } = $props();
  onMount(() => { fromHash(); loadParties(); });
  const tabs = [['/', 'Map'], ['/buyers', 'Buyers'], ['/ads', 'Ads'], ['/explore', 'Explore'], ['/about', 'About']];
  const hash = $derived(loc.p ? `#${loc.p[0].toFixed(4)},${loc.p[1].toFixed(4)}` : '');
</script>
<nav class="top">
  <span class="brand">Adfall</span>
  {#each tabs as [href, label]}<a href={href + hash} class:active={href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href)}>{label}</a>{/each}
  <span class="colorby" title="What the colors on buyers, tiles and bars mean">Color by
    <span class="chip" class:on={view.by === 'category'} onclick={() => setColorBy('category')} onkeydown={e => e.key === 'Enter' && setColorBy('category')} role="button" tabindex="0">Office level</span>
    <span class="chip" class:on={view.by === 'party'} onclick={() => setColorBy('party')} onkeydown={e => e.key === 'Enter' && setColorBy('party')} role="button" tabindex="0" title={PARTY_NOTE}>Party</span></span>
  <span class="loc">{loc.p ? `${loc.label} · ${loc.found.length} stations` : ''}</span>
  <SearchAll />
</nav>
{@render children()}

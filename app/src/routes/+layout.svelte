<script>
  import '../app.css';
  import { page } from '$app/state';
  import { onMount, untrack } from 'svelte';
  import { pushState, replaceState, afterNavigate } from '$app/navigation';
  import { loc } from '$lib/location.svelte.js';
  import { ui, serialize, apply, historyMode } from '$lib/url.svelte.js';
  import SearchAll from '$lib/SearchAll.svelte';
  import { view, setColorBy, loadParties, PARTY_NOTE } from '$lib/color.svelte.js';
  let { children } = $props();
  // URL -> state on load, Back/Forward (popstate), hash links and in-app navigation; state -> URL on every change.
  // SvelteKit's page.url does not always follow a popstate between shallow entries, so the window events are the source.
  let last = null, applying = false;
  function sync() {
    const h = location.hash;
    if (h === last) return;
    last = h; applying = true;
    apply(h).finally(() => { applying = false; last = '#' + serialize(); });
  }
  onMount(() => {
    loadParties(); sync();
    addEventListener('popstate', sync); addEventListener('hashchange', sync);
    return () => { removeEventListener('popstate', sync); removeEventListener('hashchange', sync); };
  });
  afterNavigate(() => sync());
  $effect(() => { ui.path = page.url.pathname; });
  $effect(() => {
    const h = '#' + serialize();
    if (applying || h === last) return;
    const mode = historyMode(last, h); last = h;
    untrack(() => { try { (mode === 'push' ? pushState : replaceState)(h, {}); } catch { /* before the router is ready */ } });
  });
  const tabs = [['/', 'Map'], ['/buyers', 'Buyers'], ['/ads', 'Ads'], ['/explore', 'Explore'], ['/about', 'About']];
  const hash = $derived((loc.p || view.by !== 'category') ? '#' + serialize({ shared: true }) : '');
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

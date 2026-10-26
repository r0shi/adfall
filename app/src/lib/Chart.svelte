<script>
  // Observable Plot wrapper: `make(Plot, width)` returns a plot element; re-renders on resize.
  import { onMount } from 'svelte';
  import * as Plot from '@observablehq/plot';
  let { make, height = 220, key = null } = $props();   // key: any value whose change should redraw (e.g. the color-by mode)
  let el, width = $state(400);
  onMount(() => {
    const ro = new ResizeObserver(([e]) => { width = Math.max(240, e.contentRect.width); });
    ro.observe(el); return () => ro.disconnect();
  });
  $effect(() => {
    if (!el) return;
    void key;
    el.replaceChildren();
    try { const node = make(Plot, width, height); if (node) el.appendChild(node); } catch (e) { console.error(e); }
  });
</script>
<figure class="plot" bind:this={el}></figure>

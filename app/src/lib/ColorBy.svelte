<script>
  // The "Color by: Office level | Party" switch (color.svelte.js), placed next to the marks it recolors: the pin popover's
  // share bar, and the legends on the Buyers, Ads and station pages. The choice is global and remembered per browser.
  import { view, setColorBy, PARTY_NOTE } from './color.svelte.js';
  let { label = 'Color by' } = $props();
  const OPTS = [['category', 'Office level', 'What the colors on buyers, tiles and bars mean: federal, state, local, issue'], ['party', 'Party', PARTY_NOTE]];
</script>
<span class="colorby">
  {#if label}<span class="lbl">{label}</span>{/if}
  <span class="seg" role="radiogroup" aria-label="Color buyers by">
    {#each OPTS as [k, l, t]}<button role="radio" aria-checked={view.by === k} class:on={view.by === k} onclick={() => setColorBy(k)} title={t}>{l}</button>{/each}
  </span>
</span>
<style>
  .colorby { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--muted); white-space: nowrap; flex: none; }
  .seg { display: inline-flex; padding: 2px; gap: 2px; border-radius: 8px; background: var(--chip); border: 1px solid var(--line); }
  .seg button { padding: 2px 8px; font-size: 11.5px; font-weight: 500; color: var(--muted); background: transparent; border-radius: 6px; }
  .seg button:hover { color: var(--fg); }
  .seg button.on { background: var(--bg); color: var(--fg); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 0.18); }
</style>

<script>
  // The "Color by: Party | Office level" switch (party is the default) (color.svelte.js), placed next to the marks it recolors: the pin popover's
  // share bar, and the legends on the Buyers, Ads and station pages. The choice is global and remembered per browser.
  // One pill: the label is its first (inert) segment, so it reads as a single control.
  import { view, setColorBy, PARTY_NOTE } from './color.svelte.js';
  let { label = 'Color by:' } = $props();
  const OPTS = [['party', 'Party', PARTY_NOTE], ['category', 'Office level', 'What the colors on buyers, tiles and bars mean: federal, state, local, issue']];
</script>
<span class="colorby" role="radiogroup" aria-label={label.replace(/:$/, '')}>
  {#if label}<span class="lbl" aria-hidden="true">{label}</span>{/if}
  {#each OPTS as [k, l, t]}<button role="radio" aria-checked={view.by === k} class:on={view.by === k} onclick={() => setColorBy(k)} title={t}>{l}</button>{/each}
</span>
<style>
  .colorby { display: inline-flex; align-items: center; gap: 2px; padding: 2px; flex: none; white-space: nowrap;
    border-radius: 8px; background: var(--chip); border: 1px solid var(--line); font-size: 11.5px; }
  .lbl { padding: 2px 6px 2px 6px; margin-right: 2px; color: var(--muted); border-right: 1px solid var(--line); }
  button { padding: 2px 8px; font-size: 11.5px; font-weight: 500; color: var(--muted); background: transparent; border-radius: 6px; }
  button:hover { color: var(--fg); }
  button.on { background: var(--bg); color: var(--fg); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 0.18); }
</style>

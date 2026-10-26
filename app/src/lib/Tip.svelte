<script>
  // The tooltip surface for the `tip` action. Follows the pointer, flips to stay inside the window, never grabs the pointer.
  import { tipState } from './tip.svelte.js';
  let el, w = $state(0), h = $state(0);
  $effect(() => { if (tipState.on && el) { w = el.offsetWidth; h = el.offsetHeight; } });
  const pos = $derived.by(() => {
    const W = typeof window !== 'undefined' ? window.innerWidth : 1000, H = typeof window !== 'undefined' ? window.innerHeight : 800;
    let x = tipState.x + 14, y = tipState.y + 16;
    if (x + w > W - 8) x = Math.max(8, tipState.x - w - 10);
    if (y + h > H - 8) y = Math.max(8, tipState.y - h - 10);
    return { x, y };
  });
</script>
{#if tipState.on && tipState.text}
  <div class="tip" bind:this={el} style="left:{pos.x}px;top:{pos.y}px">{#if tipState.html}{@html tipState.text}{:else}{tipState.text}{/if}</div>
{/if}
<style>
  .tip { position: fixed; z-index: 60; pointer-events: none; max-width: 300px; padding: 6px 9px; font-size: 12.5px; line-height: 1.35; white-space: pre-line;
    color: var(--fg); background: color-mix(in srgb, var(--bg) 94%, transparent); backdrop-filter: blur(8px); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,.18); }
  .tip :global(b) { font-weight: 700; }
</style>

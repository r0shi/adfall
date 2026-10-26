<script>
  // Legend for whatever buyer marks are colored by right now (category or party), plus any trailing note.
  import { legendEntries, view, PARTY_NOTE } from './color.svelte.js';
  let { other = false, mode = null, children = null } = $props();
</script>
<div class="legend">
  {#each legendEntries({ other, mode }) as [label, color] (label)}<span><span class="dot" style="background:{color}"></span>{label}</span>{/each}
  {#if (mode || view.by) === 'party'}<span class="muted" title={PARTY_NOTE}>· by party ⓘ</span>{/if}
  {#if children}{@render children()}{/if}
</div>

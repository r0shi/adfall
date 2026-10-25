<script>
  import { TIERS, tier } from './video.js';
  let { confidence, source = 'youtube', size = 'small' } = $props();
  const t = $derived(tier(confidence));
</script>
{#if t}
  <span class="vbadge {size}" style="background:{TIERS[t].color}" title="{TIERS[t].title} · {Math.round(confidence * 100)}% · {source}">
    {source === 'override' ? 'verified' : TIERS[t].label}
  </span>
{/if}
<style>
  .vbadge { display: inline-block; color: #fff; font-size: 10px; font-weight: 700; line-height: 1; padding: 3px 6px; border-radius: 999px; letter-spacing: .02em; text-transform: uppercase; }
  .vbadge.small { font-size: 9px; padding: 2px 5px; }
</style>

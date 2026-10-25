<script>
  // Inline player for a matched creative: the platform's own iframe (YouTube, nocookie host); a link-out card when the source cannot embed.
  import Badge from './Badge.svelte';
  import { playUrl } from './video.js';
  let { video, title = '', autoplay = true, onclose = null } = $props();
  const src = $derived(autoplay ? playUrl(video?.embed_url) : video?.embed_url);
</script>
{#if video?.embed_url}
  <div class="player">
    <iframe {src} title={title || 'Ad video'} loading="lazy" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
    <div class="pbar small">
      <Badge confidence={video.confidence} source={video.source} />
      {#if title}<span class="ptitle">{title}</span>{/if}
      <a href={video.video_url} target="_blank" rel="noopener" class="muted" style="margin-left:auto">Open on {video.source === 'youtube' ? 'YouTube' : video.source} ↗</a>
      {#if onclose}<button class="ghost" style="padding:2px 8px;font-size:12px" onclick={onclose}>close</button>{/if}
    </div>
  </div>
{:else if video?.video_url}
  <a class="linkout" href={video.video_url} target="_blank" rel="noopener">
    <Badge confidence={video.confidence} source={video.source} />
    <span>Watch on {video.source === 'google-ads' ? "Google's Ads Transparency Center" : video.source === 'ispot' ? 'iSpot.tv' : video.source} ↗</span>
    <span class="muted small">This source does not allow embedding; it opens in a new tab.</span>
  </a>
{/if}
<style>
  .player { border-radius: 10px; overflow: hidden; border: 1px solid var(--line); background: #000; }
  .player iframe { display: block; width: 100%; aspect-ratio: 16 / 9; border: 0; }
  .pbar { display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: var(--chip); color: var(--fg); }
  .ptitle { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .linkout { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; text-decoration: none; background: var(--chip); }
</style>

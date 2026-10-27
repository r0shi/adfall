<script>
  // Thumbnail wall: one tile per spot family, sized by airings on the stations in scope. Matched spots show the
  // upload's thumbnail and play inline on click (the platform's own player); unmatched spots stay as text tiles.
  import Badge from './Badge.svelte';
  import Player from './Player.svelte';
  import { families } from './video.js';
  import { CATS, num } from '../data.js';
  import { colorOf } from '../color.svelte.js';
  import { tip } from '../tip.svelte.js';
  let { list, limit = 48, min = 84, max = 156 } = $props();
  const fams = $derived(families(list).slice(0, limit));
  const maxA = $derived(fams[0]?.airings || 1);
  const matched = $derived(fams.filter(f => f.video?.embed_url).length);
  const linked = $derived(fams.filter(f => f.video && !f.video.embed_url).length);
  const width = (a) => Math.round(min + (max - min) * Math.sqrt(a / maxA));
  let playing = $state(null);
</script>
<div class="muted small" style="margin-bottom:6px">{matched} of {fams.length} spots play here{linked ? `, ${linked} more link to a Google ad that started the same week` : ''}{matched + linked < fams.length ? '; the rest are invoice codes with no public video yet' : ''}. Click a tile to play.</div>
<div class="wall">
  {#each fams as f (f.key)}
    {#if playing === f.key && f.video}
      <div class="tile open">
        <Player video={f.video} title="{f.buyer || f.key} · {num(f.airings)} airings" onclose={() => playing = null} />
        <div class="cap small"><a href="/ads/{f.ad_id}" style="font-family:ui-monospace,monospace;text-decoration:none">{f.key}</a><span class="muted">{f.buyer || 'unknown buyer'}</span></div>
      </div>
    {:else if f.video && !f.video.embed_url}
      <a class="tile text linkout" href={f.video.video_url} target="_blank" rel="noopener" style="width:{width(f.airings)}px;--cat:{CATS[f.category] || CATS.Other}" title="{f.buyer || f.key} · {num(f.airings)} airings · a Google video ad that started the same week; opens Google's Ads Transparency Center">
        <span class="tag"><Badge confidence={f.video.confidence} source={f.video.source} /></span>
        <span class="code">{f.key}</span>
        <span class="go small">Google ad ↗</span>
        <span class="label"><b>{f.buyer || 'unknown buyer'}</b><span>{num(f.airings)}</span></span>
      </a>
    {:else if f.video}
      <button class="tile thumb" style="width:{width(f.airings)}px;--cat:{colorOf(f)}" onclick={() => playing = f.key} use:tip={`${f.buyer || f.key}\n${num(f.airings)} airings · ${f.first} → ${f.last}`}>
        <img src={f.video.thumb_url} alt="" loading="lazy" />
        <span class="play">▶</span>
        <span class="tag"><Badge confidence={f.video.confidence} source={f.video.source} /></span>
        <span class="label"><b>{f.buyer || f.key}</b><span>{num(f.airings)}</span></span>
      </button>
    {:else}
      <a class="tile text" href="/ads/{f.ad_id}" style="width:{width(f.airings)}px;--cat:{colorOf(f)}" use:tip={`${f.buyer || 'unknown buyer'}\n${num(f.airings)} airings · no video match yet`}>
        <span class="code">{f.key}</span>
        <span class="label"><b>{f.buyer || 'unknown buyer'}</b><span>{num(f.airings)}</span></span>
      </a>
    {/if}
  {/each}
</div>
<style>
  .wall { display: flex; flex-wrap: wrap; gap: 6px; align-items: flex-start; }
  .tile { position: relative; display: block; border-radius: 8px; overflow: hidden; border: 1px solid var(--line); border-left: 3px solid var(--cat); background: var(--chip); color: var(--fg); padding: 0; text-decoration: none; cursor: pointer; font: inherit; text-align: left; }
  .tile.thumb { aspect-ratio: 16 / 9; }
  .tile.thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .tile.thumb:hover img { filter: brightness(1.08); }
  .play { position: absolute; left: 50%; top: 45%; transform: translate(-50%, -50%); width: 28px; height: 28px; border-radius: 50%; background: rgba(0,0,0,.55); color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; opacity: .85; }
  .tile.thumb:hover .play { opacity: 1; background: var(--accent); }
  .tag { position: absolute; left: 6px; top: 5px; }
  .label { position: absolute; left: 0; right: 0; bottom: 0; display: flex; justify-content: space-between; gap: 6px; padding: 14px 6px 4px; font-size: 11px; line-height: 1.1; color: #fff; background: linear-gradient(transparent, rgba(0,0,0,.75)); }
  .label b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .label span { font-variant-numeric: tabular-nums; flex: none; }
  .tile.text { aspect-ratio: 16 / 9; display: flex; flex-direction: column; justify-content: center; align-items: center; }
  .tile.text .code { font-family: ui-monospace, monospace; font-weight: 700; font-size: 11px; opacity: .8; padding: 0 6px; word-break: break-all; text-align: center; }
  .tile.text .label { color: var(--fg); background: none; padding: 4px 6px; }
  .tile.linkout { border-style: dashed; border-left-style: solid; }
  .tile.linkout .go { font-size: 10.5px; color: var(--accent); margin-top: 2px; }
  .tile.open { width: 100%; cursor: default; border-left-width: 1px; background: none; border: 0; }
  .cap { display: flex; gap: 8px; padding: 4px 2px 0; }
</style>

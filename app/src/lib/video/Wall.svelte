<script>
  // Thumbnail wall: one tile per spot family, sized by airings on the stations in scope. Clicking a tile opens that spot
  // in the whole panel (the platform's own player when it embeds, otherwise a summary card in the player's place), with a
  // back button that returns to the wall at the same scroll position. `open` is bindable so the tab can hide its own controls.
  import { tick } from 'svelte';
  import Badge from './Badge.svelte';
  import Player from './Player.svelte';
  import { families } from './video.js';
  import { num, catShort, slugOf } from '../data.js';
  import { colorOf } from '../color.svelte.js';
  import { tip } from '../tip.svelte.js';
  let { list, limit = 48, min = 84, max = 156, open = $bindable(null) } = $props();
  const fams = $derived(families(list).slice(0, limit));
  const maxA = $derived(fams[0]?.airings || 1);
  const total = $derived(list.reduce((t, c) => t + c.airings, 0));
  const matched = $derived(fams.filter(f => f.video?.embed_url).length);
  const linked = $derived(fams.filter(f => f.video && !f.video.embed_url).length);
  const width = (a) => Math.round(min + (max - min) * Math.sqrt(a / maxA));
  const cur = $derived(open ? fams.find(f => f.key === open) : null);
  let root, back, scroller = null, saved = 0;
  // the panel that scrolls (the popover body, or the page); its position is what "back" restores
  const scrollParent = (n) => { for (let p = n?.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowY; if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight) return p; } return document.scrollingElement; };
  async function show(f) { scroller = scrollParent(root); saved = scroller?.scrollTop || 0; open = f.key; await tick(); if (scroller) scroller.scrollTop = 0; back?.focus({ preventScroll: true }); }
  async function close() { const key = open; open = null; await tick(); if (scroller) scroller.scrollTop = saved; root?.querySelector(`[data-key="${CSS.escape(key)}"]`)?.focus({ preventScroll: true }); }
  const range = (f) => f.first === f.last ? f.first : `${f.first} → ${f.last}`;
  const sourceName = (s) => s === 'google-ads' ? "Google's Ads Transparency Center" : s === 'youtube' ? 'YouTube' : s === 'ispot' ? 'iSpot.tv' : s;
</script>
<svelte:window onkeydown={e => { if (cur && e.key === 'Escape') { e.preventDefault(); close(); } }} />
<div bind:this={root}>
{#if cur}
  {@const f = cur}
  <div class="detail">
    <div class="dbar">
      <button class="ghost dback" bind:this={back} onclick={close} title="Back to the ads (Esc)"><span aria-hidden="true">←</span> All ads</button>
      <span class="dcount muted small">{fams.indexOf(f) + 1} of {fams.length}</span>
      <button class="ghost dx" onclick={close} title="Close (Esc)" aria-label="Close and go back to the ads">×</button>
    </div>
    {#snippet facts(f)}
      <div class="dname"><span class="dot" style="background:{colorOf(f)}"></span><b>{f.buyer || 'Unknown buyer'}</b></div>
      <div class="dmeta"><span class="code">{f.key}</span><span class="muted">· {catShort(f.category)}</span></div>
      <dl>
        <div><dt>Airings here</dt><dd>{num(f.airings)} <span class="muted">({(100 * f.airings / Math.max(1, total)).toFixed(1)}%)</span></dd></div>
        <div><dt>Aired</dt><dd>{range(f)}</dd></div>
        {#if f.ids.length > 1}<div><dt>Ad-ID variants</dt><dd>{f.ids.length}</dd></div>{/if}
      </dl>
      <div class="links">
        <a href="/ads/{f.ad_id}" target="_blank" rel="noopener" class="live">Open the ad's page ↗</a>
        {#if f.buyer}<a href="/buyers/{slugOf(f.category, f.buyer)}" target="_blank" rel="noopener">Buyer page ↗</a>{/if}
        {#if f.video?.video_url && !f.video.embed_url}<a href={f.video.video_url} target="_blank" rel="noopener">Watch on {sourceName(f.video.source)} ↗</a>{/if}
      </div>
    {/snippet}
    {#if f.video?.embed_url}
      <Player video={f.video} title="{f.buyer || f.key} · {f.key}" showTitle={false} />
      <div class="dfacts">{@render facts(f)}</div>
    {:else}
      <div class="dcard" style="--cat:{colorOf(f)}">
        <div class="dnote small">
          {#if f.video}<Badge confidence={f.video.confidence} source={f.video.source} /> A Google video ad that started the same week; it plays on Google's page, not here.
          {:else}No public video matched to this spot yet.{/if}
        </div>
        {@render facts(f)}
      </div>
    {/if}
  </div>
{:else}
  <div class="muted small" style="margin-bottom:6px">{matched} of {fams.length} spots play here{linked ? `, ${linked} more link to a Google ad that started the same week` : ''}{matched + linked < fams.length ? '; the rest are invoice codes with no public video yet' : ''}. Click a tile to open it.</div>
  <div class="wall">
    {#each fams as f (f.key)}
      {#if f.video?.embed_url}
        <button class="tile thumb" data-key={f.key} style="width:{width(f.airings)}px;--cat:{colorOf(f)}" onclick={() => show(f)} use:tip={`${f.buyer || f.key}\n${num(f.airings)} airings · ${f.first} → ${f.last}`}>
          <img src={f.video.thumb_url} alt="" loading="lazy" />
          <span class="play">▶</span>
          <span class="tag"><Badge confidence={f.video.confidence} source={f.video.source} /></span>
          <span class="label"><b>{f.buyer || f.key}</b><span>{num(f.airings)}</span></span>
        </button>
      {:else}
        <button class="tile text" class:linkout={!!f.video} data-key={f.key} style="width:{width(f.airings)}px;--cat:{colorOf(f)}" onclick={() => show(f)} use:tip={`${f.buyer || 'unknown buyer'}\n${num(f.airings)} airings · ${f.video ? 'a Google video ad that started the same week' : 'no video match yet'}`}>
          {#if f.video}<span class="tag"><Badge confidence={f.video.confidence} source={f.video.source} /></span>{/if}
          <span class="code">{f.key}</span>
          {#if f.video}<span class="go small">Google ad</span>{/if}
          <span class="label"><b>{f.buyer || 'unknown buyer'}</b><span>{num(f.airings)}</span></span>
        </button>
      {/if}
    {/each}
  </div>
{/if}
</div>
<style>
  .wall { display: flex; flex-wrap: wrap; gap: 6px; align-items: flex-start; }
  .tile { position: relative; display: block; border-radius: 8px; overflow: hidden; border: 1px solid var(--line); border-left: 3px solid var(--cat); background: var(--chip); color: var(--fg); padding: 0; text-decoration: none; cursor: pointer; font: inherit; font-weight: 400; text-align: left; }
  .tile.thumb { aspect-ratio: 16 / 9; }
  .tile.thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .tile.thumb:hover img { filter: brightness(1.08); }
  .tile:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .play { position: absolute; left: 50%; top: 45%; transform: translate(-50%, -50%); width: 28px; height: 28px; border-radius: 50%; background: rgba(0,0,0,.55); color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; opacity: .85; }
  .tile.thumb:hover .play { opacity: 1; background: var(--accent); }
  .tag { position: absolute; left: 6px; top: 5px; }
  .label { position: absolute; left: 0; right: 0; bottom: 0; display: flex; justify-content: space-between; gap: 6px; padding: 14px 6px 4px; font-size: 11px; line-height: 1.1; color: #fff; background: linear-gradient(transparent, rgba(0,0,0,.75)); }
  .label b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .label span { font-variant-numeric: tabular-nums; flex: none; }
  .tile.text { aspect-ratio: 16 / 9; display: flex; flex-direction: column; justify-content: center; align-items: center; }
  .tile.text:hover { border-color: var(--accent); border-left-color: var(--cat); }
  .tile.text .code { font-family: ui-monospace, monospace; font-weight: 700; font-size: 11px; opacity: .8; padding: 0 6px; word-break: break-all; text-align: center; }
  .tile.text .label { color: var(--fg); background: none; padding: 4px 6px; }
  .tile.linkout { border-style: dashed; border-left-style: solid; }
  .tile.linkout .go { font-size: 10.5px; color: var(--accent); margin-top: 2px; }
  .dbar { display: flex; align-items: center; gap: 8px; margin: -2px 0 10px; }
  .dback { padding: 5px 12px 5px 10px; font-size: 13px; }
  .dback span { margin-right: 2px; }
  .dcount { margin-left: auto; font-variant-numeric: tabular-nums; }
  .dx { width: 30px; height: 30px; padding: 0; font-size: 17px; line-height: 1; }
  .dfacts { padding: 10px 2px 0; }
  .dcard { aspect-ratio: 16 / 9; display: flex; flex-direction: column; justify-content: center; padding: 14px 16px; border-radius: 10px;
    border: 1px solid var(--line); border-left: 4px solid var(--cat); background: var(--chip); }
  .dnote { color: var(--muted); margin-bottom: 8px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .dname { display: flex; align-items: center; gap: 2px; font-size: 16px; line-height: 1.25; }
  .dmeta { display: flex; gap: 6px; font-size: 12.5px; margin-top: 2px; }
  .code { font-family: ui-monospace, monospace; font-weight: 700; }
  dl { display: flex; flex-wrap: wrap; gap: 4px 18px; margin: 10px 0 0; }
  dl div { display: flex; flex-direction: column; }
  dt { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  dd { margin: 0; font-size: 13.5px; font-weight: 600; font-variant-numeric: tabular-nums; }
  dd .muted { font-weight: 400; }
  .links { margin-top: 12px; }
  @media (max-width: 480px) { .dcard { aspect-ratio: auto; min-height: 180px; } }
</style>

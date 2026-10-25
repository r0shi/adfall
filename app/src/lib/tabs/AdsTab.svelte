<script>
  import { creativesHere } from '../here.js';
  import { num, CATS, catShort, slugOf } from '../data.js';
  let { found } = $props();
  let list = $state.raw([]), mode = $state('cloud'), loading = $state(true);
  $effect(() => { loading = true; const f = found; creativesHere(f).then(c => { list = c; loading = false; }); });
  const byBuyer = $derived.by(() => {
    const m = new Map();
    for (const c of list) { const k = c.buyer || `(${c.prefix}…)`; const e = m.get(k) || { buyer: k, category: c.category, airings: 0, creatives: 0, slug: c.buyer ? slugOf(c.category, c.buyer) : null, top: c.ad_id }; e.airings += c.airings; e.creatives += 1; m.set(k, e); }
    return [...m.values()].sort((a, b) => b.airings - a.airings);
  });
  const maxB = $derived(byBuyer[0]?.airings || 1), maxA = $derived(list[0]?.airings || 1);
  const size = (a, mx) => 11 + 24 * Math.sqrt(a / mx);
</script>
<div class="chips" style="margin:0 0 8px">
  <span class="chip" class:on={mode === 'cloud'} onclick={() => mode = 'cloud'} role="button" tabindex="0">Buyers</span>
  <span class="chip" class:on={mode === 'list'} onclick={() => mode = 'list'} role="button" tabindex="0">Creatives</span>
  <span class="muted small" style="align-self:center">{num(list.length)} creatives · {num(list.reduce((t, c) => t + c.airings, 0))} airings</span>
</div>
{#if loading}<div class="muted small">Loading…</div>
{:else if mode === 'cloud'}
  <div class="cloud">{#each byBuyer.slice(0, 80) as b (b.buyer)}<a href={b.slug ? `/buyers/${b.slug}` : `/ads/${b.top}`} style="font-size:{size(b.airings, maxB).toFixed(0)}px;color:{CATS[b.category] || CATS.Other};text-decoration:none" title="{b.buyer} · {num(b.airings)} airings · {b.creatives} creatives">{b.buyer}</a>{/each}</div>
{:else}
  {#each list.slice(0, 60) as c (c.ad_id)}
    <div style="padding:4px 0;border-bottom:1px solid var(--line)">
      <div class="row small"><span class="dot" style="background:{CATS[c.category] || CATS.Other}"></span><a href="/ads/{c.ad_id}" style="font-family:ui-monospace,monospace;font-weight:700;text-decoration:none">{c.ad_id}</a><span class="muted">{c.buyer || 'unknown'}</span><span class="amt">{num(c.airings)}</span></div>
      <div class="bar"><i style="width:{(100 * c.airings / maxA).toFixed(1)}%;background:{CATS[c.category] || CATS.Other}"></i></div>
    </div>
  {/each}
{/if}

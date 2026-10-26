<script>
  import { creativesHere } from '../here.js';
  import { num, CATS, catShort, slugOf } from '../data.js';
  import { colorOf } from '../color.svelte.js';
  let { found, idx = null } = $props();
  import Coverage from '../Coverage.svelte';
  import Heatmap from '../Heatmap.svelte';
  import { stationDetail } from '../data.js';
  import Wall from '../video/Wall.svelte';                    // video chain (ingest.video): thumbnail wall mode
  let list = $state.raw([]), mode = $state('wall'), loading = $state(true), grid = $state.raw(null);
  $effect(() => { loading = true; const f = found; creativesHere(f).then(c => { list = c; loading = false; }).catch(() => { list = []; loading = false; }); });
  $effect(() => {
    const facs = idx ? found.filter(s => idx.stations[s.fac]) : found;
    Promise.all(facs.map(s => stationDetail(s.fac).catch(() => null))).then(ds => {
      const g = Array.from({ length: 7 }, () => new Array(24).fill(0)); let any = false;
      for (const d of ds) if (d?.daypart) { any = true; for (let i = 0; i < 7; i++) for (let h = 0; h < 24; h++) g[i][h] += d.daypart[i][h]; }
      grid = any ? g : null;
    });
  });
  const byBuyer = $derived.by(() => {
    const m = new Map();
    for (const c of list) { const k = c.buyer || `(${c.prefix}…)`; const e = m.get(k) || { buyer: k, category: c.category, airings: 0, creatives: 0, slug: c.buyer ? slugOf(c.category, c.buyer) : null, top: c.ad_id }; e.airings += c.airings; e.creatives += 1; m.set(k, e); }
    return [...m.values()].sort((a, b) => b.airings - a.airings);
  });
  const maxB = $derived(byBuyer[0]?.airings || 1), maxA = $derived(list[0]?.airings || 1);
  const size = (a, mx) => 11 + 24 * Math.sqrt(a / mx);
</script>
<div class="chips" style="margin:0 0 8px">
  <!-- video chain: thumbnail wall (components under src/lib/video/) -->
  <span class="chip" class:on={mode === 'wall'} onclick={() => mode = 'wall'} role="button" tabindex="0" title="The spots as video, sized by airings here">Wall</span>
  <!-- /video chain -->
  <span class="chip" class:on={mode === 'cloud'} onclick={() => mode = 'cloud'} role="button" tabindex="0">Buyers</span>
  <span class="chip" class:on={mode === 'list'} onclick={() => mode = 'list'} role="button" tabindex="0">Creatives</span>
  <span class="chip" class:on={mode === 'daypart'} onclick={() => mode = 'daypart'} role="button" tabindex="0" title="When the ads ran: hour × weekday">Daypart</span>
  <span class="muted small" style="align-self:center">{num(list.length)} creatives · {num(list.reduce((t, c) => t + c.airings, 0))} airings</span>
</div>
{#if loading}<div class="muted small">Loading…</div>
{:else if !list.length}<Coverage {found} {idx} what="aired ads on record" />
{:else if mode === 'wall'}
  <!-- video chain: thumbnail wall -->
  <Wall {list} />
  <!-- /video chain -->
{:else if mode === 'daypart'}
  <div class="muted small" style="margin-bottom:4px">When political spots aired on these stations (invoiced airings with a known time).</div>
  <Heatmap {grid} />
{:else if mode === 'cloud'}
  <div class="cloud">{#each byBuyer.slice(0, 80) as b (b.buyer)}<a href={b.slug ? `/buyers/${b.slug}` : `/ads/${b.top}`} style="font-size:{size(b.airings, maxB).toFixed(0)}px;color:{colorOf(b)};text-decoration:none" title="{b.buyer} · {num(b.airings)} airings · {b.creatives} creatives">{b.buyer}</a>{/each}</div>
{:else}
  {#each list.slice(0, 60) as c (c.ad_id)}
    <div style="padding:4px 0;border-bottom:1px solid var(--line)">
      <div class="row small"><span class="dot" style="background:{colorOf(c)}"></span><a href="/ads/{c.ad_id}" style="font-family:ui-monospace,monospace;font-weight:700;text-decoration:none">{c.ad_id}</a><span class="muted">{c.buyer || 'unknown'}</span><span class="amt">{num(c.airings)}</span></div>
      <div class="bar"><i style="width:{(100 * c.airings / maxA).toFixed(1)}%;background:{colorOf(c)}"></i></div>
    </div>
  {/each}
{/if}

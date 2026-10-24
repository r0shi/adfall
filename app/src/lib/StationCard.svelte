<script>
  import { usd, CATS, catShort, stationSpend } from './data.js';
  import { miles } from './geo.js';
  let { s, p, spend = null, year, onhover = () => {}, onzoom = () => {} } = $props();
  let open = $state(false), detail = $state(null);
  async function toggle(e) { e.stopPropagation(); open = !open; if (open && !detail) detail = await stationSpend(s.fac); }
  const dist = $derived(p ? Math.round(miles(p, s.tx)) : null);
  const searchUrl = $derived(`https://duckduckgo.com/?q=${encodeURIComponent(`${s.call} ${s.city} ${s.state} live stream news`)}`);
</script>
<div class="card" role="button" tabindex="0" onmouseenter={() => onhover(s.fac)} onmouseleave={() => onhover(null)} onclick={() => onzoom(s)} onkeydown={e => e.key === 'Enter' && onzoom(s)}>
  <div class="row"><b style="font-size:16px">{s.call}</b><span class="muted small">ch {s.vchan && s.vchan !== '-' ? s.vchan : s.rf}</span>
    <span class="muted small" style="margin-left:auto;text-transform:uppercase;letter-spacing:.04em;font-size:11px">{s.svc === 'DCA' ? 'Class A' : 'Full power'}</span></div>
  <div class="muted small">{s.city}, {s.state} · {s.licensee}{dist !== null ? ` · transmitter ${dist} mi away` : ''}</div>
  {#if spend}
    {#if spend.total}
      <div class="small" style="margin-top:8px">
        <div class="row"><b>{usd(spend.total)}</b> political ad buys · {spend.buyers} buyers · {year}
          <span style="margin-left:auto;color:var(--accent);cursor:pointer;font-size:12px" onclick={toggle} role="button" tabindex="0" onkeydown={e => e.key === 'Enter' && toggle(e)}>buyers {open ? '▴' : '▾'}</span></div>
        <div class="catbar">{#each Object.entries(spend.by_category).sort((a, b) => b[1] - a[1]) as [c, v]}<i style="width:{(100 * v / spend.total).toFixed(1)}%;background:{CATS[c] || CATS.Other}" title="{c}: {usd(v)}"></i>{/each}</div>
        {#if open}
          <div style="margin-top:8px;border-top:1px solid var(--line);padding-top:6px" onclick={e => e.stopPropagation()} role="presentation">
            {#if !detail}<span class="muted">Loading…</span>{:else}
              {#each detail.buyers.slice(0, 25) as b}
                <div style="margin:6px 0">
                  <div class="row small"><span class="dot" style="background:{CATS[b.category] || CATS.Other}"></span>{b.name}<span class="amt">{usd(b.gross)}</span></div>
                  <div class="bar"><i style="width:{(100 * b.gross / (detail.buyers[0]?.gross || 1)).toFixed(1)}%;background:{CATS[b.category] || CATS.Other}"></i></div>
                  <div class="muted" style="font-size:11.5px">{b.orders} order{b.orders === 1 ? '' : 's'}{b.invoiced ? ` · ${usd(b.invoiced)} invoiced` : ''}{b.ad_ids ? ` · ${b.ad_ids} creative${b.ad_ids === 1 ? '' : 's'}` : ''}{b.agencies?.length ? ` · via ${b.agencies.slice(0, 2).join(', ')}` : ''}</div>
                </div>
              {/each}
              {#if detail.buyers.length > 25}<div class="muted" style="font-size:11.5px">…and {detail.buyers.length - 25} more</div>{/if}
              <div class="legend">{#each Object.entries(CATS) as [c, col]}<span><span class="dot" style="background:{col}"></span>{catShort(c)}</span>{/each}<span>· {detail.docs} documents, {Math.round(100 * (detail.parse_status?.ok || 0) / detail.docs)}% parsed</span></div>
            {/if}
          </div>
        {/if}
      </div>
    {:else}<div class="muted small" style="margin-top:6px">No political buys filed for {year}</div>{/if}
  {/if}
  <div class="links" onclick={e => e.stopPropagation()} role="presentation">
    {#if s.newson}<a class="live" href="https://www.newson.us/stationDetails/{s.newson.id}" target="_blank" rel="noopener">▶ Watch on NewsON</a>
    {:else}<a href={searchUrl} target="_blank" rel="noopener">Find stream</a>{/if}
    <a href="https://publicfiles.fcc.gov/tv-profile/{s.slug}/political-files" target="_blank" rel="noopener">Political ad buys</a>
    <a href="https://publicfiles.fcc.gov/tv-profile/{s.slug}" target="_blank" rel="noopener">FCC file</a>
  </div>
</div>

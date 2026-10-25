<script>
  import { buyersHere, pivot } from '../here.js';
  import { usd, num, CATS, catShort } from '../data.js';
  let { found, all, idx = null } = $props();
  let buyers = $state.raw([]), by = $state('buyer'), cat = $state('All'), loading = $state(true);
  $effect(() => { loading = true; const f = found; buyersHere(f, all, idx).then(b => { buyers = b; loading = false; }); });
  const filtered = $derived(cat === 'All' ? buyers : buyers.filter(b => b.category === cat));
  const rows = $derived(pivot(filtered, by));
  const total = $derived(filtered.reduce((t, b) => t + b.booked, 0));
  const max = $derived(rows[0]?.booked || 1);
  const PARTY = { Democratic: '#2f6fd6', Republican: '#c8102e', 'Issue groups': 'var(--issue)' };
  const color = (r) => by === 'party' ? (PARTY[r.key] || 'var(--other)') : (CATS[r.category] || CATS.Other);
</script>
<div class="chips" style="margin:0 0 6px"><span class="muted small">By:</span>
  {#each [['buyer', 'Buyer'], ['party', 'Party'], ['category', 'Category'], ['agency', 'Agency']] as [k, l]}<span class="chip" class:on={by === k} onclick={() => by = k} role="button" tabindex="0">{l}</span>{/each}
</div>
<div class="chips" style="margin:0 0 8px">{#each ['All', ...Object.keys(CATS).filter(c => c !== 'Other')] as c}<span class="chip" class:on={cat === c} onclick={() => cat = c} role="button" tabindex="0">{catShort(c)}</span>{/each}</div>
{#if loading}<div class="muted small">Loading…</div>
{:else}
  <div class="muted small" style="margin-bottom:6px"><b>{usd(total)}</b> booked by {filtered.length} buyers on {found.length} stations · {rows.length} {by === 'buyer' ? 'buyers' : by === 'party' ? 'parties' : by === 'agency' ? 'agencies' : 'categories'}</div>
  {#each rows.slice(0, 40) as r (r.key)}
    <div style="margin:5px 0">
      <div class="row small"><span class="dot" style="background:{color(r)}"></span>{#if r.slug}<a href="/buyers/{r.slug}" style="text-decoration:none">{r.key}</a>{:else}<span>{r.key}</span>{/if}
        {#if by !== 'buyer'}<span class="muted">{r.n} buyer{r.n === 1 ? '' : 's'}</span>{/if}<span class="amt">{usd(r.booked)}</span></div>
      <div class="bar" style="position:relative"><i style="width:{(100 * r.booked / max).toFixed(1)}%;background:{color(r)};opacity:.35"></i><i style="position:absolute;left:0;top:0;width:{(100 * Math.min(r.invoiced, r.booked) / max).toFixed(1)}%;background:{color(r)}"></i></div>
    </div>
  {/each}
  {#if rows.length > 40}<div class="muted small">…and {rows.length - 40} more</div>{/if}
  <div class="legend"><span><span class="dot" style="background:var(--accent)"></span>invoiced (aired)</span><span><span class="dot" style="background:var(--accent);opacity:.35"></span>booked</span></div>
{/if}

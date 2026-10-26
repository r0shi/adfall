<script>
  // Newscasts: the political spots in each station's news blocks for one night. Scheduled from order lines
  // (what was bought into "News at 6", with spots per week) until the invoices for that night arrive, then the
  // confirmed airings with their Ad-IDs. Data: web/data/newscasts/<fac>.json (ingest.newscasts).
  import { newscasts, newscastIndex, creatives, CATS, num, slugOf } from '../data.js';
  import Coverage from '../Coverage.svelte';
  import { colorOf } from '../color.svelte.js';
  import { ui } from '../url.svelte.js';
  let { found, idx = null } = $props();
  const iso = (d) => d.toISOString().slice(0, 10);
  const today = iso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
  const shift = (d, n) => { const x = new Date(d + 'T00:00:00Z'); x.setUTCDate(x.getUTCDate() + n); return iso(x); };
  const day = $derived(ui.newsDay || today);
  let files = $state.raw([]), cr = $state.raw(null), loading = $state(true);
  $effect(() => {
    loading = true;
    const f0 = found;
    newscastIndex().then(have => Promise.all([Promise.all(f0.filter(s => have.has(s.fac)).map(s => newscasts(s.fac).catch(() => null))), cr ? Promise.resolve(cr) : creatives().catch(() => [])]))
      .then(([fs, c]) => { files = fs.filter(Boolean); cr = c; loading = false; });
  });
  const wd = $derived((new Date(day + 'T00:00:00Z').getUTCDay() + 6) % 7);   // Mon=0
  const LABELS = ['Morning', 'Midday', 'Evening', 'Late'];
  // creatives by buyer id -> [creative], for the "likely spots" under a scheduled buyer
  // keyed by buyer slug: buyer ids are reassigned on every entity rebuild, slugs are stable across exports
  const byBuyer = $derived.by(() => { const m = new Map(); for (const c of cr || []) { if (!c.buyer) continue; const k = slugOf(c.category, c.buyer); (m.get(k) || m.set(k, []).get(k)).push(c); } return m; });
  const byAd = $derived(new Map((cr || []).map(c => [c.ad_id, c])));
  function eligible(l) {   // nights in the line's week that its day pattern allows
    let n = 0; for (let d = l.start; d <= l.end; d = shift(d, 1)) { const w = (new Date(d + 'T00:00:00Z').getUTCDay() + 6) % 7; if (!l.days || l.days.includes(w)) n++; }
    return n || 1;
  }
  const rows = $derived.by(() => {
    const out = [];
    for (const f of files) {
      const confirmedNight = f.confirmed_through && f.confirmed_through >= day;
      const groups = new Map();   // block index -> buyer id -> entry
      if (confirmedNight) {
        for (const c of f.confirmed) {
          if (c.d !== day) continue;
          const g = groups.get(c.b) || groups.set(c.b, new Map()).get(c.b);
          const e = g.get(c.buyer) || g.set(c.buyer, { buyer: f.buyers[c.buyer], n: 0, aired: [] }).get(c.buyer);
          e.n += 1; e.aired.push({ t: c.t, ad_id: c.ad_id });
        }
      } else {
        for (const l of f.lines) {
          if (l.start > day || l.end < day || (l.days && !l.days.includes(wd))) continue;
          const g = groups.get(l.b) || groups.set(l.b, new Map()).get(l.b);
          const e = g.get(l.buyer) || g.set(l.buyer, { buyer: f.buyers[l.buyer], n: 0, aired: null }).get(l.buyer);
          e.n += l.spots / eligible(l);
        }
      }
      for (const [bi, g] of groups) {
        const b = f.blocks[bi];
        const buyers = [...g.values()].filter(e => e.n >= 0.2).sort((x, y) => y.n - x.n);
        if (buyers.length) out.push({ station: f, block: b, confirmed: confirmedNight, buyers, total: buyers.reduce((t, e) => t + e.n, 0) });
      }
    }
    return out.sort((a, b) => a.block.start - b.block.start || a.station.call.localeCompare(b.station.call));
  });
  const nConfirmed = $derived(new Set(rows.filter(r => r.confirmed).map(r => r.station.fac)).size), nScheduled = $derived(new Set(rows.filter(r => !r.confirmed).map(r => r.station.fac)).size);
  const anyConfirmed = $derived(nConfirmed > 0);
  const latest = $derived(files.reduce((m, f) => f.confirmed_through > m ? f.confirmed_through : m, ''));
  const fmtT = (m) => { const h = Math.floor(m / 60) % 24, mm = m % 60; return `${h % 12 || 12}:${String(mm).padStart(2, '0')}${h < 12 ? 'a' : 'p'}`; };
  const dayLabel = $derived(day === today ? 'Tonight' : day === shift(today, -1) ? 'Last night' : new Date(day + 'T00:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }));
  const likely = (e, fac) => (byBuyer.get(e.buyer?.slug) || []).filter(c => c.facs?.[fac]).sort((a, b) => (b.last || '').localeCompare(a.last || '')).slice(0, 3);
</script>
<div class="chips" style="margin:0 0 8px">
  <span class="chip" class:on={day === today} onclick={() => ui.newsDay = today} role="button" tabindex="0">Tonight</span>
  <span class="chip" class:on={day === shift(today, -1)} onclick={() => ui.newsDay = shift(today, -1)} role="button" tabindex="0">Last night</span>
  <input type="date" value={day} onchange={e => ui.newsDay = e.target.value} max={shift(today, 60)} style="font-size:12.5px;padding:3px 8px" />
  <span class="chip" onclick={() => ui.newsDay = shift(day, -1)} role="button" tabindex="0" title="Previous night">‹</span>
  <span class="chip" onclick={() => ui.newsDay = shift(day, 1)} role="button" tabindex="0" title="Next night">›</span>
</div>
{#if loading}<div class="muted small">Loading…</div>
{:else if !files.length}<Coverage {found} {idx} what="newscast buys on record" />
{:else}
  <div class="muted small" style="margin-bottom:8px">
    <b>{dayLabel}</b> · {#if nConfirmed && nScheduled}{nConfirmed} station{nConfirmed === 1 ? '' : 's'} confirmed from invoices, {nScheduled} still scheduled from order files{:else if nConfirmed}confirmed airings from the stations' invoices; counts are exact{:else}scheduled from the stations' order files; invoices confirming what aired reach the FCC about two to three weeks later{latest ? ` (confirmed through ${latest})` : ''}. A "≈" count is the week's buy spread over its nights{/if}.
  </div>
  {#if !rows.length}<div class="card" style="border-style:dashed"><b>No political spots in the newscasts {dayLabel.toLowerCase()}.</b><div class="muted small" style="margin-top:4px">Nothing booked into news programs on these stations for this night. Try another night.</div></div>{/if}
  {#each LABELS as L}
    {@const rs = rows.filter(r => r.block.label === L)}
    {#if rs.length}
      <h2 style="margin:10px 0 4px">{L} news <span class="muted small" style="font-weight:400">· {num(rs.reduce((t, r) => t + r.total, 0))} spots</span></h2>
      {#each rs as r (r.station.fac + r.block.id)}
        <div class="card" style="padding:8px 10px">
          <div class="row small"><b>{r.station.call}</b><span class="muted">{r.block.time}{r.block.network ? ' · network' : ''} · {r.confirmed ? 'confirmed' : 'scheduled'}</span><span class="amt">{r.confirmed ? num(r.total) : '≈' + num(r.total)} spots</span></div>
          {#each r.buyers as e (e.buyer?.id)}
            <div class="row small" style="margin-top:4px"><span class="dot" style="background:{colorOf(e.buyer)}"></span>
              {#if e.buyer?.slug}<a href="/buyers/{e.buyer.slug}" style="text-decoration:none">{e.buyer.name}</a>{:else}<span>{e.buyer?.name || 'unknown'}</span>{/if}
              <span class="muted" style="margin-left:auto;font-variant-numeric:tabular-nums">{r.confirmed ? e.n : '≈' + (Math.round(e.n * 10) / 10)}</span></div>
            {#if e.aired}
              <div class="spots">{#each e.aired as a}{@const c = byAd.get(a.ad_id)}<a class="spot" href={a.ad_id ? `/ads/${a.ad_id}` : null} title="{fmtT(a.t)} · {a.ad_id || 'no Ad-ID'}">{#if c?.thumb_url}<img src={c.thumb_url} alt="" />{/if}<span>{fmtT(a.t)}</span><code>{a.ad_id || '—'}</code></a>{/each}</div>
            {:else}
              {@const ls = likely(e, r.station.fac)}
              {#if ls.length}<div class="spots">{#each ls as c (c.ad_id)}<a class="spot" href="/ads/{c.ad_id}" title="{c.ad_id} · {num(c.airings)} airings, last {c.last}">{#if c.thumb_url}<img src={c.thumb_url} alt="" />{/if}<code>{c.family || c.ad_id}</code></a>{/each}<span class="muted" style="font-size:11px;align-self:center">recent spots, likely</span></div>{/if}
            {/if}
          {/each}
        </div>
      {/each}
    {/if}
  {/each}
{/if}
<style>
  .spots { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 2px 14px; }
  .spot { display: inline-flex; align-items: center; gap: 5px; padding: 2px 6px 2px 2px; border: 1px solid var(--line); border-radius: 6px; background: var(--chip); text-decoration: none; font-size: 11.5px; color: var(--fg); }
  .spot img { width: 44px; height: 25px; object-fit: cover; border-radius: 4px; }
  .spot code { font-size: 11px; }
  .spot span { color: var(--muted); }
</style>

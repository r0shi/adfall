<script>
  // One search box for places, stations, buyers and Ad-IDs.
  import { goto } from '$app/navigation';
  import { get, stations as loadStations, buyers as loadBuyers, creatives as loadCreatives } from './data.js';
  import { geocode } from './geo.js';
  import { setLocation } from './location.svelte.js';
  let wide = $state(false), input;                         // phones: an icon that expands into a full-width field over the nav
  let q = $state(''), open = $state(false), results = $state.raw([]), sel = $state(0), busy = $state(false), el;
  let sts = null, bys = null, crs = null;
  async function search(text) {
    const t = text.trim(); if (t.length < 2) { results = []; return; }
    busy = true;
    sts ||= await loadStations(); bys ||= await loadBuyers();
    const tl = t.toLowerCase(), out = [];
    const callHits = sts.filter(s => s.call.toLowerCase().startsWith(tl) || s.call.toLowerCase().replace(/-.*/, '') === tl).slice(0, 4);
    for (const s of callHits) out.push({ kind: 'Station', label: `${s.call} · ${s.city}, ${s.state}`, href: `/stations/${s.fac}` });
    for (const b of bys.filter(b => b.name.toLowerCase().includes(tl)).slice(0, 5)) out.push({ kind: 'Buyer', label: `${b.name} · ${b.category === 'Non-Candidate Issue Ads' ? 'Issue' : b.category}${b.state ? ' · ' + b.state : ''}`, href: `/buyers/${b.slug}` });
    if (/^[A-Z0-9]{6,16}$/i.test(t)) { crs ||= await loadCreatives(); for (const c of crs.filter(c => c.ad_id.toUpperCase().startsWith(t.toUpperCase())).slice(0, 4)) out.push({ kind: 'Ad-ID', label: `${c.ad_id} · ${c.buyer || 'unknown buyer'} · ${c.airings} airings`, href: `/ads/${c.ad_id}` }); }
    if (/^\d{5}$/.test(t) || /^[a-z .'-]+(,\s*[a-z .]+)?$/i.test(t)) out.push({ kind: 'Place', label: `Go to "${t}"`, place: t });
    results = out; sel = 0; busy = false;
  }
  let timer; $effect(() => { const text = q; clearTimeout(timer); timer = setTimeout(() => search(text), 160); });
  async function pick(r) {
    open = false; q = ''; wide = false;
    if (r.place) { try { const g = await geocode(r.place); await setLocation(g.p, g.label); goto('/'); } catch { /* no match */ } }
    else goto(r.href);
  }
  function key(e) {
    if (e.key === 'ArrowDown') { sel = Math.min(results.length - 1, sel + 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); e.preventDefault(); }
    else if (e.key === 'Enter' && results[sel]) pick(results[sel]);
    else if (e.key === 'Escape') { open = false; wide = false; }
  }
</script>
<div class="sa" class:wide bind:this={el}>
  <button class="ghost saicon" onclick={async () => { wide = true; await Promise.resolve(); input?.focus(); }} title="Search places, stations, buyers and Ad-IDs" aria-label="Search">
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="7" cy="7" r="4.8" fill="none" stroke="currentColor" stroke-width="1.7" /><path d="M10.6 10.6 14 14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" /></svg>
  </button>
  <input type="search" placeholder="Place, station, buyer or Ad-ID" bind:this={input} bind:value={q} onfocus={() => open = true} oninput={() => open = true} onkeydown={key} onblur={() => setTimeout(() => { open = false; if (!q) wide = false; }, 150)} />
  {#if open && results.length}
    <div class="sa-list">
      {#each results as r, i}<div class="sa-item" class:on={i === sel} onmousedown={() => pick(r)} role="option" aria-selected={i === sel} tabindex="-1"><span class="muted small" style="width:52px;display:inline-block">{r.kind}</span>{r.label}</div>{/each}
    </div>
  {/if}
</div>
<style>
  .sa { position: relative; margin-left: auto; }
  .sa input { width: 260px; padding: 6px 10px; font-size: 13px; }
  .sa-list { position: absolute; right: 0; top: 36px; width: 380px; max-height: 320px; overflow: auto; background: var(--bg); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.18); z-index: 20; }
  .sa-item { padding: 7px 10px; font-size: 13px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sa-item.on, .sa-item:hover { background: var(--chip); }
  .saicon { display: none; }
  @media (max-width: 800px) {
    .saicon { display: grid; place-items: center; width: 34px; height: 34px; padding: 0; }
    .sa input { display: none; }
    .sa.wide { position: absolute; left: 8px; right: 8px; top: 7px; z-index: 30; }
    .sa.wide .saicon { display: none; }
    .sa.wide input { display: block; width: 100%; padding: 7px 10px; font-size: 15px; }
    .sa-list { width: calc(100vw - 16px); }
  }
</style>

<script>
  import Chart from '$lib/Chart.svelte';
  import { loc } from '$lib/location.svelte.js';
  import { buyers, stationSpend, usd, num, CATS, catShort, slugOf } from '$lib/data.js';
  import { colorOf, keyOf, plotColor, view } from '$lib/color.svelte.js';
  import Legend from '$lib/Legend.svelte';
  let all = $state([]), here = $state([]), cat = $state('All'), scope = $state('here'), q = $state(''), openId = $state(null), detail = $state(null);
  buyers().then(b => all = b);
  const facsHere = $derived(new Set(loc.found.map(s => s.fac)));
  // "here" scope: re-aggregate from the per-station files so amounts cover only the stations reaching this place
  $effect(() => {
    const facs = [...facsHere]; if (!facs.length) { here = []; return; }
    Promise.all(facs.map(f => stationSpend(f).catch(() => null))).then(files => aggregateHere(files.filter(Boolean)));
  });
  function aggregateHere(files) {
    const m = new Map();
    for (const d of files) for (const b of d.buyers) {
      const k = `${b.category}|${b.name}`; const e = m.get(k) || { id: k, name: b.name, category: b.category, kind: b.kind, party: b.party, office: b.office, booked: 0, invoiced: 0, orders: 0, spots_aired: 0, stations: 0, states: new Set(), facs: [] };
      e.booked += b.gross; e.invoiced += b.invoiced; e.orders += b.orders; e.spots_aired += b.spots_aired || 0; e.stations += 1; e.facs.push(d.fac);
      e.states.add(loc.all.find(s => s.fac === d.fac)?.state); m.set(k, e);
    }
    here = [...m.values()].map(e => ({ ...e, states: [...e.states].filter(Boolean).sort() })).sort((a, b) => b.booked - a.booked);
  }
  const source = $derived(scope === 'here' && loc.p ? here : all);
  const list = $derived(source
    .filter(b => cat === 'All' || b.category === cat)
    .filter(b => !q || b.name.toLowerCase().includes(q.toLowerCase())));
  const total = $derived(list.reduce((t, b) => t + b.booked, 0));
  async function open(b) {
    if (openId === b.id) { openId = null; return; }
    openId = b.id; detail = null;
    const rows = await Promise.all(b.facs.map(async f => { const d = await stationSpend(f); const me = d.buyers.find(x => x.name === b.name && x.category === b.category); return me && { fac: f, call: loc.all.find(s => s.fac === f)?.call || f, state: loc.all.find(s => s.fac === f)?.state, ...me }; }));
    detail = rows.filter(Boolean).sort((a, c) => c.gross - a.gross);
  }
  const top = $derived(list.slice(0, 25));
</script>
<svelte:head><title>Buyers · Adfall</title></svelte:head>
<div class="shell wide">
  <aside class="panel" style="border:0">
    <header>
      <h1>Who is buying</h1>
      <p class="tag">Political advertisers ranked by booked TV time, from the stations' own FCC filings. Booked is what was ordered; invoiced is what has aired and been billed so far.</p>
      <div class="chips">
        <span class="chip" class:on={scope === 'here'} onclick={() => scope = 'here'} role="button" tabindex="0">{loc.p ? `Reaching ${loc.label}` : 'Reaching my place (pick one on Stations)'}</span>
        <span class="chip" class:on={scope === 'all'} onclick={() => scope = 'all'} role="button" tabindex="0">All crawled stations</span>
        {#each ['All', ...Object.keys(CATS).filter(c => c !== 'Other')] as c}<span class="chip" class:on={cat === c} onclick={() => cat = c} role="button" tabindex="0">{catShort(c)}</span>{/each}
        <input type="search" placeholder="Find a buyer" bind:value={q} style="margin-left:auto;min-width:160px" />
      </div>
    </header>
    <section>
      <div class="muted small">{list.length} buyers · {usd(total)} booked{scope === 'here' && loc.p ? ` on the ${loc.found.length} stations reaching ${loc.label}` : ''}</div>
      {#if top.length}
        <Chart key={view.by} height={Math.max(200, 18 * top.length + 40)} make={(Plot, width, height) => Plot.plot({
          width, height, marginLeft: 220, x: { label: 'Booked ($)', tickFormat: 's', grid: true }, y: { label: null },
          color: plotColor(),
          marks: [
            Plot.barX(top, { x: 'booked', y: 'name', fill: d => keyOf(d), sort: { y: '-x' }, tip: true,
              title: d => `${d.name}\n${usd(d.booked)} booked · ${usd(d.invoiced)} invoiced\n${d.stations} station${d.stations === 1 ? '' : 's'} · ${d.states.join(', ')}` }),
            Plot.text(top, { x: 'booked', y: 'name', text: d => usd(d.booked), dx: 4, textAnchor: 'start', fontSize: 11, fill: 'var(--fg)' })
          ]
        })} />
        <Legend other toggle />
      {/if}
      <h2>All {list.length}</h2>
      {#each list.slice(0, 200) as b (b.id)}
        <div class="card" style="cursor:pointer" onclick={() => open(b)} role="button" tabindex="0" onkeydown={e => e.key === 'Enter' && open(b)}>
          <div class="row"><span class="dot" style="background:{colorOf(b)}"></span><a href="/buyers/{b.slug || slugOf(b.category, b.name)}" style="font-weight:700;text-decoration:none" onclick={e => e.stopPropagation()}>{b.name}</a><span class="amt">{usd(b.booked)}</span></div>
          <div class="muted small">{catShort(b.category)}{b.party ? ` · ${b.party}` : ''}{b.office ? ` · ${b.office}${b.district && b.district !== '00' ? ' ' + b.district.replace(/^0/, '') : ''}` : ''} · {b.stations} station{b.stations === 1 ? '' : 's'} in {b.states.join(', ')} · {b.orders} orders · {usd(b.invoiced)} invoiced · {num(b.spots_aired)} spots aired
            {#if b.fec_candidate_id}· <a href="https://www.fec.gov/data/candidate/{b.fec_candidate_id}/" target="_blank" rel="noopener" onclick={e => e.stopPropagation()}>FEC candidate</a>{:else if b.fec_committee_id}· <a href="https://www.fec.gov/data/committee/{b.fec_committee_id}/" target="_blank" rel="noopener" onclick={e => e.stopPropagation()}>FEC committee</a>{/if}
            {#if b.labels > 1}· merged from {b.labels} station labels{/if}</div>
          {#if openId === b.id}
            <div style="margin-top:8px;border-top:1px solid var(--line);padding-top:6px" onclick={e => e.stopPropagation()} role="presentation">
              {#if !detail}<span class="muted small">Loading…</span>{:else}
                {#each detail as r}
                  <div class="row small"><a href="/stations/{r.fac}" style="font-weight:700;text-decoration:none">{r.call}</a><span class="muted">{r.state}</span><span class="amt">{usd(r.gross)}</span></div>
                  <div class="bar"><i style="width:{(100 * r.gross / (detail[0]?.gross || 1)).toFixed(1)}%;background:{colorOf(b)}"></i></div>
                  <div class="muted" style="font-size:11.5px">{r.orders} orders · {usd(r.invoiced)} invoiced · {r.ad_ids} creatives{r.agencies?.length ? ` · via ${r.agencies.slice(0, 2).join(', ')}` : ''}</div>
                {/each}
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </section>
  </aside>
</div>

<script>
  import { page } from '$app/state';
  import Chart from '$lib/Chart.svelte';
  import { buyerDetail, usd, num, CATS, catShort, PLOT_COLORS } from '$lib/data.js';
  let d = $state(null), err = $state(null);
  $effect(() => { const slug = page.params.slug; d = null; buyerDetail(slug).then(x => d = x).catch(e => err = e.message); });
  const color = $derived(d ? (CATS[d.category] || CATS.Other) : 'var(--muted)');
</script>
<svelte:head><title>{d ? d.name : 'Buyer'} · TV Wormhole</title></svelte:head>
<div class="shell wide"><aside class="panel" style="border:0">
  {#if err}<section class="muted">Not found: {err}</section>
  {:else if !d}<section class="muted">Loading…</section>
  {:else}
    <header>
      <div class="muted small"><a href="/buyers">Buyers</a> › {catShort(d.category)}</div>
      <h1><span class="dot" style="background:{color};width:12px;height:12px"></span>{d.name}</h1>
      <div class="muted">{[d.party, d.office ? d.office + (d.district && d.district !== '00' ? ' ' + d.district.replace(/^0/, '') : '') : null, d.state].filter(Boolean).join(' · ')}</div>
      <div class="links">
        {#if d.fec_candidate_id}<a href="https://www.fec.gov/data/candidate/{d.fec_candidate_id}/" target="_blank" rel="noopener">FEC candidate {d.fec_candidate_id}</a>{/if}
        {#if d.fec_committee_id}<a href="https://www.fec.gov/data/committee/{d.fec_committee_id}/" target="_blank" rel="noopener">FEC committee{d.fec_committee_name ? `: ${d.fec_committee_name}` : ''}</a>{/if}
        <a href="/ads?q={encodeURIComponent(d.name)}">Ads aired</a>
      </div>
      <div class="rollup"><b>{usd(d.booked)}</b> booked · <b>{usd(d.invoiced)}</b> invoiced · {d.stations.length} station{d.stations.length === 1 ? '' : 's'} · {num(d.stations.reduce((t, s) => t + s.spots_aired, 0))} spots aired · {d.creatives.length} creative{d.creatives.length === 1 ? '' : 's'}</div>
    </header>
    <section>
      <h2>By station</h2>
      <Chart height={Math.max(140, 20 * Math.min(30, d.stations.length) + 40)} make={(Plot, width, height) => Plot.plot({
        width, height, marginLeft: 90, x: { label: 'Booked ($)', tickFormat: 's', grid: true }, y: { label: null },
        marks: [
          Plot.barX(d.stations.slice(0, 30), { x: 'booked', y: d_ => `${d_.call} (${d_.state})`, fill: color, fillOpacity: 0.35, sort: { y: '-x' }, tip: true, title: s => `${s.call} ${s.city}, ${s.state}\n${usd(s.booked)} booked · ${usd(s.invoiced)} invoiced · ${s.orders} orders` }),
          Plot.barX(d.stations.slice(0, 30), { x: 'invoiced', y: d_ => `${d_.call} (${d_.state})`, fill: color })
        ]
      })} />
      <div class="legend"><span><span class="dot" style="background:{color}"></span>invoiced (aired)</span><span><span class="dot" style="background:{color};opacity:.35"></span>booked</span></div>
      <h2>By week</h2>
      {#if d.weekly.length}
        <Chart height={180} make={(Plot, width, height) => Plot.plot({
          width, height, marginLeft: 48, x: { label: null }, y: { label: '$ / week', tickFormat: 's', grid: true },
          marks: [Plot.areaY(d.weekly, { x: w => new Date(w.week), y: 'booked', fill: color, fillOpacity: 0.15 }), Plot.lineY(d.weekly, { x: w => new Date(w.week), y: 'booked', stroke: color }),
                  Plot.lineY(d.weekly, { x: w => new Date(w.week), y: 'invoiced', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
                  Plot.tip(d.weekly, Plot.pointerX({ x: w => new Date(w.week), y: 'booked', title: w => `week of ${w.week}\n${usd(w.booked)} booked · ${usd(w.invoiced)} invoiced · ${num(w.spots)} spots` }))]
        })} />
      {/if}
      <h2>Stations</h2>
      {#each d.stations as s}
        <div class="card" style="padding:7px 12px">
          <div class="row small"><a href="/stations/{s.fac}" style="font-weight:700;text-decoration:none">{s.call}</a><span class="muted">{s.city}, {s.state}{s.group ? ` · ${s.group}` : ''}</span><span class="amt">{usd(s.booked)}</span></div>
          <div class="muted" style="font-size:11.5px">{s.orders} orders · {usd(s.invoiced)} invoiced · {num(s.spots_aired)} spots · {s.creatives} creatives{s.agencies.length ? ` · via ${s.agencies.slice(0, 2).join(', ')}` : ''}</div>
        </div>
      {/each}
      {#if d.creatives.length}
        <h2>Creatives aired</h2>
        {#each d.creatives.slice(0, 30) as c}
          <div class="row small" style="padding:3px 0;border-bottom:1px solid var(--line)"><a href="/ads/{c.ad_id}" style="font-family:ui-monospace,monospace;font-weight:700;text-decoration:none">{c.ad_id}</a><span class="muted">{c.first} → {c.last} · {c.stations.join(', ')}</span><span class="amt">{num(c.airings)}</span></div>
        {/each}
      {/if}
      {#if d.agencies.length}<h2>Agencies</h2><div class="chips">{#each d.agencies as a}<span class="chip">{a}</span>{/each}</div>{/if}
      <h2>Filed by stations as</h2>
      <div class="chips">{#each d.labels as l}<span class="chip" style="cursor:default">{l}</span>{/each}</div>
      <p class="muted small">Identity method: {d.method}. Corrections go in data/buyer_overrides.yaml.</p>
    </section>
  {/if}
</aside></div>

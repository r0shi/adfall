<script>
  import { page } from '$app/state';
  import Chart from '$lib/Chart.svelte';
  import Treemap from '$lib/Treemap.svelte';
  import Heatmap from '$lib/Heatmap.svelte';
  import { loc, ready, setLocation } from '$lib/location.svelte.js';
  import { stationDetail, stationSpend, usd, num, CATS, catShort } from '$lib/data.js';
  let d = $state(null), sp = $state(null), err = $state(null);
  $effect(() => { const fac = +page.params.fac; d = null; sp = null;
    Promise.all([stationDetail(fac), stationSpend(fac).catch(() => null), ready()]).then(([a, b]) => { d = a; sp = b; }).catch(e => err = e.message); });
  const st = $derived(d ? loc.all.find(s => s.fac === d.fac) : null);
</script>
<svelte:head><title>{d ? d.call : 'Station'} · TV Wormhole</title></svelte:head>
<div class="shell wide"><aside class="panel" style="border:0">
  {#if err}<section class="muted">Not found: {err}</section>
  {:else if !d}<section class="muted">Loading…</section>
  {:else}
    <header>
      <div class="muted small"><a href="/">Stations</a> › {d.state}</div>
      <h1>{d.call} <span class="muted" style="font-weight:400;font-size:16px">{d.city}, {d.state}{d.group ? ` · ${d.group}` : ''}</span></h1>
      <div class="links">
        {#if d.newson}<a class="live" href="https://www.newson.us/stationDetails/{d.newson}" target="_blank" rel="noopener">▶ Watch on NewsON</a>{/if}
        <a href="https://publicfiles.fcc.gov/tv-profile/{d.slug}/political-files" target="_blank" rel="noopener">Political ad buys (FCC)</a>
        <a href="https://publicfiles.fcc.gov/tv-profile/{d.slug}" target="_blank" rel="noopener">FCC file</a>
        {#if st}<a href="/#{st.tx[0].toFixed(4)},{st.tx[1].toFixed(4)}" onclick={() => setLocation(st.tx, `${d.call} transmitter`)}>Coverage map</a>{/if}
      </div>
      {#if sp}<div class="rollup"><b>{usd(sp.total)}</b> booked · <b>{usd(sp.invoiced)}</b> invoiced · {sp.buyers.length} buyers · {num(sp.spots_aired || 0)} spots aired · {sp.creatives || 0} creatives · {sp.docs} documents, {Math.round(100 * (sp.parse_status?.ok || 0) / sp.docs)}% parsed
        <div class="catbar">{#each Object.entries(sp.by_category).sort((a, b) => b[1] - a[1]) as [c, v]}<i style="width:{(100 * v / sp.total).toFixed(1)}%;background:{CATS[c] || CATS.Other}" title="{c}: {usd(v)}"></i>{/each}</div></div>{/if}
    </header>
    <section>
      {#if d.weekly.length}
        <h2>By week</h2>
        <Chart height={180} make={(Plot, width, height) => Plot.plot({
          width, height, marginLeft: 48, x: { label: null }, y: { label: '$ / week', tickFormat: 's', grid: true },
          marks: [Plot.areaY(d.weekly, { x: w => new Date(w.week), y: 'booked', fill: 'var(--accent)', fillOpacity: 0.15 }), Plot.lineY(d.weekly, { x: w => new Date(w.week), y: 'booked', stroke: 'var(--accent)' }),
                  Plot.lineY(d.weekly, { x: w => new Date(w.week), y: 'invoiced', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
                  Plot.tip(d.weekly, Plot.pointerX({ x: w => new Date(w.week), y: 'booked', title: w => `week of ${w.week}\n${usd(w.booked)} booked · ${usd(w.invoiced)} invoiced · ${num(w.spots)} spots` }))]
        })} />
      {/if}
      {#if sp}
        <h2>Who is buying here</h2>
        <Treemap items={sp.buyers.map(b => ({ id: `${b.category}|${b.name}`, key: b.name, value: b.gross, color: CATS[b.category] || CATS.Other, href: b.slug ? `/buyers/${b.slug}` : null }))} height={260} format={usd} />
        <div class="legend">{#each Object.entries(CATS).filter(([c]) => c !== 'Other') as [c, col]}<span><span class="dot" style="background:{col}"></span>{catShort(c)}</span>{/each}<span>· area = booked $</span></div>
      {/if}
      {#if d.daypart}<h2>When political ads ran</h2><Heatmap grid={d.daypart} />{/if}
      {#if sp}
        <h2>Buyers</h2>
        {#each sp.buyers.slice(0, 40) as b}
          <div style="margin:6px 0">
            <div class="row small"><span class="dot" style="background:{CATS[b.category] || CATS.Other}"></span><a href="/buyers/{b.slug}" style="text-decoration:none">{b.name}</a><span class="muted">{catShort(b.category)}</span><span class="amt">{usd(b.gross)}</span></div>
            <div class="bar"><i style="width:{(100 * b.gross / (sp.buyers[0]?.gross || 1)).toFixed(1)}%;background:{CATS[b.category] || CATS.Other}"></i></div>
            <div class="muted" style="font-size:11.5px">{b.orders} orders{b.invoiced ? ` · ${usd(b.invoiced)} invoiced` : ''}{b.ad_ids ? ` · ${b.ad_ids} creatives` : ''}{b.agencies?.length ? ` · via ${b.agencies.slice(0, 2).join(', ')}` : ''}</div>
          </div>
        {/each}
        {#if sp.buyers.length > 40}<div class="muted small">…and {sp.buyers.length - 40} more</div>{/if}
      {/if}
      {#if d.creatives.length}
        <h2>Most-aired creatives</h2>
        {#each d.creatives.slice(0, 30) as c}
          <div class="row small" style="padding:3px 0;border-bottom:1px solid var(--line)"><span class="dot" style="background:{CATS[c.category] || CATS.Other}"></span><a href="/ads/{c.ad_id}" style="font-family:ui-monospace,monospace;font-weight:700;text-decoration:none">{c.ad_id}</a>{#if c.slug}<a href="/buyers/{c.slug}" class="muted" style="text-decoration:none">{c.buyer}</a>{/if}<span class="muted">{c.first} → {c.last}</span><span class="amt">{num(c.airings)}</span></div>
        {/each}
      {/if}
    </section>
  {/if}
</aside></div>

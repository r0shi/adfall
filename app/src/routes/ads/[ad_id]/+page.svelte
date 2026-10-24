<script>
  import { page } from '$app/state';
  import Chart from '$lib/Chart.svelte';
  import { get, usd, num, CATS, catShort } from '$lib/data.js';
  let d = $state(null), err = $state(null);
  $effect(() => { const id = page.params.ad_id; d = null; get(`creatives/id/${id}.json`).then(x => d = x).catch(e => err = e.message); });
  const color = $derived(d ? (CATS[d.category] || CATS.Other) : 'var(--muted)');
  const hours = $derived(d ? d.by_hour.map((n, h) => ({ hour: h, n, label: `${h % 12 || 12}${h < 12 ? 'a' : 'p'}` })) : []);
</script>
<svelte:head><title>{d ? d.ad_id : 'Creative'} · TV Wormhole</title></svelte:head>
<div class="shell wide"><aside class="panel" style="border:0">
  {#if err}<section class="muted">Not found: {err}</section>
  {:else if !d}<section class="muted">Loading…</section>
  {:else}
    <header>
      <div class="muted small"><a href="/ads">Ads</a> › {catShort(d.category)}</div>
      <h1 style="font-family:ui-monospace,monospace">{d.ad_id}</h1>
      <div class="muted">{#if d.slug}<a href="/buyers/{d.slug}">{d.buyer}</a>{:else}unknown buyer{/if} · Ad-ID prefix <b>{d.prefix}</b> (identifies the advertiser in the Ad-ID registry)</div>
      <div class="rollup"><b>{num(d.airings)}</b> airings on record · {d.by_station.length} station{d.by_station.length === 1 ? '' : 's'} · {d.first} → {d.last}</div>
    </header>
    <section>
      <h2>Airings by day</h2>
      <Chart height={160} make={(Plot, width, height) => Plot.plot({
        width, height, marginLeft: 36, x: { label: null }, y: { label: 'airings / day', grid: true },
        marks: [Plot.rectY(d.by_day.map(([day, n]) => ({ day: new Date(day), n })), { x: 'day', y: 'n', interval: 'day', fill: color, tip: true })]
      })} />
      <h2>Time of day</h2>
      <Chart height={140} make={(Plot, width, height) => Plot.plot({
        width, height, marginLeft: 36, x: { label: null, domain: hours.map(h => h.label) }, y: { label: 'airings', grid: true },
        marks: [Plot.barY(hours, { x: 'label', y: 'n', fill: color, tip: true, title: h => `${h.label}: ${h.n} airings` })]
      })} />
      <h2>By station</h2>
      {#each d.by_station as s}
        <div class="row small" style="padding:4px 0;border-bottom:1px solid var(--line)"><a href="/stations/{s.fac}" style="font-weight:700;text-decoration:none">{s.call}</a><span class="muted">{s.state}</span><span class="amt">{num(s.airings)}</span></div>
      {/each}
      <p class="muted small" style="margin-top:14px">The video itself is not in the FCC file. The Ad-ID code is the registry key the campaign used; the same code appears in the spot's online and connected-TV versions.</p>
    </section>
  {/if}
</aside></div>

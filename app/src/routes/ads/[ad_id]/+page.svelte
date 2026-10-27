<script>
  import { page } from '$app/state';
  import Chart from '$lib/Chart.svelte';
  import { get, usd, num, CATS, catShort } from '$lib/data.js';
  import { colorOf } from '$lib/color.svelte.js';
  import Player from '$lib/video/Player.svelte';            // video chain (ingest.video)
  import Badge from '$lib/video/Badge.svelte';
  let d = $state(null), err = $state(null);
  $effect(() => { const id = page.params.ad_id; d = null; get(`creatives/id/${id}.json`).then(x => d = x).catch(e => err = e.message); });
  const color = $derived(d ? colorOf(d) : 'var(--muted)');
  const hours = $derived(d ? d.by_hour.map((n, h) => ({ hour: h, n, label: `${h % 12 || 12}${h < 12 ? 'a' : 'p'}` })) : []);
</script>
<svelte:head><title>{d ? d.ad_id : 'Creative'} · Adfall</title></svelte:head>
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
      <!-- video chain: the matched upload, how it was matched, and the runner-up -->
      {#if d.video_url}
        <h2 style="margin-top:0">The ad{#if d.video_title} · <span class="muted" style="font-weight:400">{d.video_title}</span>{/if}</h2>
        <div style="max-width:720px"><Player video={d} title={d.video_title || d.ad_id} autoplay={false} /></div>
        <p class="muted small" style="margin:6px 0 0">
          {#if d.source === 'google-ads'}No upload on the campaign's channel lines up, but the advertiser started a Google video ad within days of the first airing ({(d.matched_by || '').match(/candidates=(\d+)/)?.[1] || '?'} candidate{(d.matched_by || '').includes('candidates=1,') || (d.matched_by || '').endsWith('candidates=1') ? '' : 's'} that week). Google's page plays it; it may be a different cut of the same spot. <Badge confidence={d.confidence} source={d.source} size="inline" />
          {:else if d.source === 'override'}Verified by hand.{:else}Matched to the buyer's own channel by {(d.matched_by || '').split(',').filter(x => x && x !== 'exact-date').join(', ') || 'date'}:
            uploaded {d.video_published || '?'}{#if d.video_duration} · {d.video_duration}s{/if} vs first aired {d.first}. <Badge confidence={d.confidence} source={d.source} size="inline" /> {Math.round((d.confidence || 0) * 100)}% confidence.{/if}
          {#if d.google_url}It also ran as a Google video ad that week: <a href={d.google_url} target="_blank" rel="noopener">Ads Transparency Center ↗</a>.{/if}
          {#if d.runner_up}Runner-up: <a href={d.runner_up.video_url} target="_blank" rel="noopener">{d.runner_up.title || 'another upload'}</a> ({Math.round((d.runner_up.confidence || 0) * 100)}%).{/if}
          {#if d.family && d.family !== d.ad_id}Spot family <b style="font-family:ui-monospace,monospace">{d.family}</b>: the invoices append a per-airing tail to this code; every variant maps to the same video.{/if}
        </p>
      {/if}
      <!-- /video chain -->
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
      <!-- video chain -->
      <p class="muted small" style="margin-top:14px">The video itself is not in the FCC file. The Ad-ID code is the registry key the campaign used; the same code appears in the spot's online and connected-TV versions.{#if !d.video_url} No public upload matched this one yet: the buyer has no channel on record, or none of its uploads lines up with the airing dates. Corrections go in <code>data/video_overrides.yaml</code>.{/if}</p>
      <!-- /video chain -->
    </section>
  {/if}
</aside></div>

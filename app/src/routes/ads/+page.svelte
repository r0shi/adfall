<script>
  import Chart from '$lib/Chart.svelte';
  import { loc } from '$lib/location.svelte.js';
  import { creatives, num, CATS, catShort, slugOf } from '$lib/data.js';
  import { colorOf, keyOf, plotColor, view } from '$lib/color.svelte.js';
  import Legend from '$lib/Legend.svelte';
  import { tip } from '$lib/tip.svelte.js';
  let all = $state([]), scope = $state('here'), cat = $state('All'), q = $state(''), mode = $state('cloud');
  creatives().then(c => all = c);
  const facsHere = $derived(new Set(loc.found.map(s => s.fac)));
  const hereOn = $derived(scope === 'here' && !!loc.p);
  const list = $derived(all
    .filter(c => cat === 'All' || c.category === cat)
    .map(c => hereOn ? { ...c, airings: Object.entries(c.facs).reduce((t, [f, n]) => t + (facsHere.has(+f) ? n : 0), 0) } : c)
    .filter(c => c.airings > 0)
    .filter(c => !q || (c.buyer || '').toLowerCase().includes(q.toLowerCase()) || c.ad_id.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => b.airings - a.airings));
  const airings = $derived(list.reduce((t, c) => t + c.airings, 0));
  const byBuyer = $derived.by(() => {
    const m = new Map();
    for (const c of list) { const k = c.buyer || `(${c.prefix}…)`; const e = m.get(k) || { buyer: k, category: c.category, airings: 0, creatives: 0, slug: c.buyer ? slugOf(c.category, c.buyer) : null, top: c.ad_id }; e.airings += c.airings; e.creatives += 1; m.set(k, e); }
    return [...m.values()].sort((a, b) => b.airings - a.airings);
  });
  const top = $derived(list.slice(0, 150));
  const maxA = $derived(top[0]?.airings || 1);
  const cloud = $derived(byBuyer.slice(0, 120));          // the cloud is by buyer; the list is by creative
  const maxB = $derived(cloud[0]?.airings || 1);
  const size = (a, mx) => 11 + 28 * Math.sqrt(a / mx);
  const slugFor = (b) => b.slug || null;
</script>
<svelte:head><title>Ads · Adfall</title></svelte:head>
<div class="shell wide">
  <aside class="panel" style="border:0">
    <header>
      <h1>Ads actually aired</h1>
      <p class="tag">Every invoice lists the spots that ran, with the Ad-ID code of the creative. Bigger means aired more often. The code is the industry's registry ID for the spot; the first four letters identify the advertiser.</p>
      <div class="chips">
        <span class="chip" class:on={scope === 'here'} onclick={() => scope = 'here'} role="button" tabindex="0">{loc.p ? `Aired on stations reaching ${loc.label}` : 'Reaching my place (pick one on Stations)'}</span>
        <span class="chip" class:on={scope === 'all'} onclick={() => scope = 'all'} role="button" tabindex="0">All crawled stations</span>
        {#each ['All', ...Object.keys(CATS).filter(c => c !== 'Other')] as c}<span class="chip" class:on={cat === c} onclick={() => cat = c} role="button" tabindex="0">{catShort(c)}</span>{/each}
        <span class="chip" class:on={mode === 'cloud'} onclick={() => mode = 'cloud'} role="button" tabindex="0">Cloud</span>
        <span class="chip" class:on={mode === 'list'} onclick={() => mode = 'list'} role="button" tabindex="0">List</span>
        <input type="search" placeholder="Buyer or Ad-ID" bind:value={q} style="margin-left:auto;min-width:160px" />
      </div>
    </header>
    <section>
      <div class="muted small">{num(list.length)} creatives · {num(airings)} airings on record</div>
      {#if mode === 'cloud'}
        <div class="cloud" style="margin:12px 0">
          {#each cloud as b (b.buyer)}
            <a href={b.slug ? `/buyers/${b.slug}` : `/ads/${b.top}`} style="font-size:{size(b.airings, maxB).toFixed(0)}px;color:{colorOf(b)};text-decoration:none" use:tip={{ html: true, text: `<b>${b.buyer}</b>\n${num(b.airings)} airings · ${b.creatives} creative${b.creatives === 1 ? '' : 's'}` }}>{b.buyer}</a>
          {/each}
        </div>
        <Legend other><span>· sized by airings; switch to List for individual creatives</span></Legend>
      {:else}
        {#each list.slice(0, 150) as c (c.ad_id)}
          <div class="card" style="padding:7px 12px">
            <div class="row small"><span class="dot" style="background:{colorOf(c)}"></span><a href="/ads/{c.ad_id}" style="font-family:ui-monospace,monospace;font-weight:700;text-decoration:none">{c.ad_id}</a>{#if c.buyer}<a href="/buyers/{slugOf(c.category, c.buyer)}" class="muted" style="text-decoration:none">{c.buyer}</a>{:else}<span class="muted">unknown buyer</span>{/if}<span class="amt">{num(c.airings)}</span></div>
            <div class="bar"><i style="width:{(100 * c.airings / maxA).toFixed(1)}%;background:{colorOf(c)}"></i></div>
            <div class="muted" style="font-size:11.5px">{c.first} → {c.last} · {Object.keys(c.facs).length} station{Object.keys(c.facs).length === 1 ? '' : 's'}</div>
          </div>
        {/each}
      {/if}
      <h2>Airings by buyer</h2>
      {#if byBuyer.length}
        <Chart key={view.by} height={Math.max(160, 18 * Math.min(20, byBuyer.length) + 40)} make={(Plot, width, height) => Plot.plot({
          width, height, marginLeft: 220, x: { label: 'Spots aired', grid: true }, y: { label: null },
          color: plotColor(),
          marks: [Plot.barX(byBuyer.slice(0, 20), { x: 'airings', y: 'buyer', fill: d => keyOf(d), sort: { y: '-x' }, tip: true, title: d => `${d.buyer}\n${num(d.airings)} airings · ${d.creatives} creatives` })]
        })} />
      {/if}
    </section>
  </aside>
</div>

<script>
  import Chart from '../Chart.svelte';
  import { tl } from '../time.svelte.js';
  import { stationDaily, usd, num } from '../data.js';
  let { found, idx = null } = $props();
  import Coverage from '../Coverage.svelte';
  let daily = $state.raw(null);
  stationDaily().then(d => daily = d);
  const today = new Date().toISOString().slice(0, 10);
  const weekly = $derived.by(() => {
    if (!daily) return [];
    const facs = new Set(found.map(s => s.fac)), by = new Map();
    for (const [fac, day, booked, invoiced, spots] of daily.rows) {
      if (!facs.has(fac)) continue;
      const d = new Date(day + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); const wk = d.toISOString().slice(0, 10);
      const e = by.get(wk) || { week: new Date(wk), key: wk, booked: 0, invoiced: 0, spots: 0, future: wk > today }; e.booked += booked; e.invoiced += invoiced; e.spots += spots; by.set(wk, e);
    }
    return [...by.values()].sort((a, b) => a.week - b.week);
  });
  const past = $derived(weekly.filter(w => !w.future)), future = $derived(weekly.filter(w => w.future || w.key === past[past.length - 1]?.key));
  const totals = $derived({ booked: weekly.reduce((t, w) => t + w.booked, 0), invoiced: weekly.reduce((t, w) => t + w.invoiced, 0), ahead: weekly.filter(w => w.future).reduce((t, w) => t + w.booked, 0) });
</script>
{#if !daily}<div class="muted small">Loading…</div>
{:else if !weekly.length}<Coverage {found} {idx} what="spending over time" />
{:else}
  <div class="muted small" style="margin-bottom:6px"><b>{usd(totals.booked)}</b> booked on these stations · {usd(totals.invoiced)} invoiced so far{totals.ahead ? ` · ${usd(totals.ahead)} scheduled ahead` : ''}</div>
  <Chart height={200} make={(Plot, width, height) => Plot.plot({
    width, height, marginLeft: 48, x: { label: null }, y: { label: '$ / week', tickFormat: 's', grid: true },
    marks: [
      Plot.areaY(past, { x: 'week', y: 'booked', fill: 'var(--accent)', fillOpacity: 0.15 }),
      Plot.lineY(past, { x: 'week', y: 'booked', stroke: 'var(--accent)' }),
      Plot.lineY(future, { x: 'week', y: 'booked', stroke: 'var(--accent)', strokeOpacity: 0.35, strokeDasharray: '2,3' }),
      Plot.lineY(past, { x: 'week', y: 'invoiced', stroke: 'var(--muted)', strokeDasharray: '3,3' }),
      tl.day ? Plot.ruleX([new Date(tl.day)], { stroke: 'var(--fg)', strokeOpacity: 0.5 }) : null,
      Plot.tip(weekly, Plot.pointerX({ x: 'week', y: 'booked', title: w => `week of ${w.key}${w.future ? ' (scheduled)' : ''}\n${usd(w.booked)} booked · ${usd(w.invoiced)} invoiced · ${num(w.spots)} spots aired` }))
    ]
  })} />
  <div class="legend"><span><span class="dot" style="background:var(--accent)"></span>booked</span><span><span class="dot" style="background:var(--muted)"></span>invoiced (lags a billing cycle)</span><span>· dotted: scheduled after today</span></div>
{/if}

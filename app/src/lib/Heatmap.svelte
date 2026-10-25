<script>
  // Daypart heatmap: grid[weekday Mon=0][hour] -> Plot cells. Row = weekday, column = hour of day.
  import Chart from './Chart.svelte';
  let { grid = null, height = 190, title = 'airings' } = $props();
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const HOURS = Array.from({ length: 24 }, (_, h) => `${h % 12 || 12}${h < 12 ? 'a' : 'p'}`);
  const rows = $derived(grid ? grid.flatMap((r, d) => r.map((n, h) => ({ day: DAYS[d], hour: HOURS[h], n, d, h }))) : []);
  const total = $derived(rows.reduce((t, r) => t + r.n, 0));
  const peak = $derived(rows.reduce((b, r) => r.n > b.n ? r : b, { n: 0 }));
</script>
{#if rows.length && total}
  <Chart {height} make={(Plot, width, height) => Plot.plot({
    width, height, marginLeft: 36, marginBottom: 28, padding: 0.08,
    x: { domain: HOURS, label: null, tickFormat: (d, i) => i % 3 === 0 ? d : '' }, y: { domain: DAYS, label: null },
    color: { scheme: 'reds', type: 'sqrt', label: title },
    marks: [Plot.cell(rows, { x: 'hour', y: 'day', fill: 'n', inset: 0.5, tip: true, title: r => `${r.day} ${r.hour}: ${r.n.toLocaleString()} ${title}` })]
  })} />
  <div class="muted" style="font-size:11.5px">Peak: {peak.day} {peak.hour} ({peak.n.toLocaleString()} {title}) · {total.toLocaleString()} total with a known air time</div>
{:else}<div class="muted small">No air times on record.</div>{/if}

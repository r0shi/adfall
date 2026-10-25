<script>
  import Chart from '$lib/Chart.svelte';
  import { PRESETS, TABLES, query, open } from '$lib/duck.js';
  let sql = $state(PRESETS[0][1]), status = $state('not loaded'), result = $state(null), err = $state(null), running = $state(false), schema = $state({});
  async function boot() {
    status = 'starting DuckDB…';
    await open(s => { if (s) status = s; });
    status = 'ready';
    for (const t of ['station', 'buyer', 'buyer_station', 'station_total', 'station_daily']) { try { schema[t] = (await query(`DESCRIBE ${t}`)).rows.map(r => r.column_name); } catch { /* missing mart */ } }
  }
  async function run() {
    if (running) return;
    running = true; err = null;
    try { if (status !== 'ready') await boot(); const t0 = performance.now(); result = { ...(await query(sql)), ms: Math.round(performance.now() - t0) }; }
    catch (e) { err = e.message; }
    running = false;
  }
  function onkey(e) { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); run(); } }
  const isNum = (v) => typeof v === 'number';
  const chart = $derived.by(() => {
    if (!result?.rows.length) return null;
    const cols = result.cols.map(c => c.name); const r0 = result.rows[0];
    const dateCol = cols.find(c => /date|week|day|month/i.test(c) || r0[c] instanceof Date || /^\d{4}-\d\d-\d\d/.test(String(r0[c])));
    const numCols = cols.filter(c => isNum(r0[c]) && c !== dateCol);
    const strCols = cols.filter(c => !isNum(r0[c]) && c !== dateCol);
    if (dateCol && numCols.length) return { kind: 'line', x: dateCol, y: numCols[0], series: strCols[0] || null };
    if (strCols.length && numCols.length) return { kind: 'bar', x: numCols[0], y: strCols[0], series: strCols[1] || null };
    return null;
  });
  const csv = () => {
    const cols = result.cols.map(c => c.name);
    const esc = v => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const blob = new Blob([[cols.join(','), ...result.rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\n')], { type: 'text/csv' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'tv-wormhole-query.csv'; a.click();
  };
</script>
<svelte:head><title>Explore · TV Wormhole</title></svelte:head>
<div class="shell wide"><aside class="panel" style="border:0">
  <header>
    <h1>Explore</h1>
    <p class="tag">SQL over the data marts, running in your browser (DuckDB-WASM over Parquet). Nothing leaves your machine. Cmd/Ctrl+Enter runs.</p>
    <div class="chips">
      {#each PRESETS as [name, q]}<span class="chip" class:on={sql === q} onclick={() => { sql = q; run(); }} role="button" tabindex="0">{name}</span>{/each}
    </div>
    <textarea bind:value={sql} onkeydown={onkey} spellcheck="false" style="width:100%;min-height:140px;font:13px/1.4 ui-monospace,monospace;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--chip);color:var(--fg);resize:vertical"></textarea>
    <div class="row" style="margin-top:8px;gap:10px">
      <button onclick={run} disabled={running}>{running ? 'Running…' : 'Run'}</button>
      {#if result}<button class="ghost" onclick={csv}>Download CSV</button>{/if}
      <span class="muted small">{status}{result ? ` · ${result.rows.length} rows in ${result.ms} ms` : ''}</span>
    </div>
    {#if err}<div style="color:var(--accent);font-family:ui-monospace,monospace;font-size:12.5px;margin-top:8px;white-space:pre-wrap">{err}</div>{/if}
  </header>
  <section>
    {#if chart && result}
      <Chart height={chart.kind === 'bar' ? Math.max(160, 18 * Math.min(40, result.rows.length) + 40) : 240} make={(Plot, width, height) => chart.kind === 'line'
        ? Plot.plot({ width, height, marginLeft: 56, x: { label: null }, y: { label: chart.y, tickFormat: 's', grid: true }, color: { legend: !!chart.series },
            marks: [Plot.lineY(result.rows.map(r => ({ ...r, [chart.x]: new Date(r[chart.x]) })), { x: chart.x, y: chart.y, stroke: chart.series || 'var(--accent)', tip: true })] })
        : Plot.plot({ width, height, marginLeft: 200, x: { label: chart.x, tickFormat: 's', grid: true }, y: { label: null }, color: { legend: !!chart.series },
            marks: [Plot.barX(result.rows.slice(0, 40), { x: chart.x, y: chart.y, fill: chart.series || 'var(--accent)', sort: { y: '-x' }, tip: true })] })} />
    {/if}
    {#if result}
      <div style="overflow:auto;max-height:60vh;margin-top:10px;border:1px solid var(--line);border-radius:8px">
        <table style="border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;min-width:100%">
          <thead><tr>{#each result.cols as c}<th style="text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg)">{c.name}<div class="muted" style="font-weight:400;font-size:10.5px">{c.type}</div></th>{/each}</tr></thead>
          <tbody>{#each result.rows.slice(0, 500) as r}<tr>{#each result.cols as c}<td style="padding:4px 10px;border-bottom:1px solid var(--line);white-space:nowrap">{isNum(r[c.name]) ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(r[c.name]) : (r[c.name] instanceof Date ? r[c.name].toISOString().slice(0, 10) : r[c.name])}</td>{/each}</tr>{/each}</tbody>
        </table>
      </div>
      {#if result.rows.length > 500}<div class="muted small">Showing 500 of {result.rows.length} rows; download the CSV for all.</div>{/if}
    {/if}
    <h2>Tables</h2>
    {#each TABLES as t}
      <details ontoggle={async e => { if (e.target.open && !schema[t]) { try { schema[t] = (await query(`DESCRIBE ${t}`)).rows.map(r => r.column_name); } catch { schema[t] = ['(not exported)']; } } }}><summary style="cursor:pointer;font-family:ui-monospace,monospace;font-size:13px">{t}</summary><div class="muted small" style="padding:4px 0 8px 16px">{(schema[t] || ['…']).join(', ')}</div></details>
    {/each}
    <p class="muted small" style="margin-top:12px">Grain: <b>order_</b>-level booked dollars are in buyer_station/station_total; <b>spend_daily</b> places them on days (schedule lines when present, else the flight window); <b>spot</b> is one aired airing from an invoice; <b>hex_total</b> spreads station totals over H3 cells by population.</p>
  </section>
</aside></div>

<script>
  // The global timeline bar: every playback choice lives here. Header: play, date, what to show; the scrubline (a sparkline
  // of the series); footer: window, trails, speed. mode 'wk' (week vs last) only needs the day, so it drops the metric and window.
  import { tl, setRange, step, ANIM } from './time.svelte.js';
  let { series = [], label = '', mode = 'animate' } = $props();   // series is a plain array from the page (not deep state)   // series: [[day, value], ...]
  let el, width = $state(600), dragging = $state(false), timer;
  $effect(() => { const ro = new ResizeObserver(([e]) => { width = e.contentRect.width; }); ro.observe(el); return () => ro.disconnect(); });
  $effect(() => { if (series.length && !tl.first) setRange(series[0][0], series[series.length - 1][0]); });
  $effect(() => { clearInterval(timer); if (tl.playing) timer = setInterval(() => { step(1); if (tl.day === tl.last) tl.playing = false; }, 700 / tl.speed); return () => clearInterval(timer); });
  const WINDOWS = [['day', 'Day', 'Day'], ['week', 'Week', 'Week'], ['cumulative', 'Cumulative', 'To date']];
  const SPEEDS = [[0.5, '½×'], [1, '1×'], [2, '2×'], [4, '4×']];
  const H = 44, PAD = 8;
  const max = $derived(Math.max(1, ...series.map(s => s[1])));
  const x = (i) => PAD + (i / Math.max(1, series.length - 1)) * (width - 2 * PAD);
  const path = $derived(series.length ? series.map((s, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${(H - 4 - (s[1] / max) * (H - 10)).toFixed(1)}`).join(' ') : '');
  const curI = $derived(series.findIndex(s => s[0] >= tl.day));
  const dateLabel = $derived(tl.day ? new Date(tl.day + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : '');
  function pick(e) { const r = el.getBoundingClientRect(); const t = Math.min(1, Math.max(0, (e.clientX - r.left - PAD) / (r.width - 2 * PAD))); const i = Math.round(t * (series.length - 1)); if (series[i]) tl.day = series[i][0]; }
  const ticks = $derived.by(() => { const out = []; let last = ''; series.forEach((s, i) => { const m = s[0].slice(0, 7); if (m !== last) { out.push({ i, label: new Date(s[0] + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }) }); last = m; } }); return out; });
  const fmt = (v) => tl.metric === 'spots' && mode === 'animate' ? `${Math.round(v).toLocaleString()} spots` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
  const windowLabel = $derived(mode === 'wk' ? 'week ending' : tl.window === 'cumulative' ? 'cumulative through' : tl.window === 'week' ? 'week ending' : 'day');
  const value = $derived(curI >= 0 && series[curI] ? fmt(tl.window === 'week' ? series.slice(Math.max(0, curI - 6), curI + 1).reduce((t, s) => t + s[1], 0) : series[curI][1]) : '');
  function toggle() { if (tl.day === tl.last) tl.day = tl.first; tl.playing = !tl.playing; }
</script>
<div class="tlbar">
  <div class="tlhead">
    <button class="tlplay" onclick={toggle} title={tl.playing ? 'Pause' : 'Play'} aria-label={tl.playing ? 'Pause' : 'Play'}>
      {#if tl.playing}<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="3" y="2" width="3.5" height="12" rx="1" fill="currentColor" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" fill="currentColor" /></svg>
      {:else}<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2.2v11.6a.8.8 0 0 0 1.2.7l9.3-5.8a.8.8 0 0 0 0-1.4L5.2 1.5A.8.8 0 0 0 4 2.2z" fill="currentColor" /></svg>{/if}
    </button>
    <div class="tldate"><span class="tlwin">{windowLabel}</span><b>{dateLabel}</b></div>
    {#if value}<div class="tlval"><b>{value}</b><span>{label}</span></div>{/if}
    {#if mode === 'animate'}
      <div class="seg what" role="radiogroup" aria-label="What the map shows">
        {#each ANIM as [k, l, short]}<button role="radio" aria-checked={tl.metric === k} class:on={tl.metric === k} onclick={() => tl.metric = k}><span class="long">{l}</span><span class="short">{short}</span></button>{/each}
      </div>
    {/if}
  </div>
  <div class="tlscrub" bind:this={el} onpointerdown={e => { dragging = true; pick(e); e.currentTarget.setPointerCapture(e.pointerId); }} onpointermove={e => dragging && pick(e)} onpointerup={() => dragging = false} role="slider" tabindex="0" aria-label="Date" aria-valuenow={curI} onkeydown={e => { if (e.key === 'ArrowRight') step(1); if (e.key === 'ArrowLeft') step(-1); if (e.key === ' ') { e.preventDefault(); tl.playing = !tl.playing; } }}>
    <svg width={width} height={H}>
      <path d={path + (series.length ? ` L${x(series.length - 1).toFixed(1)},${H - 4} L${x(0).toFixed(1)},${H - 4} Z` : '')} fill="var(--accent)" fill-opacity="0.18" stroke="none" />
      <path d={path} fill="none" stroke="var(--accent)" stroke-width="1.5" />
      {#each ticks as t}<text x={x(t.i)} y={H - 1} font-size="9" fill="var(--muted)">{t.label}</text>{/each}
      {#if curI >= 0}<line x1={x(curI)} x2={x(curI)} y1="0" y2={H} stroke="var(--fg)" stroke-width="1.5" /><circle cx={x(curI)} cy={H - 4 - ((series[curI]?.[1] || 0) / max) * (H - 10)} r="4" fill="var(--fg)" />{/if}
    </svg>
  </div>
  <div class="tlfoot">
    {#if mode === 'animate'}
      <div class="grp"><span class="lbl">Window</span><div class="seg" role="radiogroup" aria-label="Window">{#each WINDOWS as [k, l, short]}<button role="radio" aria-checked={tl.window === k} class:on={tl.window === k} onclick={() => tl.window = k}><span class="long">{l}</span><span class="short">{short}</span></button>{/each}</div></div>
      <div class="grp"><button class="tog" class:on={tl.trails} aria-pressed={tl.trails} onclick={() => tl.trails = !tl.trails} title="Previous frames fade slowly instead of vanishing"><i></i>Trails</button></div>
    {/if}
    <button class="tog speed1" onclick={() => tl.speed = SPEEDS[(SPEEDS.findIndex(s => s[0] === tl.speed) + 1) % SPEEDS.length][0]} title="Playback speed (tap to change)" aria-label="Playback speed">{SPEEDS.find(s => s[0] === tl.speed)?.[1] || '1×'}</button>
    <div class="grp speeds"><span class="lbl">Speed</span><div class="seg" role="radiogroup" aria-label="Playback speed">{#each SPEEDS as [k, l]}<button role="radio" aria-checked={tl.speed === k} class:on={tl.speed === k} onclick={() => tl.speed = k}>{l}</button>{/each}</div></div>
  </div>
</div>
<style>
  .tlbar { pointer-events: auto; padding: 8px 12px 8px; border-radius: 14px;
    background: color-mix(in srgb, var(--bg) 80%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); box-shadow: 0 4px 18px rgb(0 0 0 / 0.12); }
  .tlhead { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .tlplay { width: 40px; height: 40px; padding: 0; border-radius: 50%; display: grid; place-items: center; flex: none; }
  .tlplay svg { margin-left: 1px; }
  .tldate { display: flex; flex-direction: column; min-width: 128px; }
  .tldate b { font-size: 20px; letter-spacing: -0.01em; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .tlwin, .tlval span, .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .tlval { display: flex; flex-direction: column-reverse; padding-left: 12px; border-left: 1px solid var(--line); }
  .tlval b { font-size: 15px; font-variant-numeric: tabular-nums; line-height: 1.2; }
  .tlval span { text-transform: none; letter-spacing: 0; }
  .what { margin-left: auto; }
  .tlscrub { cursor: ew-resize; user-select: none; touch-action: none; margin-top: 6px; }
  .tlfoot { display: flex; align-items: center; gap: 8px 16px; flex-wrap: wrap; margin-top: 4px; padding-top: 6px; border-top: 1px solid var(--line); }
  .grp { display: flex; align-items: center; gap: 6px; }
  .seg { display: inline-flex; padding: 2px; gap: 2px; border-radius: 9px; background: var(--chip); border: 1px solid var(--line); }
  .seg button { padding: 3px 9px; font-size: 12.5px; font-weight: 500; color: var(--muted); background: transparent; border-radius: 7px; white-space: nowrap; }
  .seg button:hover { color: var(--fg); }
  .seg button.on { background: var(--bg); color: var(--fg); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 0.18); }
  .what button { padding: 5px 11px; font-size: 13px; }
  .what button.on { background: var(--accent); color: #fff; }
  .short, .speed1 { display: none; }
  .tog { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 6px; font-size: 12.5px; font-weight: 500; color: var(--muted); background: var(--chip); border: 1px solid var(--line); border-radius: 999px; }
  .tog i { width: 22px; height: 12px; border-radius: 6px; background: var(--line); position: relative; transition: background 0.15s; }
  .tog i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 8px; height: 8px; border-radius: 50%; background: var(--bg); transition: left 0.15s; }
  .tog.on { color: var(--fg); }
  .tog.on i { background: var(--accent); }
  .tog.on i::after { left: 12px; background: #fff; }
  @media (max-width: 800px) {
    .tlbar { padding: 8px 10px; }
    .tldate b { font-size: 17px; }
    .tldate { min-width: 0; }
    .what { margin-left: 0; width: 100%; display: flex; }
    .what button { flex: 1; padding: 5px 4px; }
    .long { display: none; } .short { display: inline; }
    .tlfoot { gap: 6px 12px; }
    .lbl, .speeds { display: none; }
    .speed1 { display: inline-flex; padding: 3px 10px; font-variant-numeric: tabular-nums; }
  }
</style>

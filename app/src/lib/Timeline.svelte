<script>
  // The global timeline bar: date, scrubline (a sparkline of the series), play, window and trails.
  import { tl, setRange, step } from './time.svelte.js';
  let { series = [], label = '' } = $props();   // series is a plain array from the page (not deep state)   // series: [[day, value], ...]
  let el, width = $state(600), dragging = $state(false), timer;
  $effect(() => { const ro = new ResizeObserver(([e]) => { width = e.contentRect.width; }); ro.observe(el); return () => ro.disconnect(); });
  $effect(() => { if (series.length && !tl.first) setRange(series[0][0], series[series.length - 1][0]); });
  $effect(() => { clearInterval(timer); if (tl.playing) timer = setInterval(() => { step(1); if (tl.day === tl.last) tl.playing = false; }, 700 / tl.speed); return () => clearInterval(timer); });
  const H = 44, PAD = 8;
  const max = $derived(Math.max(1, ...series.map(s => s[1])));
  const x = (i) => PAD + (i / Math.max(1, series.length - 1)) * (width - 2 * PAD);
  const path = $derived(series.length ? series.map((s, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${(H - 4 - (s[1] / max) * (H - 10)).toFixed(1)}`).join(' ') : '');
  const curI = $derived(series.findIndex(s => s[0] >= tl.day));
  const dateLabel = $derived(tl.day ? new Date(tl.day + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : '');
  function pick(e) { const r = el.getBoundingClientRect(); const t = Math.min(1, Math.max(0, (e.clientX - r.left - PAD) / (r.width - 2 * PAD))); const i = Math.round(t * (series.length - 1)); if (series[i]) tl.day = series[i][0]; }
  const ticks = $derived.by(() => { const out = []; let last = ''; series.forEach((s, i) => { const m = s[0].slice(0, 7); if (m !== last) { out.push({ i, label: new Date(s[0] + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }) }); last = m; } }); return out; });
  const fmt = (v) => tl.metric === 'spots' ? `${Math.round(v).toLocaleString()} spots` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
</script>
<div class="tlbar">
  <div class="tlhead">
    <button class="ghost tlplay" onclick={() => { if (tl.day === tl.last) tl.day = tl.first; tl.playing = !tl.playing; }} title="Play / pause">{tl.playing ? '❚❚' : '▶'}</button>
    <div class="tldate"><b>{dateLabel}</b><span class="muted small">{tl.window === 'cumulative' ? 'cumulative through' : tl.window === 'week' ? 'week ending' : 'day'}{label ? ` · ${label}` : ''}{curI >= 0 && series[curI] ? ` · ${fmt(tl.window === 'week' ? series.slice(Math.max(0, curI - 6), curI + 1).reduce((t, s) => t + s[1], 0) : series[curI][1])}` : ''}</span></div>
    <div class="chips tlchips">
      {#each [['day', 'Day'], ['week', 'Week'], ['cumulative', 'Cumulative']] as [k, l]}<span class="chip" class:on={tl.window === k} onclick={() => tl.window = k} role="button" tabindex="0">{l}</span>{/each}
      <span class="chip" class:on={tl.trails} onclick={() => tl.trails = !tl.trails} role="button" tabindex="0" title="Previous frames fade slowly instead of vanishing">Trails</span>
      <select bind:value={tl.speed} class="small" title="Playback speed"><option value={0.5}>½×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select>
    </div>
  </div>
  <div class="tlscrub" bind:this={el} onpointerdown={e => { dragging = true; pick(e); e.currentTarget.setPointerCapture(e.pointerId); }} onpointermove={e => dragging && pick(e)} onpointerup={() => dragging = false} role="slider" tabindex="0" aria-valuenow={curI} onkeydown={e => { if (e.key === 'ArrowRight') step(1); if (e.key === 'ArrowLeft') step(-1); if (e.key === ' ') { e.preventDefault(); tl.playing = !tl.playing; } }}>
    <svg width={width} height={H}>
      <path d={path + (series.length ? ` L${x(series.length - 1).toFixed(1)},${H - 4} L${x(0).toFixed(1)},${H - 4} Z` : '')} fill="var(--accent)" fill-opacity="0.18" stroke="none" />
      <path d={path} fill="none" stroke="var(--accent)" stroke-width="1.5" />
      {#each ticks as t}<text x={x(t.i)} y={H - 1} font-size="9" fill="var(--muted)">{t.label}</text>{/each}
      {#if curI >= 0}<line x1={x(curI)} x2={x(curI)} y1="0" y2={H} stroke="var(--fg)" stroke-width="1.5" /><circle cx={x(curI)} cy={H - 4 - ((series[curI]?.[1] || 0) / max) * (H - 10)} r="4" fill="var(--fg)" />{/if}
    </svg>
  </div>
</div>
<style>
  .tlbar { position: absolute; left: 12px; right: 12px; bottom: 12px; z-index: 4; padding: 8px 12px 6px; border-radius: 12px;
    background: color-mix(in srgb, var(--bg) 72%, transparent); backdrop-filter: blur(10px); border: 1px solid var(--line); }
  .tlhead { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .tlplay { width: 36px; height: 36px; padding: 0; font-size: 14px; }
  .tldate { display: flex; flex-direction: column; min-width: 180px; }
  .tldate b { font-size: 20px; letter-spacing: -0.01em; line-height: 1.1; }
  .tlchips { margin: 0 0 0 auto; align-items: center; }
  .tlscrub { cursor: ew-resize; user-select: none; touch-action: none; margin-top: 4px; }
  @media (max-width: 800px) { .tldate b { font-size: 16px; } .tlbar { left: 6px; right: 6px; bottom: 6px; } }
</style>

<script>
  // Floating panel anchored to the pin; draggable; collapses to a pill; a bottom sheet on phones.
  let { api, anchor, title, sub = '', tabs = [], active = $bindable(), collapsed = $bindable(false), children, onclose = null } = $props();
  let pos = $state({ x: 40, y: 40 }), drag = $state(null), el;
  let userMoved = $state(false), w = 420, h = 520;
  function place() {
    if (!api || !anchor || userMoved) return;
    const [x, y] = api.project(anchor), [W, H] = api.size();
    let px = x + 18, py = y - 24;
    if (px + w > W - 8) px = Math.max(8, x - w - 18);
    if (py + h > H - 8) py = Math.max(8, H - h - 8);
    if (py < 8) py = 8;
    if (px < 390 && py < 150 && H > 400) py = 150;          // keep clear of the search card at top-left
    pos = { x: px, y: py };
  }
  $effect(() => { if (api) { api.onMove(place); } });
  $effect(() => { if (api && anchor) { userMoved = false; place(); } });   // re-runs when the map becomes ready or the pin moves
  function down(e) { if (e.target.closest('button, a, .chip, input, select')) return; drag = { dx: e.clientX - pos.x, dy: e.clientY - pos.y }; e.currentTarget.setPointerCapture(e.pointerId); }
  function move(e) { if (!drag) return; userMoved = true; pos = { x: e.clientX - drag.dx, y: e.clientY - drag.dy }; }
</script>
<div class="pop" class:collapsed bind:this={el} style="left:{pos.x}px;top:{pos.y}px">
  <div class="pophead" onpointerdown={down} onpointermove={move} onpointerup={() => drag = null} role="presentation">
    <div class="poptitle"><b>{title}</b>{#if sub}<span class="muted small">{sub}</span>{/if}</div>
    <button class="ghost popbtn" onclick={() => collapsed = !collapsed} title={collapsed ? 'Expand' : 'Collapse'}>{collapsed ? '▴' : '▾'}</button>
    {#if onclose}<button class="ghost popbtn" onclick={onclose} title="Clear place">×</button>{/if}
  </div>
  {#if !collapsed}
    {#if tabs.length}<div class="poptabs">{#each tabs as t}<button class="tab" class:on={active === t.id} onclick={() => active = t.id}>{t.label}</button>{/each}</div>{/if}
    <div class="popbody">{@render children()}</div>
  {/if}
</div>
<style>
  .pop { position: absolute; z-index: 5; width: 420px; max-height: min(560px, calc(100% - 80px)); display: flex; flex-direction: column;
    background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(12px); border: 1px solid var(--line); border-radius: 14px;
    box-shadow: 0 10px 30px rgba(0,0,0,.18); overflow: hidden; }
  .pop.collapsed { width: auto; max-width: 420px; }
  .pophead { display: flex; align-items: center; gap: 6px; padding: 10px 12px; cursor: grab; user-select: none; border-bottom: 1px solid var(--line); }
  .pop.collapsed .pophead { border-bottom: 0; }
  .poptitle { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .poptitle b { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .popbtn { width: 28px; height: 28px; padding: 0; font-size: 14px; }
  .poptabs { display: flex; gap: 2px; padding: 6px 8px 0; border-bottom: 1px solid var(--line); }
  .tab { background: none; color: var(--muted); font-weight: 600; padding: 6px 10px; border-radius: 8px 8px 0 0; }
  .tab.on { color: var(--fg); background: var(--chip); }
  .popbody { overflow: auto; padding: 10px 12px; min-height: 0; }
  @media (max-width: 800px) {
    .pop { left: 0 !important; top: auto !important; bottom: 0; width: 100%; max-height: 58vh; border-radius: 14px 14px 0 0; }
    .pop.collapsed { width: 100%; }
  }
</style>

<script module>
  // where each open popover sits (by badge), so two of them keep out of each other's way
  const placed = new Map();
</script>
<script>
  // Floating panel anchored to the pin; draggable; collapses to a pill. On phones it is a bottom sheet with three heights:
  // peek (the header: collapsed), half, and tall; drag the header or its handle between them, or tap it to peek / open.
  import { untrack } from 'svelte';
  import { phone, sheetHeight } from './phone.svelte.js';
  let { api, anchor, title, sub = '', tabs = [], active = $bindable(), collapsed = $bindable(false), children, onclose = null, badge = '', accent = '', oncompare = null, compareLabel = 'Compare', prefer = 'right' } = $props();
  let pos = $state({ x: 40, y: 40 }), drag = $state(null), el;
  let userMoved = $state(false), w = 420, h = 520;
  let tall = $state(false), dragH = $state(null);          // phone sheet: tall height, and the live height while dragging
  const id = badge || 'A';
  const rect = () => ({ x: pos.x, y: pos.y, w: el?.offsetWidth || w, h: el?.offsetHeight || h });
  const hits = (r, o) => r.x < o.x + o.w && o.x < r.x + r.w && r.y < o.y + o.h && o.y < r.y + r.h;
  function place() {
    if (!api || !anchor || userMoved) return;
    const [x, y] = api.project(anchor), [W, H] = api.size();
    const right = x + 18, left = Math.max(8, x - w - 18);
    let px = prefer === 'left' ? left : right, py = y - 24;
    if (prefer !== 'left' && px + w > W - 8) px = left;
    if (prefer === 'left' && x - w - 18 < 8 && right + w <= W - 8) px = right;
    if (py + h > H - 8) py = Math.max(8, H - h - 8);
    if (py < 8) py = 8;
    if (px < 440 && py < 150 && H > 400) py = 150;          // keep clear of the search card at top-left
    // stay off the other popover: try the other side of the pin, then below it, then above
    for (const [k, o] of placed) {
      if (k === id || !hits({ x: px, y: py, w, h }, o)) continue;
      const alt = px === right ? left : right;
      if (!hits({ x: alt, y: py, w, h }, o) && alt >= 8 && alt + w <= W - 8) { px = alt; break; }
      if (o.y + o.h + 8 + h <= H - 8) { py = o.y + o.h + 8; break; }
      if (o.y - 8 - h >= 8) { py = o.y - 8 - h; break; }
    }
    pos = { x: px, y: py };
    placed.set(id, rect());
  }
  $effect(() => { if (api) { api.onMove(place); } });
  // re-runs only when the map becomes ready or the pin moves: place() reads pos and userMoved, which must not re-trigger it (that undid every drag)
  $effect(() => { if (api && anchor) untrack(() => { userMoved = false; place(); }); });
  // drag by the header: listeners go on the window for the duration, so a fast drag that leaves the header still follows
  function down(e) {
    if (e.button !== 0 || e.target.closest('button, a, .chip, input, select')) return;
    e.preventDefault();
    if (phone.on) return sheetDrag(e);
    const d = { dx: e.clientX - pos.x, dy: e.clientY - pos.y }; drag = d;
    const mv = (ev) => { userMoved = true; pos = { x: ev.clientX - d.dx, y: ev.clientY - d.dy }; placed.set(id, rect()); };
    const up = () => { drag = null; window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
  }
  $effect(() => () => placed.delete(id));
  // phone sheet: follow the finger, then snap to the nearest of peek / half / tall; a tap without movement toggles peek
  function sheetDrag(e) {
    const y0 = e.clientY, h0 = el.offsetHeight, H = el.parentElement.clientHeight; let moved = false;
    const mv = (ev) => { const dy = ev.clientY - y0; if (Math.abs(dy) > 6) moved = true; if (moved) dragH = Math.max(60, Math.min(H - 64, h0 - dy)); };
    const up = () => {
      window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up);
      if (!moved) { collapsed = !collapsed; tall = false; }
      else { const snaps = [[90, 'peek'], [H * 0.5, 'half'], [H - 64, 'tall']]; const [, to] = snaps.reduce((b, s) => Math.abs(s[0] - dragH) < Math.abs(b[0] - dragH) ? s : b);
        collapsed = to === 'peek'; tall = to === 'tall'; }
      dragH = null;
    };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
  }
  $effect(() => { if (!el) return; const ro = new ResizeObserver(() => sheetHeight(id, phone.on ? el.offsetHeight : 0)); ro.observe(el); return () => { ro.disconnect(); sheetHeight(id, 0); }; });
  $effect(() => { sheetHeight(id, phone.on && el ? el.offsetHeight : 0); });
</script>
<div class="pop" class:collapsed class:tall class:dragging={dragH !== null} bind:this={el} style="left:{pos.x}px;top:{pos.y}px" style:height={dragH !== null ? `${dragH}px` : null}>
  <div class="grab" onpointerdown={down} role="presentation"><i></i></div>
  <div class="pophead" class:dragging={!!drag} onpointerdown={down} role="presentation">
    {#if badge}<span class="badge" style:background={accent || 'var(--fg)'}>{badge}</span>{/if}
    <div class="poptitle"><b>{title}</b>{#if sub}<span class="muted small">{sub}</span>{/if}</div>
    {#if oncompare}<button class="ghost popbtn" style="width:auto;padding:0 8px;font-size:12px" onclick={oncompare} title="Drop a second pin to compare">{compareLabel}</button>{/if}
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
  .badge { width: 22px; height: 22px; border-radius: 50%; color: #fff; font-weight: 700; font-size: 12px; display: inline-flex; align-items: center; justify-content: center; flex: none; }
  .pophead { display: flex; align-items: center; gap: 6px; padding: 10px 12px; cursor: grab; user-select: none; touch-action: none; border-bottom: 1px solid var(--line); }
  .pophead.dragging { cursor: grabbing; }
  .pop.collapsed .pophead { border-bottom: 0; }
  .poptitle { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .poptitle b { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .popbtn { width: 28px; height: 28px; padding: 0; font-size: 14px; }
  .poptabs { display: flex; gap: 2px; padding: 6px 8px 0; border-bottom: 1px solid var(--line); }
  .tab { background: none; color: var(--muted); font-weight: 600; padding: 6px 10px; border-radius: 8px 8px 0 0; }
  .tab.on { color: var(--fg); background: var(--chip); }
  .popbody { overflow: auto; overscroll-behavior: contain; padding: 10px 12px; min-height: 0; }
  .grab { display: none; }
  @media (max-width: 800px) {
    .pop { left: 0 !important; top: auto !important; bottom: 0; width: 100%; height: 50%; max-height: none; border-radius: 14px 14px 0 0; transition: height 0.18s ease; }
    .pop.tall { height: calc(100% - 64px); }
    .pop.collapsed { width: 100%; height: auto; max-width: none; }
    .pop.dragging { transition: none; }
    .grab { display: flex; justify-content: center; padding: 6px 0 0; touch-action: none; cursor: grab; }
    .grab i { width: 36px; height: 4px; border-radius: 2px; background: var(--line); }
    .pophead { padding: 4px 12px 8px; }
    .poptitle span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .poptabs { flex: none; overflow-x: auto; scrollbar-width: none; }
    .pophead, .grab { flex: none; }
    .tab { white-space: nowrap; padding: 6px 9px; }
  }
</style>

<script>
  // Squarified treemap. items: [{ key, value, color, href?, sub? }]. One level, labels when the tile is big enough.
  import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy';
  let { items = [], height = 260, format = v => String(v), onpick = null } = $props();
  let el, width = $state(400);
  $effect(() => { const ro = new ResizeObserver(([e]) => width = Math.max(200, e.contentRect.width)); ro.observe(el); return () => ro.disconnect(); });
  const tiles = $derived.by(() => {
    const data = items.filter(d => d.value > 0);
    if (!data.length) return [];
    const root = hierarchy({ children: data }).sum(d => d.value).sort((a, b) => b.value - a.value);
    treemap().tile(treemapSquarify).size([width, height]).paddingInner(2).round(true)(root);
    return root.leaves().map((n, i) => ({ id: n.data.id ?? `${n.data.key}#${i}`, ...n.data, x: n.x0, y: n.y0, w: n.x1 - n.x0, h: n.y1 - n.y0, share: n.value / root.value }));
  });
</script>
<div class="tm" bind:this={el} style="height:{height}px">
  {#each tiles as t (t.id ?? t.key)}
    <a class="tile" href={t.href || null} style="left:{t.x}px;top:{t.y}px;width:{t.w}px;height:{t.h}px;background:{t.color}" title="{t.key} · {format(t.value)} · {(100 * t.share).toFixed(1)}%"
       onclick={e => { if (onpick) { e.preventDefault(); onpick(t); } }}>
      {#if t.w > 54 && t.h > 26}<span class="lbl">{t.key}</span>{/if}
      {#if t.w > 70 && t.h > 42}<span class="val">{format(t.value)}</span>{/if}
    </a>
  {/each}
</div>
<style>
  .tm { position: relative; width: 100%; overflow: hidden; border-radius: 8px; }
  .tile { position: absolute; display: flex; flex-direction: column; justify-content: flex-start; padding: 4px 6px; box-sizing: border-box; overflow: hidden;
    color: #fff; text-decoration: none; border-radius: 3px; transition: filter .12s; }
  .tile:hover { filter: brightness(1.15); outline: 2px solid var(--fg); outline-offset: -2px; }
  .lbl { font-size: 12px; font-weight: 600; line-height: 1.15; text-shadow: 0 1px 2px rgba(0,0,0,.35); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .val { font-size: 11px; opacity: .9; font-variant-numeric: tabular-nums; }
</style>

// deck.gl layer for one timeline frame. Stable per-cell identity so color transitions interpolate per cell.
export function makeFrameLayer(H3HexagonLayer, framer, { max, speed = 1, triggers = [], onHover, onClick }) {
  const shown = framer.shown, raw = framer.raw, cells = framer.cells;
  framer._index ||= Array.from(cells, (_, i) => i);
  return new H3HexagonLayer({
    id: 'frame', data: framer._index, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.85,
    getFillColor: i => { const t = Math.sqrt(Math.min(1, shown[i] / max)); return [200, 16 + 120 * (1 - t), 46 + 150 * (1 - t), Math.round(255 * Math.min(1, t * 1.4))]; },
    onHover: ({ object }) => onHover && onHover(object == null ? null : { h3: cells[object], shown: shown[object], raw: raw[object] }),
    onClick: ({ object }) => object != null && onClick && onClick(cells[object]),
    transitions: { getFillColor: { duration: Math.min(650, 600 / speed), easing: t => t } },
    updateTriggers: { getFillColor: triggers }
  });
}
/** 98th percentile of cell values over sampled frames, for a stable color scale per window. */
export function frameScale(framer, win) {
  const vals = []; const keep = framer.shown.slice();
  for (let i = 0; i < framer.dayList.length; i += 7) { framer.reset(); for (const [, v] of framer.frame(framer.dayList[i], win)) vals.push(v); }
  framer.shown.set(keep);
  vals.sort((a, b) => a - b); return vals[Math.floor(vals.length * 0.98)] || 1;
}

// deck.gl layer for one timeline frame. Stable per-cell identity so color transitions interpolate per cell.
import { rampRGBA, partyRGBA } from './palette.js';
export function makeFrameLayer(H3HexagonLayer, framer, { max, speed = 1, triggers = [], onHover, onClick }) {
  const shown = framer.shown, raw = framer.raw, cells = framer.cells;
  framer._index ||= Array.from(cells, (_, i) => i);
  return new H3HexagonLayer({
    id: 'frame', data: framer._index, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.85,
    getFillColor: i => { const t = Math.sqrt(Math.min(1, shown[i] / max)); const c = rampRGBA(t); c[3] = Math.round(c[3] * Math.min(1, t * 1.6)); return c; },
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

/** Party-share frame: two framers (Democratic and Republican booked $) with the same decay; hue by share, alpha by amount. */
export function makePartyFrameLayer(H3HexagonLayer, fd, fr, { max, speed = 1, triggers = [], onHover, onClick }) {
  const cells = fd.cells, d = fd.shown, r = fr.shown;
  fd._index ||= Array.from(cells, (_, i) => i);
  return new H3HexagonLayer({
    id: 'frame', data: fd._index, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.9,
    getFillColor: i => { const t = d[i] + r[i]; return t ? partyRGBA(d[i] / t, Math.sqrt(t / max)) : [0, 0, 0, 0]; },
    onHover: ({ object }) => onHover && onHover(object == null ? null : { h3: cells[object], party: true, share: d[object] / ((d[object] + r[object]) || 1), total: d[object] + r[object], raw: (fd.raw?.[object] || 0) + (fr.raw?.[object] || 0) }),
    onClick: ({ object }) => object != null && onClick && onClick(cells[object]),
    transitions: { getFillColor: { duration: Math.min(650, 600 / speed), easing: t => t } },
    updateTriggers: { getFillColor: triggers }
  });
}
export function partyFrameScale(fd, fr, win) {
  const vals = []; const kd = fd.shown.slice(), kr = fr.shown.slice();
  for (let i = 0; i < fd.dayList.length; i += 7) {
    fd.reset(); fr.reset(); fd.frame(fd.dayList[i], win); fr.frame(fd.dayList[i], win);
    for (let c = 0; c < fd.cells.length; c++) { const t = fd.shown[c] + fr.shown[c]; if (t > 0) vals.push(t); }
  }
  fd.shown.set(kd); fr.shown.set(kr);
  vals.sort((a, b) => a - b); return vals[Math.floor(vals.length * 0.98)] || 1;
}

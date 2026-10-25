// Difference layers: per-station signed values spread over cells by population share (same weights as the frames).
import { WARM, COOL, DEM, REP } from './palette.js';
export const DIFFS = {
  dr: { label: 'D − R', desc: 'Democratic minus Republican candidate dollars reaching each cell', pos: 'Democratic', neg: 'Republican', posColor: DEM, negColor: REP },
  bi: { label: 'Booked − invoiced', desc: 'Dollars booked but not yet billed (the pipeline still to air), minus nothing where invoices have caught up', pos: 'still to air', neg: 'billed above booking', posColor: WARM, negColor: COOL },
  wk: { label: 'This week − last', desc: 'Change in booked dollars versus the previous week (momentum)', pos: 'rising', neg: 'falling', posColor: WARM, negColor: COOL }
};
export function stationDiffs(mode, idx, framer = null, day = null) {
  const out = new Map();
  if (mode === 'wk' && framer && day) {
    const prev = (d) => { const x = new Date(d + 'T00:00:00Z'); x.setUTCDate(x.getUTCDate() - 7); return x.toISOString().slice(0, 10); };
    for (const fac of framer.byStation.keys()) out.set(fac, framer.stationValue(fac, day, 'week') - framer.stationValue(fac, prev(day), 'week'));
    return out;
  }
  for (const [fac, s] of Object.entries(idx.stations)) {
    if (mode === 'dr') out.set(+fac, (s.by_party?.Democratic || 0) - (s.by_party?.Republican || 0));
    else if (mode === 'bi') out.set(+fac, (s.total || 0) - (s.invoiced || 0));
  }
  return out;
}
export function composeDiff(weights, values) {
  const cells = weights.cells, v = new Float64Array(cells.length);
  for (const [fac, val] of values) { if (!val) continue; const ws = weights.stations[fac]; if (!ws) continue; for (const [i, w] of ws) v[i] += val * w; }
  return v;
}
export function makeDiffLayer(H3HexagonLayer, weights, v, scale, mode, { onHover, onClick, triggers }) {
  const cells = weights.cells, m = DIFFS[mode];
  weights._index ||= Array.from(cells, (_, i) => i);
  return new H3HexagonLayer({
    id: 'diff', data: weights._index, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.85,
    getFillColor: i => { const x = v[i]; if (!x) return [0, 0, 0, 0]; const t = Math.sqrt(Math.min(1, Math.abs(x) / scale)); const c = x > 0 ? m.posColor : m.negColor; return [c[0], c[1], c[2], Math.round(255 * Math.min(1, t * 1.3))]; },
    onHover: ({ object }) => onHover && onHover(object == null ? null : { h3: cells[object], value: v[object] }),
    onClick: ({ object }) => object != null && onClick && onClick(cells[object]),
    transitions: { getFillColor: 300 }, updateTriggers: { getFillColor: triggers }
  });
}
export function diffScale(v) { const a = Array.from(v).map(Math.abs).filter(x => x > 0).sort((x, y) => x - y); return a[Math.floor(a.length * 0.98)] || 1; }

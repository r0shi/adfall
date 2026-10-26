// Difference layers: per-station signed values spread over cells by population share (same weights as the frames).
import { WARM, COOL, DEM, REP, partyRGBA } from './palette.js';
export const DIFFS = {
  party: { label: 'Party share', desc: 'Candidate dollars reaching each cell, colored by the Democratic (blue) or Republican (red) share; fainter cells carry less candidate money. Issue-group money has no party and is left out', pos: 'Democratic', neg: 'Republican', posColor: DEM, negColor: REP },
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
    if (mode === 'bi') out.set(+fac, (s.total || 0) - (s.invoiced || 0));
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

/** Party share per cell: value-by-alpha. share = Democratic / (Democratic + Republican) candidate dollars, total = the sum;
 *  unknown-party candidates and issue groups are excluded from both, which the legend says. */
export function composeParty(weights, idx) {
  const cells = weights.cells, dem = new Float64Array(cells.length), rep = new Float64Array(cells.length), unk = new Float64Array(cells.length);
  for (const [fac, s] of Object.entries(idx.stations)) {
    const ws = weights.stations[fac]; if (!ws) continue;
    const d = s.by_party?.Democratic || 0, r = s.by_party?.Republican || 0, u = s.by_party?.Unknown || 0;
    if (!d && !r && !u) continue;
    for (const [i, w] of ws) { dem[i] += d * w; rep[i] += r * w; unk[i] += u * w; }
  }
  const total = new Float64Array(cells.length), share = new Float32Array(cells.length);
  for (let i = 0; i < cells.length; i++) { total[i] = dem[i] + rep[i]; share[i] = total[i] ? dem[i] / total[i] : NaN; }
  return { dem, rep, unk, total, share };
}
export function makePartyLayer(H3HexagonLayer, weights, p, scale, { onHover, onClick, triggers }) {
  const cells = weights.cells;
  weights._index ||= Array.from(cells, (_, i) => i);
  return new H3HexagonLayer({
    id: 'party', data: weights._index, getHexagon: i => cells[i], filled: true, extruded: false, stroked: false, pickable: true, opacity: 0.9,
    getFillColor: i => {
      const t = p.total[i]; if (!t) return [0, 0, 0, 0];
      return partyRGBA(p.share[i], Math.sqrt(t / scale));
    },
    onHover: ({ object }) => onHover && onHover(object == null ? null : { h3: cells[object], share: p.share[object], total: p.total[object], unk: p.unk[object] }),
    onClick: ({ object }) => object != null && onClick && onClick(cells[object]),
    transitions: { getFillColor: 300 }, updateTriggers: { getFillColor: triggers }
  });
}

// Compose hex frames in the client: station_daily (per station per day) × station weights over cells.
// value_cell(day, window) = Σ_station window_sum(station, day) × w(station, cell). Cumulative = prefix sums.
export class Framer {
  constructor(daily, weights, metricIndex = 2) {
    this.cells = weights.cells; this.w = weights.stations; this.idx = metricIndex; // station_daily columns: fac, day, booked, invoiced, spots
    this.byStation = new Map();                       // fac -> Map(day -> value)
    this.days = new Set();
    for (const r of daily.rows) { const m = this.byStation.get(r[0]) || new Map(); m.set(r[1], r[metricIndex] || 0); this.byStation.set(r[0], m); this.days.add(r[1]); }
    this.dayList = [...this.days].sort();
    this.cum = new Map();                              // fac -> Map(day -> cumulative through that day)
    for (const [fac, m] of this.byStation) { let acc = 0; const c = new Map(); for (const d of this.dayList) { acc += m.get(d) || 0; c.set(d, acc); } this.cum.set(fac, c); }
    this.shown = new Float64Array(this.cells.length); // decayed display values
  }
  stationValue(fac, day, win) {
    if (win === 'cumulative') { const c = this.cum.get(fac); if (!c) return 0; let best = 0; for (const d of this.dayList) { if (d > day) break; best = c.get(d); } return best; }
    const m = this.byStation.get(fac); if (!m) return 0;
    if (win === 'day') return m.get(day) || 0;
    let s = 0; const end = new Date(day + 'T00:00:00Z');
    for (let i = 0; i < 7; i++) { const d = new Date(end); d.setUTCDate(d.getUTCDate() - i); s += m.get(d.toISOString().slice(0, 10)) || 0; }
    return s;
  }
  stationTotals(day, win, facs = null) {
    const out = new Map();
    for (const fac of (facs || this.byStation.keys())) out.set(fac, this.stationValue(fac, day, win));
    return out;
  }
  frame(day, win, { decay = 0, facs = null } = {}) {
    const raw = this.raw ||= new Float64Array(this.cells.length);
    raw.fill(0);
    for (const [fac, v] of this.stationTotals(day, win, facs)) { if (!v) continue; const ws = this.w[fac]; if (!ws) continue; for (const [i, w] of ws) raw[i] += v * w; }
    for (let i = 0; i < raw.length; i++) this.shown[i] = decay ? Math.max(raw[i], this.shown[i] * decay) : raw[i];
    const out = [];
    for (let i = 0; i < raw.length; i++) if (this.shown[i] > 0) out.push([this.cells[i], this.shown[i], raw[i]]);
    return out;                      // sparse view (used for scale sampling); the layer reads this.shown / this.raw by index
  }
  reset() { this.shown.fill(0); }
  series(win, facs = null) {   // total per day for the scrubline (national or a set of stations)
    const st = facs ? [...facs].filter(f => this.byStation.has(f)) : [...this.byStation.keys()];
    return this.dayList.map(d => [d, st.reduce((t, f) => t + (win === 'cumulative' ? (this.cum.get(f).get(d) || 0) : (this.byStation.get(f).get(d) || 0)), 0)]);
  }
}

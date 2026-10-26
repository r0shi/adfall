// Global timeline state: the day being looked at, the window it summarizes, and playback.
export const tl = $state({
  day: null,            // 'YYYY-MM-DD'
  first: null, last: null,
  window: 'week',       // 'day' | 'week' | 'cumulative'
  playing: false,
  speed: 1,             // frames per tick multiplier
  trails: true,         // slow decay of previous frames while playing/scrubbing
  metric: 'booked'      // 'booked' | 'invoiced' | 'spots' | 'party' (Democratic share of candidate $, value-by-alpha)
});
export const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
export const FIRST_DAY = '2025-11-01';      // the view starts here; earlier bookings still count in cumulative windows
export function setRange(first, last) {
  const today = new Date().toISOString().slice(0, 10);
  tl.first = first < FIRST_DAY ? FIRST_DAY : first; tl.last = last > today ? today : last;      // the future holds only thin scheduled bookings; the cycle ends today
  if (!tl.day || tl.day < tl.first || tl.day > tl.last) tl.day = tl.last;
}
export function step(n = 1) { if (!tl.day) return; const next = addDays(tl.day, n * (tl.window === 'day' ? 1 : 7)); tl.day = next > tl.last ? tl.first : next < tl.first ? tl.last : next; }

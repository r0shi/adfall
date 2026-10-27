// The Over time data, shared by the map's animate / week-vs-last layers and /time: station_daily rows, res-5 weights,
// the deck.gl hex layer module, and one Framer per metric. Loads once per page life. The state is visible so a failed
// load is shown and can be retried: data.js forgets a failed fetch, so a retry refetches instead of replaying the error.
import { stationDaily, hexWeights, forget } from './data.js';
import { Framer } from './frames.js';
import { setRange } from './time.svelte.js';
import { lazy, describe } from './recover.js';

export const td = $state({ status: 'idle', error: null, slow: false });   // idle | loading | ready | error
const COL = { booked: 2, invoiced: 3, spots: 4 };                          // station_daily columns; party reads 5 (dem) and 6 (rep)
let data = null, layerMod = null, inflight = null;                         // big and non-reactive; td.status is the signal
const framers = new Map();

export const geoLayers = () => layerMod;
export function framerFor(metric) {
  if (!data) return null;
  if (!framers.has(metric)) {
    const { daily, weights } = data;
    framers.set(metric, metric === 'party' ? { d: new Framer(daily, weights, 5), r: new Framer(daily, weights, 6) } : new Framer(daily, weights, COL[metric] ?? 2));
  }
  return framers.get(metric);
}

export function loadTimeData() {
  if (inflight) return inflight;
  td.status = 'loading'; td.error = null; td.slow = false;
  const slowTimer = setTimeout(() => { td.slow = true; }, 12_000);
  inflight = Promise.all([stationDaily(), hexWeights(5), lazy(() => import('@deck.gl/geo-layers'))])
    .then(([d, w, m]) => {
      data = { daily: d, weights: w }; layerMod = m; framers.clear();
      const days = framerFor('booked').dayList;
      if (!days.length) throw new Error('station_daily.json has no rows');
      setRange(days[0], days[days.length - 1]);
      td.status = 'ready';
    })
    .catch(e => { inflight = null; td.status = 'error'; td.error = describe(e); console.error('Over time data failed to load', e); })
    .finally(() => { clearTimeout(slowTimer); td.slow = false; });
  return inflight;
}
export function retryTimeData() { forget('station_daily.json'); forget('hex/weights_r5.json'); inflight = null; return loadTimeData(); }

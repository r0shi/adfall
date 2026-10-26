// Where the user is looking: pin A and pin B with the stations reaching them. The URL hash is written by url.svelte.js.
import { stations } from './data.js';
import { covering, reverse, marketOf } from './geo.js';

export const loc = $state({ p: null, label: '', market: '', found: [], all: [] });
export const locB = $state({ p: null, label: '', market: '', found: [] });
const at = (a, b) => a && b && a[0] === b[0] && a[1] === b[1];   // state proxies break identity checks

export async function ready() {
  if (!loc.all.length) loc.all = await stations();
  return loc.all;
}
export async function setLocation(p, label = '') {
  await ready();
  loc.p = p; loc.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  loc.found = covering(loc.all, p); loc.market = marketOf(loc.found, p);
  if (!label) reverse(p).then(n => { if (n && at(loc.p, p)) loc.label = n; });
}
export async function setLocationB(p, label = '') {
  await ready();
  locB.p = p; locB.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  locB.found = covering(loc.all, p); locB.market = marketOf(locB.found, p);
  if (!label) reverse(p).then(n => { if (n && at(locB.p, p)) locB.label = n; });
}
export function clearB() { locB.p = null; locB.found = []; locB.label = ''; locB.market = ''; }
export function clearA() { loc.p = null; loc.found = []; loc.label = ''; loc.market = ''; }

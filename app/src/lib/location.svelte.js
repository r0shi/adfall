// Where the user is looking: pin A and pin B with the stations reaching them. The URL hash is written by url.svelte.js.
import { stations } from './data.js';
import { covering, reverse } from './geo.js';

export const loc = $state({ p: null, label: '', found: [], all: [] });
export const locB = $state({ p: null, label: '', found: [] });

export async function ready() {
  if (!loc.all.length) loc.all = await stations();
  return loc.all;
}
export async function setLocation(p, label = '') {
  await ready();
  loc.p = p; loc.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  loc.found = covering(loc.all, p);
  if (!label) reverse(p).then(n => { if (n && loc.p === p) loc.label = n; });
}
export async function setLocationB(p, label = '') {
  await ready();
  locB.p = p; locB.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  locB.found = covering(loc.all, p);
  if (!label) reverse(p).then(n => { if (n && locB.p === p) locB.label = n; });
}
export function clearB() { locB.p = null; locB.found = []; locB.label = ''; }
export function clearA() { loc.p = null; loc.found = []; loc.label = ''; }

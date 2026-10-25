// The one piece of shared UI state: where the user is looking. Synced to the URL hash (#lat,lon).
import { stations } from './data.js';
import { covering, reverse } from './geo.js';
import { replaceState } from '$app/navigation';

export const loc = $state({ p: null, label: '', found: [], all: [] });
export const locB = $state({ p: null, label: '', found: [] });

export async function ready() {
  if (!loc.all.length) loc.all = await stations();
  return loc.all;
}
function syncHash() {
  const f = (p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`;
  const h = loc.p ? '#' + f(loc.p) + (locB.p ? ';' + f(locB.p) : '') : '';
  try { replaceState(`${location.pathname}${h}`, {}); } catch { /* before router init */ }
}
export async function setLocation(p, label = '') {
  await ready();
  loc.p = p; loc.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  loc.found = covering(loc.all, p);
  syncHash();
  if (!label) reverse(p).then(n => { if (n && loc.p === p) loc.label = n; });
}
export async function setLocationB(p, label = '') {
  await ready();
  locB.p = p; locB.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  locB.found = covering(loc.all, p);
  syncHash();
  if (!label) reverse(p).then(n => { if (n && locB.p === p) locB.label = n; });
}
export function clearB() { locB.p = null; locB.found = []; locB.label = ''; syncHash(); }
export function clearA() { loc.p = null; loc.found = []; loc.label = ''; syncHash(); }
export async function fromHash() {
  const h = typeof location !== 'undefined' && location.hash.slice(1).match(/^(-?[\d.]+),(-?[\d.]+)(?:;(-?[\d.]+),(-?[\d.]+))?$/);
  if (h && !loc.p) { await setLocation([+h[1], +h[2]]); if (h[3]) await setLocationB([+h[3], +h[4]]); }
  else await ready();
}

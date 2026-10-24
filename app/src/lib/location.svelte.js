// The one piece of shared UI state: where the user is looking. Synced to the URL hash (#lat,lon).
import { stations } from './data.js';
import { covering, reverse } from './geo.js';
import { replaceState } from '$app/navigation';

export const loc = $state({ p: null, label: '', found: [], all: [] });

export async function ready() {
  if (!loc.all.length) loc.all = await stations();
  return loc.all;
}
export async function setLocation(p, label = '') {
  await ready();
  loc.p = p; loc.label = label || `${p[0].toFixed(3)}, ${p[1].toFixed(3)}`;
  loc.found = covering(loc.all, p);
  try { replaceState(`${location.pathname}#${p[0].toFixed(4)},${p[1].toFixed(4)}`, {}); } catch { /* before router init */ }
  if (!label) reverse(p).then(n => { if (n && loc.p === p) loc.label = n; });
}
export async function fromHash() {
  const h = typeof location !== 'undefined' && location.hash.slice(1).match(/^(-?[\d.]+),(-?[\d.]+)$/);
  if (h && !loc.p) await setLocation([+h[1], +h[2]]);
  else await ready();
}

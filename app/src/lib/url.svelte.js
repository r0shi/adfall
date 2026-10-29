// View state <-> URL hash. The site is static, so everything someone needs to see your view lives in the hash:
// pins, map layer, open tab, newscast night, timeline position, color mode and camera. Every discrete change is a
// history entry (Back and Forward act as undo and redo); continuous ones (panning, playback, scrubbing) replace
// the current entry so they do not flood history. The layout wires this to SvelteKit's shallow routing.
import { loc, locB, ready, setLocation, setLocationB, clearA, clearB } from './location.svelte.js';
import { tl } from './time.svelte.js';
import { view, setColorBy } from './color.svelte.js';

export const ui = $state({
  layer: 'booked', tab: 'stations', tabB: 'stations',     // home map layer ('coverage' = none, contours only) and the open popover tabs
  newsDay: null,                                          // Newscasts tab night (null = tonight)
  cam: null,                                              // [zoom, lat, lon] as last reported by the map
  camRequest: null, camApplied: 0,                        // a camera the URL asked for; when the map applied it
  path: '/'
});

// Map layers the hash may name: Over time, the tile metrics (hexlayers.js METRICS) and the comparisons (difflayer.js
// DIFFS); 'none' (or the older 'coverage') is no layer. No layer= means Money, the default; anything unknown falls back to it.
const LAYERS = new Set(['coverage', 'animate', 'booked', 'pp', 'spots', 'ps', 'stations', 'party', 'bi', 'wk']);

const f4 = (p) => `${(+p[0]).toFixed(4)},${(+p[1]).toFixed(4)}`;

/** The hash (without '#') for the current view. shared=true keeps only what makes sense on every page. */
export function serialize({ shared = false } = {}) {
  const q = [];
  if (loc.p) q.push('p=' + f4(loc.p));
  if (locB.p) q.push('b=' + f4(locB.p));
  if (view.by !== 'party') q.push('color=' + view.by);
  if (shared) return q.join('&');
  if (ui.layer !== 'booked') q.push('layer=' + (ui.layer === 'coverage' ? 'none' : ui.layer));
  if (loc.p && ui.tab !== 'stations') q.push('tab=' + ui.tab);
  if (locB.p && ui.tabB !== 'stations') q.push('tabb=' + ui.tabB);
  if (ui.newsDay && (ui.tab === 'news' || ui.tabB === 'news')) q.push('night=' + ui.newsDay);
  if (tl.day && (ui.layer === 'animate' || ui.layer === 'wk' || ui.path === '/time')) {
    q.push('day=' + tl.day);
    if (tl.window !== 'week') q.push('win=' + tl.window);
    if (tl.metric !== 'booked') q.push('metric=' + tl.metric);
    if (!tl.trails) q.push('trails=0');
  }
  if (ui.cam) q.push('map=' + [ui.cam[0].toFixed(2), ui.cam[1].toFixed(3), ui.cam[2].toFixed(3)].join('/'));
  return q.join('&');
}

export function parse(hash) {
  const h = (hash || '').replace(/^#/, '');
  const legacy = h.match(/^(-?[\d.]+),(-?[\d.]+)(?:;(-?[\d.]+),(-?[\d.]+))?$/);   // the old #lat,lon;latB,lonB links
  if (legacy) return { p: [+legacy[1], +legacy[2]], b: legacy[3] ? [+legacy[3], +legacy[4]] : null };
  const o = {};
  for (const part of h.split('&')) { if (!part) continue; const i = part.indexOf('='); o[i < 0 ? part : part.slice(0, i)] = i < 0 ? '' : decodeURIComponent(part.slice(i + 1)); }
  const pt = (s) => { const m = (s || '').match(/^(-?[\d.]+),(-?[\d.]+)$/); return m ? [+m[1], +m[2]] : null; };
  const cam = o.map ? o.map.split('/').map(Number) : null;
  return { p: pt(o.p), b: pt(o.b), layer: o.layer, tab: o.tab, tabb: o.tabb, night: o.night, day: o.day, win: o.win, metric: o.metric, trails: o.trails, color: o.color,
           map: cam && cam.length === 3 && cam.every(Number.isFinite) ? cam : null };
}

const samePt = (a, b) => (!a && !b) || (a && b && a[0] === b[0] && a[1] === b[1]);

/** Make the app show the view a hash describes. Empty hash = the default view (pins cleared, viewer's own color mode kept). */
export async function apply(hash) {
  const s = parse(hash);
  await ready();
  if (s.map) ui.camRequest = s.map;            // before the pins, so the pin effect does not fly the camera away from it
  if (!samePt(s.p, loc.p)) { if (s.p) await setLocation(s.p); else if (loc.p) clearA(); }
  if (!samePt(s.b, locB.p)) { if (s.b) await setLocationB(s.b); else if (locB.p) clearB(); }
  ui.layer = s.layer === 'none' ? 'coverage' : LAYERS.has(s.layer) ? s.layer : 'booked'; ui.tab = s.tab || 'stations'; ui.tabB = s.tabb || 'stations';
  ui.newsDay = s.night || null;
  if (s.day) tl.day = s.day;
  if (s.win) tl.window = s.win; else if (s.day) tl.window = 'week';
  if (s.metric) tl.metric = s.metric; else if (s.day) tl.metric = 'booked';
  if (s.day) tl.trails = s.trails !== '0';
  if (hash && hash !== '#') setColorBy(s.color === 'category' ? 'category' : 'party');
}

/** push for a deliberate change, replace for panning, playback and rapid scrubbing. */
let lastDayChange = 0;
export function historyMode(prevHash, nextHash) {
  if (prevHash == null) return 'replace';
  const a = parse(prevHash), b = parse(nextHash);
  const changed = Object.keys({ ...a, ...b }).filter(k => JSON.stringify(a[k] ?? null) !== JSON.stringify(b[k] ?? null));
  if (!changed.length || changed.every(k => k === 'map')) return 'replace';
  if (changed.every(k => k === 'map' || k === 'day')) {
    const now = Date.now(), rapid = tl.playing || now - lastDayChange < 1500; lastDayChange = now;
    return rapid ? 'replace' : 'push';
  }
  return 'push';
}

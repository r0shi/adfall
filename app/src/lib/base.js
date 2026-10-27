// Where the data lives. Locally everything is /data (web/data, served by vite.config.js in dev and app/serve.mjs for
// the build). Published, the app shell is on Cloudflare Pages and the data on R2 under two bases, baked in at build
// time by scripts/publish.sh:
//   VITE_DATA_SET   the coherent set a view reads together (aggregates, hex weights, tiles, marts, methods), under a
//                   prefix named by the export's build id, never modified after upload; a page from build N always
//                   reads set N, so a publish is atomic from the browser's side
//   VITE_DATA_LIVE  self-contained per-entity pages (one creative, buyer, station, spend file or newscast night) and
//                   the hourly health file, synced in place; a page one export newer than the set is harmless
const SET = (import.meta.env.VITE_DATA_SET || '/data').replace(/\/$/, '');
const LIVE = (import.meta.env.VITE_DATA_LIVE || '/data').replace(/\/$/, '');
const LIVE_RE = /^(creatives\/id\/|buyers\/|stations\/|spend\/\d|newscasts\/(?!index\.json)|health\.json$)/;
export const isLive = (path) => LIVE_RE.test(path);
export const dataUrl = (path) => `${isLive(path) ? LIVE : SET}/${path}`;
/** An absolute URL for protocols that cannot resolve a path (pmtiles://). */
export const dataAbs = (path) => { const u = dataUrl(path); return /^https?:/.test(u) ? u : location.origin + u; };
/** A versioned file on a remote base never changes under its URL, so the browser cache can be trusted outright. */
export const cacheMode = (path) => (!isLive(path) && /^https?:/.test(SET)) ? 'default' : 'no-cache';

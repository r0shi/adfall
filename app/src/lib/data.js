// Static data access. Everything is a JSON artifact exported by ingest/export.py under /data.
const cache = new Map();
const wait = (ms) => new Promise(r => setTimeout(r, ms));
// Every data file is revalidated on load (cache: 'no-cache' makes the browser send a conditional request), so a tab
// never keeps a heuristically cached file from before an export. A failed fetch is retried once and never memoized, so
// a later call can succeed; a 404 is permanent until the next export and is remembered to spare the request.
async function fetchJson(path, attempt = 0) {
  const again = (why) => attempt < 1 ? wait(900).then(() => fetchJson(path, attempt + 1)) : Promise.reject(new Error(`${path}: ${why}`));
  let r;
  try { r = await fetch(`/data/${path}`, { cache: 'no-cache' }); } catch (e) { return again(e.message || 'network error'); }
  if (r.status === 404) throw Object.assign(new Error(`${path}: HTTP 404`), { permanent: true });
  if (!r.ok) return again(`HTTP ${r.status}`);
  try { return await r.json(); } catch { return again('incomplete JSON (an export may be in progress)'); }
}
export function get(path) {
  if (!cache.has(path)) { const p = fetchJson(path); cache.set(path, p); p.catch(e => { if (!e?.permanent) cache.delete(path); }); }
  return cache.get(path);
}
export function forget(path) { if (path) cache.delete(path); else cache.clear(); }
export const stations = () => get('stations.json').then(d => d.stations);
export const spendIndex = () => get('spend/index.json').catch(() => ({ stations: {}, year: new Date().getFullYear() }));
export const stationSpend = (fac) => get(`spend/${fac}.json`);
export const buyers = () => get('buyers.json').then(d => d.buyers);
export const creatives = () => get('creatives/all.json').then(d => d.creatives);
export const stationDaily = () => get('station_daily.json');
export const weeklyHex = () => get('hex/weekly_r5.json');
export const hexWeights = (res = 5) => get(`hex/weights_r${res}.json`);
export const hexTotal = (res = 5) => get(`hex/total_r${res}.json`);
export const build = () => get('build.json').catch(() => ({}));

export const CATS = { 'Federal': 'var(--federal)', 'State': 'var(--state)', 'Local': 'var(--local)', 'Non-Candidate Issue Ads': 'var(--issue)', 'Other': 'var(--other)' };
export const CAT_RGB = { 'Federal': [47, 51, 149], 'State': [98, 102, 208], 'Local': [154, 157, 230], 'Non-Candidate Issue Ads': [91, 108, 255], 'Other': [154, 160, 173] };
export const catShort = (c) => c === 'Non-Candidate Issue Ads' ? 'Issue' : c;
export const usd = (v) => v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
export const num = (v) => new Intl.NumberFormat('en-US').format(Math.round(v));

const CAT_CODE = { 'Federal': 'federal', 'State': 'state', 'Local': 'local', 'Non-Candidate Issue Ads': 'issue', 'Other': 'other' };
export const slugOf = (category, name) => `${CAT_CODE[category] || 'other'}-` + name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
export const buyerDetail = (slug) => get(`buyers/${slug}.json`);
export const stationDetail = (fac) => get(`stations/${fac}.json`);
export const newscastIndex = () => get('newscasts/index.json').then(d => new Set(d.facs)).catch(() => new Set());   // stations with news buys (ingest.newscasts)
export const newscasts = (fac) => get(`newscasts/${fac}.json`);   // blocks, scheduled lines, confirmed airings
export const PLOT_COLORS = { domain: Object.keys(CATS), range: ['#2f3395', '#6266d0', '#9a9de6', '#ad8c2e', '#9aa0ad'] };

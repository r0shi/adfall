// Static data access. Everything is a JSON artifact exported by ingest/export.py under /data.
const cache = new Map();
export async function get(path) {
  if (!cache.has(path)) cache.set(path, fetch(`/data/${path}`).then(r => { if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.json(); }));
  return cache.get(path);
}
export const stations = () => get('stations.json').then(d => d.stations);
export const spendIndex = () => get('spend/index.json').catch(() => ({ stations: {}, year: new Date().getFullYear() }));
export const stationSpend = (fac) => get(`spend/${fac}.json`);
export const buyers = () => get('buyers.json').then(d => d.buyers);
export const creatives = () => get('creatives/all.json').then(d => d.creatives);
export const stationDaily = () => get('station_daily.json');
export const weeklyHex = () => get('hex/weekly_r5.json');
export const hexTotal = (res = 5) => get(`hex/total_r${res}.json`);
export const build = () => get('build.json').catch(() => ({}));

export const CATS = { 'Federal': 'var(--federal)', 'State': 'var(--state)', 'Local': 'var(--local)', 'Non-Candidate Issue Ads': 'var(--issue)', 'Other': 'var(--other)' };
export const CAT_RGB = { 'Federal': [200, 16, 46], 'State': [232, 116, 59], 'Local': [242, 183, 5], 'Non-Candidate Issue Ads': [91, 108, 255], 'Other': [154, 160, 173] };
export const catShort = (c) => c === 'Non-Candidate Issue Ads' ? 'Issue' : c;
export const usd = (v) => v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
export const num = (v) => new Intl.NumberFormat('en-US').format(Math.round(v));

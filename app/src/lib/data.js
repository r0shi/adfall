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

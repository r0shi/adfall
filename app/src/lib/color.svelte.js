// One switch for what color means on buyer-level marks (tiles, bars, dots, catbars, charts): the buyer's
// category (office level) or its party. Party colors are blue and red and appear only in party mode and in
// the D − R map layer, so nothing in category mode can be mistaken for a partisan signal: the office levels
// are one indigo ramp (federal darkest), issue groups are sand, and unknowns are gray.
import { CATS, catShort, PLOT_COLORS, buyers, slugOf } from './data.js';
import { partyLabel } from './here.js';

export const view = $state({ by: 'party' });
try { const v = localStorage.getItem('colorBy'); if (v === 'party' || v === 'category') view.by = v; } catch {}
export function setColorBy(v) { view.by = v; try { localStorage.setItem('colorBy', v); } catch {} }

export const PARTIES = { Democratic: 'var(--dem)', Republican: 'var(--rep)', 'Issue groups': 'var(--issue)', Independent: 'var(--other)', Nonpartisan: 'var(--other)', Unknown: 'var(--unknown)' };
export const PARTY_PLOT = { domain: Object.keys(PARTIES), range: ['#2f6fd6', '#c8102e', '#ad8c2e', '#9aa0ad', '#9aa0ad', '#6f7380'] };
export const PARTY_NOTE = 'Party is what the station typed on the candidate\'s NAB form; issue groups carry none, and blank forms are "unknown".';

// party by buyer slug, for records that carry a slug but no party (creatives); filled once from buyers.json
const partyBySlug = $state(new Map());
let loading = null;
export function loadParties() {
  if (loading) return loading;
  loading = buyers().then(bs => { const m = new Map(); for (const b of bs) m.set(b.slug, partyLabel(b.party, b.category)); for (const [k, v] of m) partyBySlug.set(k, v); }).catch(() => {});
  return loading;
}

export function partyOf(x) {
  if (!x) return 'Unknown';
  if (x.partyLabel) return x.partyLabel;
  if (x.party !== undefined && x.party !== null) return partyLabel(x.party, x.category);
  const sl = x.slug || (x.buyer && x.category ? slugOf(x.category, x.buyer) : null);
  if (sl && partyBySlug.has(sl)) return partyBySlug.get(sl);
  return x.category === 'Non-Candidate Issue Ads' ? 'Issue groups' : 'Unknown';
}
/** The key a mark is colored by under the current mode. */
export function keyOf(x) { return view.by === 'party' ? partyOf(x) : (x?.category || 'Other'); }
/** CSS color for a buyer-like record ({category, party?, slug?}) under the current mode. */
export function colorOf(x) { return view.by === 'party' ? (PARTIES[partyOf(x)] || PARTIES.Unknown) : (CATS[x?.category] || CATS.Other); }
/** Plot color scale for the current mode; marks use fill: keyOf. */
export function plotColor() { return view.by === 'party' ? PARTY_PLOT : PLOT_COLORS; }
/** Legend entries [label, color] for the current mode. */
export function legendEntries({ other = false, mode = null } = {}) {
  return (mode || view.by) === 'party' ? Object.entries(PARTIES).filter(([k]) => other || (k !== 'Nonpartisan' && k !== 'Independent'))
                             : Object.entries(CATS).filter(([k]) => other || k !== 'Other').map(([k, c]) => [catShort(k), c]);
}
/** Share bars from a station spend record: [[label, value, color]] by category or party, noise folded into Unknown. */
export function shares(spend) {
  if (!spend) return [];
  const m = new Map();
  if (view.by === 'party') { for (const [k, v] of Object.entries(spend.by_party || {})) { const key = PARTIES[k] ? k : 'Unknown'; m.set(key, (m.get(key) || 0) + v); } }
  else for (const [k, v] of Object.entries(spend.by_category || {})) m.set(k, (m.get(k) || 0) + v);
  return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => [view.by === 'party' ? k : catShort(k), v, view.by === 'party' ? PARTIES[k] : (CATS[k] || CATS.Other)]);
}

// Aggregations scoped to the stations reaching a place, from the per-station spend files.
import { stationSpend, creatives, slugOf } from './data.js';

export async function buyersHere(found, all, idx = null) {
  const facs = idx ? found.filter(s => idx.stations[s.fac]) : found;   // only stations that have a spend file (avoids 404s)
  const files = (await Promise.all(facs.map(s => stationSpend(s.fac).catch(() => null)))).filter(Boolean);
  const m = new Map();
  for (const d of files) for (const b of d.buyers) {
    const k = `${b.category}|${b.name}`;
    const e = m.get(k) || { id: k, slug: b.slug || slugOf(b.category, b.name), name: b.name, category: b.category, kind: b.kind, party: b.party, office: b.office,
                            booked: 0, invoiced: 0, orders: 0, spots_aired: 0, stations: 0, facs: [], agencies: new Set(), groups: new Set() };
    e.booked += b.gross; e.invoiced += b.invoiced; e.orders += b.orders; e.spots_aired += b.spots_aired || 0; e.stations += 1; e.facs.push(d.fac);
    for (const a of b.agencies || []) e.agencies.add(a);
    const st = all.find(s => s.fac === d.fac); if (st?.licensee) e.groups.add(st.licensee);
    m.set(k, e);
  }
  return [...m.values()].map(e => ({ ...e, agencies: [...e.agencies], groups: [...e.groups] })).sort((a, b) => b.booked - a.booked);
}

export async function creativesHere(found) {
  const facs = new Set(found.map(s => s.fac));
  return (await creatives()).map(c => ({ ...c, airings: Object.entries(c.facs).reduce((t, [f, n]) => t + (facs.has(+f) ? n : 0), 0) }))
    .filter(c => c.airings > 0).sort((a, b) => b.airings - a.airings);
}

/** Pivot a buyer list by a key: 'buyer' | 'party' | 'category' | 'agency' | 'kind' */
export function pivot(buyers, by) {
  if (by === 'buyer') return buyers.map(b => ({ key: b.name, slug: b.slug, category: b.category, booked: b.booked, invoiced: b.invoiced, n: 1 }));
  const m = new Map();
  for (const b of buyers) {
    const keys = by === 'agency' ? (b.agencies.length ? b.agencies : ['(no agency)']) : [by === 'party' ? (b.party || (b.category === 'Non-Candidate Issue Ads' ? 'Issue groups' : 'Unknown')) : by === 'kind' ? (b.kind || 'unknown') : b.category];
    for (const k of keys) { const e = m.get(k) || { key: k, category: b.category, booked: 0, invoiced: 0, n: 0 }; e.booked += b.booked; e.invoiced += b.invoiced; e.n += 1; m.set(k, e); }
  }
  return [...m.values()].sort((a, b) => b.booked - a.booked);
}

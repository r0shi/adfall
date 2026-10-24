// Coverage lookup (point in contour polygons), distance, geocoding.
export const inBbox = (p, b) => p[0] >= b[0] && p[1] >= b[1] && p[0] <= b[2] && p[1] <= b[3];
export function inPoly(p, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i], [yj, xj] = poly[j];
    if ((yi > p[0]) !== (yj > p[0]) && p[1] < (xj - xi) * (p[0] - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
export function miles(a, b) {
  const R = 3958.8, d = Math.PI / 180, dLat = (b[0] - a[0]) * d, dLon = (b[1] - a[1]) * d;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * d) * Math.cos(b[0] * d) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
export function covering(stations, p) {
  const rank = s => (s.svc === 'DTV' ? 0 : 1);
  return stations.filter(s => inBbox(p, s.bbox) && s.polys.some(poly => inPoly(p, poly)))
    .sort((a, b) => rank(a) - rank(b) || miles(p, a.tx) - miles(p, b.tx));
}
export const toGeoJSON = (found) => ({
  type: 'FeatureCollection',
  features: found.map(s => ({ type: 'Feature', properties: { fac: s.fac, call: s.call },
    geometry: { type: 'MultiPolygon', coordinates: s.polys.map(poly => [poly.map(([lat, lon]) => [lon, lat])]) } }))
});
// Place lookup: a static Census index (ZIPs + places) answers ZIPs and city names with no external
// service; street addresses fall back to Nominatim. Reverse lookup = nearest indexed place.
const NOM = 'https://nominatim.openstreetmap.org';
let placesP = null;
const places = () => placesP ||= fetch('/data/places.json').then(r => r.json());
const STATE_NAMES = { alabama: 'AL', alaska: 'AK', arizona: 'AZ', arkansas: 'AR', california: 'CA', colorado: 'CO', connecticut: 'CT', delaware: 'DE', florida: 'FL', georgia: 'GA', hawaii: 'HI', idaho: 'ID', illinois: 'IL', indiana: 'IN', iowa: 'IA', kansas: 'KS', kentucky: 'KY', louisiana: 'LA', maine: 'ME', maryland: 'MD', massachusetts: 'MA', michigan: 'MI', minnesota: 'MN', mississippi: 'MS', missouri: 'MO', montana: 'MT', nebraska: 'NE', nevada: 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', ohio: 'OH', oklahoma: 'OK', oregon: 'OR', pennsylvania: 'PA', 'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', tennessee: 'TN', texas: 'TX', utah: 'UT', vermont: 'VT', virginia: 'VA', washington: 'WA', 'west virginia': 'WV', wisconsin: 'WI', wyoming: 'WY', 'district of columbia': 'DC' };
export async function geocode(q) {
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (m) return { p: [+m[1], +m[2]], label: '' };
  const idx = await places();
  const z = q.match(/^\s*(\d{5})(?:-\d{4})?\s*$/);
  if (z && idx.zips[z[1]]) return { p: idx.zips[z[1]], label: `ZIP ${z[1]}, ${nearestPlace(idx, idx.zips[z[1]])}` };
  const parts = q.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  if (parts.length && parts.length <= 2 && !/\d/.test(parts[0])) {
    const name = parts[0];
    let st = parts[1] ? (parts[1].length === 2 ? parts[1].toUpperCase() : STATE_NAMES[parts[1]]) : null;
    const hits = idx.places.filter(p => p[0].toLowerCase() === name && (!st || p[1] === st));
    const hit = hits[0] || (!st ? idx.places.find(p => p[0].toLowerCase().startsWith(name)) : null);
    if (hit) return { p: [hit[2], hit[3]], label: `${hit[0]}, ${hit[1]}` };
  }
  const j = await fetch(`${NOM}/search?format=jsonv2&countrycodes=us&limit=1&q=${encodeURIComponent(q)}`).then(r => r.json());
  if (!j.length) throw new Error('not found');
  return { p: [+j[0].lat, +j[0].lon], label: j[0].display_name.split(',').slice(0, 3).join(',') };
}
function nearestPlace(idx, p) {
  let best = null, bd = Infinity;
  for (const pl of idx.places) {
    const d = (pl[2] - p[0]) ** 2 + ((pl[3] - p[1]) * Math.cos(p[0] * Math.PI / 180)) ** 2;
    if (d < bd) { bd = d; best = pl; }
  }
  return best && Math.sqrt(bd) * 69 < 40 ? `${best[0]}, ${best[1]}` : '';
}
export async function reverse(p) {
  try { return nearestPlace(await places(), p); } catch { return ''; }
}

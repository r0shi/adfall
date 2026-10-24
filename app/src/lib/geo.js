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
const NOM = 'https://nominatim.openstreetmap.org';
export async function geocode(q) {
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (m) return { p: [+m[1], +m[2]], label: '' };
  const j = await fetch(`${NOM}/search?format=jsonv2&countrycodes=us&limit=1&q=${encodeURIComponent(q)}`).then(r => r.json());
  if (!j.length) throw new Error('not found');
  return { p: [+j[0].lat, +j[0].lon], label: j[0].display_name.split(',').slice(0, 3).join(',') };
}
export async function reverse(p) {
  try {
    const a = (await fetch(`${NOM}/reverse?format=jsonv2&zoom=10&lat=${p[0]}&lon=${p[1]}`).then(r => r.json())).address || {};
    return [a.city || a.town || a.village || a.county, a.state].filter(Boolean).join(', ');
  } catch { return ''; }
}

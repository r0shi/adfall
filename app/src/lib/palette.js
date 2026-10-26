// One palette for every map layer and chart. The weather lean lives here and in app.css, nowhere else:
// adfall (money and spots landing on a place) is radar's rain ramp, pale mint to deep teal (one hue family, no party); differences
// are warm against cool; party keeps its conventional blue and red; the pins are ink and amber.
// Steps were checked with the dataviz validator: the ramp is lightness-monotone within one hue family.

/** Sequential ramp for magnitude: t in [0,1] -> [r, g, b, a]. sqrt is applied by callers. */
export const RAMP = [
  [0.00, [185, 230, 211, 0.15]],
  [0.20, [127, 207, 174, 0.45]],
  [0.45, [69, 176, 138, 0.70]],
  [0.70, [35, 143, 112, 0.85]],
  [0.88, [22, 107, 94, 0.90]],
  [1.00, [15, 74, 70, 0.94]]
];
export function ramp(t) {
  t = Math.max(0, Math.min(1, t || 0));
  for (let i = 1; i < RAMP.length; i++) {
    const [t1, c1] = RAMP[i];
    if (t <= t1) { const [t0, c0] = RAMP[i - 1]; const u = (t - t0) / (t1 - t0); return c0.map((v, k) => v + (c1[k] - v) * u); }
  }
  return RAMP[RAMP.length - 1][1].slice();
}
/** deck.gl color: [r, g, b, alpha 0-255]. */
export function rampRGBA(t) { const [r, g, b, a] = ramp(t); return [Math.round(r), Math.round(g), Math.round(b), Math.round(255 * a)]; }
/** CSS gradient for legends, same stops. */
export const rampCss = `linear-gradient(90deg, ${RAMP.map(([t, [r, g, b, a]]) => `rgba(${r},${g},${b},${Math.max(a, 0.35)}) ${Math.round(100 * t)}%`).join(', ')})`;
/** MapLibre fill-color expression over a tile property, sqrt-scaled to max. */
export function rampExpr(prop, max) {
  const expr = ['interpolate', ['linear'], ['sqrt', ['min', 1, ['/', ['to-number', ['get', prop]], max || 1]]]];
  for (const [t, [r, g, b, a]] of RAMP) expr.push(t, `rgba(${r},${g},${b},${a})`);
  return expr;
}

/** Diverging pairs. Party keeps convention (blue, red, gray midpoint); everything else is warm (rising, still to air) against cool. */
export const WARM = [217, 112, 15];
export const COOL = [26, 143, 160];
export const DEM = [47, 111, 214];
export const REP = [200, 16, 46];
export const MID = [158, 160, 168];
const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
/** Party value-by-alpha color: hue from the Democratic share (gray at an even split), alpha in [0,1] from the amount. */
export function partyRGBA(share, alpha) { const c = share >= 0.5 ? mix(MID, DEM, (share - 0.5) * 2) : mix(MID, REP, (0.5 - share) * 2); return [c[0], c[1], c[2], Math.round(255 * Math.max(0, Math.min(1, alpha)))]; }

/** Pins and contours: A is ink, B is amber, on the light basemap. */
export const PIN_A = '#1b1b1f';
export const PIN_B = '#c96a0a';

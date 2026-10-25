// One palette for every map layer and chart. The weather lean lives here and in app.css, nowhere else:
// adfall (money and spots landing on a place) is a precipitation ramp, pale sky to deep indigo; differences
// are warm against cool; party keeps its conventional blue and red; the pins are ink and amber.
// Steps were checked with the dataviz validator: the ramp is lightness-monotone within one hue family.

/** Sequential ramp for magnitude: t in [0,1] -> [r, g, b, a]. sqrt is applied by callers. */
export const RAMP = [
  [0.00, [201, 221, 243, 0.15]],
  [0.20, [143, 187, 233, 0.45]],
  [0.45, [83, 144, 220, 0.70]],
  [0.70, [47, 95, 198, 0.85]],
  [0.88, [43, 56, 170, 0.90]],
  [1.00, [44, 31, 128, 0.94]]
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

/** Diverging pairs. Party keeps convention; everything else is warm (rising, still to air) against cool. */
export const WARM = [217, 112, 15];
export const COOL = [26, 143, 160];
export const DEM = [47, 111, 214];
export const REP = [200, 16, 46];

/** Pins and contours: A is ink, B is amber, on the light basemap. */
export const PIN_A = '#1b1b1f';
export const PIN_B = '#c96a0a';

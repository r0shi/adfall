// PMTiles hex density layers (from ingest/tiles.py) on a MapLibre map, shared by the home map and /map.
import { rampExpr } from './palette.js';
export const METRICS = {
  booked: ['Money reaching here', 'Booked $ spread over each station\'s coverage by population', 'booked'],
  pp: ['$ per person', 'Booked $ divided by people in the cell', 'pp'],
  spots: ['Spots aired', 'Invoiced airings reaching the cell, population-weighted', 'spots'],
  ps: ['$ per spot', 'Booked $ per aired spot', 'ps'],
  stations: ['Stations with buys', 'How many covering stations have political orders', 'stations']
};
export function installHexLayers(map, beforeId = 'contours-fill') {
  for (const r of [5, 7]) {
    if (map.getSource(`hex${r}`)) continue;
    map.addSource(`hex${r}`, { type: 'vector', url: `pmtiles://${location.origin}/data/tiles/hex${r}.pmtiles` });
    map.addLayer({ id: `hex${r}-fill`, type: 'fill', source: `hex${r}`, 'source-layer': `hex${r}`, layout: { visibility: 'none' }, paint: { 'fill-color': '#2f5fc6', 'fill-opacity': 0.85 } }, beforeId);
  }
}
export function fillExpr(prop, max) { return rampExpr(prop, max); }
/** Show one hex layer (res 5 or 7) colored by metric, or hide both. meta = tiles/meta.json. */
export function setHexLayer(map, { visible, res, metric, meta }) {
  for (const r of [5, 7]) {
    if (!map.getLayer(`hex${r}-fill`)) continue;
    const on = visible && r === res;
    map.setLayoutProperty(`hex${r}-fill`, 'visibility', on ? 'visible' : 'none');
    if (on && meta) map.setPaintProperty(`hex${r}-fill`, 'fill-color', fillExpr(METRICS[metric][2], meta.hex?.[r]?.max?.[METRICS[metric][2]]));
  }
}

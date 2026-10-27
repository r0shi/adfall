// PMTiles hex density layers (from ingest/tiles.py) on a MapLibre map, shared by the home map and /map.
import { rampExpr } from './palette.js';
import { dataAbs } from './base.js';
export const METRICS = {
  booked: ['Money reaching here', 'Booked $ spread over each station\'s coverage by population', 'booked'],
  pp: ['$ per person', 'Booked $ divided by people in the cell', 'pp'],
  spots: ['Spots aired', 'Invoiced airings reaching the cell, population-weighted', 'spots'],
  ps: ['$ per spot', 'Booked $ per aired spot', 'ps'],
  stations: ['Stations with buys', 'How many covering stations have political orders', 'stations']
};
export const RES = [5, 7, 8];
/** Resolution for a zoom: 5 nationally, 7 from 6.3, 8 from 9.3 where its layer exists (tiles/meta.json lists it). */
export function resForZoom(zoom, meta) { return zoom >= 9.3 && meta?.hex?.[8] ? 8 : zoom >= 6.3 ? 7 : 5; }
/** Res 8 exists only where people are dense enough (ingest.geo "metro"), so it is drawn as a mosaic: hex8 on top of the
 *  hex7 cells that have no res-8 children (fine != 1). These are the layers to draw and to query for a resolution. */
export function layersFor(res) { return res === 8 ? ['hex8-fill', 'hex7-fill'] : [`hex${res}-fill`]; }
export function filterFor(layerRes, res) { return layerRes === 7 && res === 8 ? ['!=', ['get', 'fine'], 1] : null; }
export function installHexLayers(map, beforeId = 'contours-fill') {
  for (const r of RES) {
    if (map.getSource(`hex${r}`)) continue;
    map.addSource(`hex${r}`, { type: 'vector', url: `pmtiles://${dataAbs(`tiles/hex${r}.pmtiles`)}` });
    map.addLayer({ id: `hex${r}-fill`, type: 'fill', source: `hex${r}`, 'source-layer': `hex${r}`, layout: { visibility: 'none' }, paint: { 'fill-color': '#238f70', 'fill-opacity': 0.85 } }, beforeId);
  }
}
export function fillExpr(prop, max) { return rampExpr(prop, max); }
/** Show the layers for one resolution (5, 7 or 8) colored by metric, or hide all. meta = tiles/meta.json. */
export function setHexLayer(map, { visible, res, metric, meta }) {
  const prop = METRICS[metric][2], want = layersFor(res);
  for (const r of RES) {
    const id = `hex${r}-fill`;
    if (!map.getLayer(id)) continue;
    const on = visible && want.includes(id);
    map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    if (!on) continue;
    map.setFilter(id, filterFor(r, res));
    if (meta) map.setPaintProperty(id, 'fill-color', fillExpr(prop, meta.hex?.[r]?.max?.[prop]));
  }
}

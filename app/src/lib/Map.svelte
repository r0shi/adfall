<script>
  // MapLibre map with an optional deck.gl overlay. Children layers are driven through the `api` prop callback.
  import { onMount } from 'svelte';
  import maplibregl from 'maplibre-gl';
  import 'maplibre-gl/dist/maplibre-gl.css';
  let { center = [-97.5, 39.5], zoom = 3.6, onclick = null, onready = null, style = 'https://tiles.openfreemap.org/styles/positron' } = $props();
  let el, map, overlay;
  onMount(() => {
    map = new maplibregl.Map({ container: el, style, center, zoom, attributionControl: { compact: true } });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('click', e => onclick && onclick([e.lngLat.lat, e.lngLat.lng]));
    map.on('load', () => {
      map.addSource('contours', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'contours-fill', type: 'fill', source: 'contours', paint: { 'fill-color': '#c8102e', 'fill-opacity': 0.06 } });
      map.addLayer({ id: 'contours-line', type: 'line', source: 'contours', paint: { 'line-color': '#c8102e', 'line-opacity': 0.55, 'line-width': 1 } });
      map.addLayer({ id: 'contours-hot', type: 'line', source: 'contours', filter: ['==', 'fac', -1], paint: { 'line-color': '#c8102e', 'line-width': 3 } });
      map.addSource('marker', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'marker', type: 'circle', source: 'marker', paint: { 'circle-radius': 7, 'circle-color': '#1b1b1f', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
      onready && onready(api);
    });
    return () => map.remove();
  });
  const api = {
    get map() { return map; },
    setContours(geojson) { map.getSource('contours')?.setData(geojson); },
    highlight(fac) { map.getLayer('contours-hot') && map.setFilter('contours-hot', ['==', 'fac', fac ?? -1]); },
    setMarker(p) { map.getSource('marker')?.setData({ type: 'FeatureCollection', features: p ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [p[1], p[0]] } }] : [] }); },
    flyTo(p, z) { map.flyTo({ center: [p[1], p[0]], zoom: z ?? Math.max(map.getZoom(), 7), duration: 600 }); },
    fitBounds(b) { map.fitBounds([[b[1], b[0]], [b[3], b[2]]], { padding: 30, duration: 600 }); },
    async setDeckLayers(layers, getTooltip = null) {
      if (!overlay) { const { MapboxOverlay } = await import('@deck.gl/mapbox'); overlay = new MapboxOverlay({ interleaved: false, layers, getTooltip }); map.addControl(overlay); }
      else overlay.setProps({ layers, getTooltip });
    },
    onZoom(fn) { map.on('zoomend', () => fn(map.getZoom())); }
  };
</script>
<div class="map" bind:this={el}></div>

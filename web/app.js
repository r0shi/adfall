/* TV Wormhole prototype: location -> FCC contour station list -> NewsON + political files */
(() => {
  const $ = (s) => document.querySelector(s);
  const list = $("#list"), where = $("#where"), results = $("#results"),
        status = $("#status"), hint = $("#hint"), onlyStream = $("#onlystream");

  const map = L.map("map", { zoomControl: true }).setView([39.5, -97.5], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  let marker = null, stations = [], polysById = new Map(), current = null;

  // ---------- geometry ----------
  const inBbox = (p, b) => p[0] >= b[0] && p[1] >= b[1] && p[0] <= b[2] && p[1] <= b[3];
  function inPoly(p, poly) {              // ray casting, poly = [[lat,lon],...]
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [yi, xi] = poly[i], [yj, xj] = poly[j];
      if ((yi > p[0]) !== (yj > p[0]) && p[1] < (xj - xi) * (p[0] - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function miles(a, b) {
    const R = 3958.8, d = Math.PI / 180;
    const dLat = (b[0] - a[0]) * d, dLon = (b[1] - a[1]) * d;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * d) * Math.cos(b[0] * d) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const covering = (p) => stations.filter(s => inBbox(p, s.bbox) && s.polys.some(poly => inPoly(p, poly)));

  // ---------- rendering ----------
  const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function card(s, p) {
    const dist = Math.round(miles(p, s.tx));
    const stream = s.newson
      ? `<a class="live" href="https://www.newson.us/stationDetails/${esc(s.newson.id)}" target="_blank" rel="noopener">▶ Watch on NewsON</a>`
      : `<a href="https://duckduckgo.com/?q=${encodeURIComponent(`${s.call} ${s.city} ${s.state} live stream news`)}" target="_blank" rel="noopener">Find stream</a>`;
    return `<li class="st" data-id="${s.fac}">
      <div class="top"><span class="call">${esc(s.call)}</span><span class="chan">ch ${esc(s.vchan && s.vchan !== "-" ? s.vchan : s.rf)}</span>
        <span class="svc">${s.svc === "DCA" ? "Class A" : "Full power"}</span></div>
      <div class="sub">${esc(s.city)}, ${esc(s.state)} · ${esc(s.licensee)} · transmitter ${dist} mi away</div>
      <div class="links">${stream}
        <a href="https://publicfiles.fcc.gov/tv-profile/${esc(s.slug)}/political-files" target="_blank" rel="noopener">Political ad buys</a>
        <a href="https://publicfiles.fcc.gov/tv-profile/${esc(s.slug)}" target="_blank" rel="noopener">FCC file</a>
      </div></li>`;
  }
  function draw(p, found) {
    layer.clearLayers(); polysById.clear();
    found.forEach(s => {
      const pl = L.polygon(s.polys, { color: "#c8102e", weight: 1, opacity: .55, fillOpacity: .06 }).addTo(layer);
      pl.bindTooltip(`${s.call} · ${s.city}, ${s.state}`, { sticky: true });
      pl.on("mouseover", () => hot(s.fac, true)).on("mouseout", () => hot(s.fac, false));
      polysById.set(s.fac, pl);
    });
    if (marker) marker.remove();
    marker = L.marker(p).addTo(map);
  }
  function hot(id, on) {
    const pl = polysById.get(id); if (pl) pl.setStyle({ weight: on ? 3 : 1, fillOpacity: on ? .18 : .06 });
    const li = list.querySelector(`[data-id="${id}"]`); if (li) li.classList.toggle("hot", on);
  }
  function render() {
    if (!current) return;
    const { p, label, found } = current;
    const shown = onlyStream.checked ? found.filter(s => s.newson) : found;
    where.innerHTML = `${esc(label)}<small>${found.length} station${found.length === 1 ? "" : "s"} predicted to reach ${p[0].toFixed(3)}, ${p[1].toFixed(3)}` +
      (found.length ? ` · ${found.filter(s => s.newson).length} with a live stream` : "") + `</small>`;
    list.innerHTML = shown.map(s => card(s, p)).join("") || `<li class="hint">Nothing here. Try a spot nearer a city.</li>`;
    results.hidden = false;
  }

  // ---------- lookup ----------
  async function lookup(p, label) {
    if (!stations.length) { setHint("Station data is still loading…", true); return; }
    const rank = s => (s.svc === "DTV" ? 0 : 1);          // full power first, then nearest transmitter
    const found = covering(p).sort((a, b) => rank(a) - rank(b) || miles(p, a.tx) - miles(p, b.tx));
    current = { p, label: label || `${p[0].toFixed(4)}, ${p[1].toFixed(4)}`, found };
    draw(p, found); render();
    location.hash = `${p[0].toFixed(4)},${p[1].toFixed(4)}`;
    if (map.getZoom() < 7) map.setView(p, 7); else map.panTo(p);
    if (!label) reverse(p).then(n => { if (n && current && current.p === p) { current.label = n; render(); } });
  }
  const setHint = (t, err) => { hint.textContent = t; hint.classList.toggle("err", !!err); };
  const NOM = "https://nominatim.openstreetmap.org";
  async function geocode(q) {
    const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (m) return { p: [+m[1], +m[2]], label: "" };
    const r = await fetch(`${NOM}/search?format=jsonv2&countrycodes=us&limit=1&q=${encodeURIComponent(q)}`);
    const j = await r.json(); if (!j.length) throw new Error("not found");
    return { p: [+j[0].lat, +j[0].lon], label: j[0].display_name.split(",").slice(0, 3).join(",") };
  }
  async function reverse(p) {
    try {
      const r = await fetch(`${NOM}/reverse?format=jsonv2&zoom=10&lat=${p[0]}&lon=${p[1]}`);
      const a = (await r.json()).address || {};
      return [a.city || a.town || a.village || a.county, a.state].filter(Boolean).join(", ");
    } catch { return ""; }
  }

  // ---------- events ----------
  $("#search").addEventListener("submit", async (e) => {
    e.preventDefault(); const q = $("#q").value.trim(); if (!q) return;
    setHint("Looking up…");
    try { const g = await geocode(q); setHint("…or click anywhere on the map."); lookup(g.p, g.label); }
    catch { setHint(`Couldn't find "${q}".`, true); }
  });
  $("#locate").addEventListener("click", () => {
    if (!navigator.geolocation) return setHint("Geolocation unavailable.", true);
    navigator.geolocation.getCurrentPosition(
      pos => lookup([pos.coords.latitude, pos.coords.longitude]),
      () => setHint("Location permission denied.", true));
  });
  map.on("click", (e) => lookup([e.latlng.lat, e.latlng.lng]));
  onlyStream.addEventListener("change", render);
  list.addEventListener("mouseover", e => { const li = e.target.closest(".st"); if (li) hot(+li.dataset.id, true); });
  list.addEventListener("mouseout", e => { const li = e.target.closest(".st"); if (li) hot(+li.dataset.id, false); });
  list.addEventListener("click", e => {
    if (e.target.closest("a")) return;
    const li = e.target.closest(".st"); const pl = li && polysById.get(+li.dataset.id);
    if (pl) map.fitBounds(pl.getBounds(), { padding: [20, 20] });
  });

  // ---------- data ----------
  fetch("data/stations.json").then(r => r.json()).then(d => {
    stations = d.stations;
    status.textContent = `${stations.length} licensed stations · ${stations.filter(s => s.newson).length} with NewsON streams · contours as of ${d.generated}`;
    const h = location.hash.slice(1).match(/^(-?[\d.]+),(-?[\d.]+)$/);
    if (h) lookup([+h[1], +h[2]]);
  }).catch(() => { status.textContent = "Failed to load station data."; });
})();

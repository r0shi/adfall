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
  let spendIndex = {}, spendYear = new Date().getFullYear();
  const CATS = { "Federal": "#c8102e", "State": "#e8743b", "Local": "#f2b705", "Non-Candidate Issue Ads": "#5b6cff" };
  const usd = (v) => v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
  function catBar(byCat, total) {
    if (!total) return "";
    return `<span class="catbar">${Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([c, v]) =>
      `<i style="width:${(100 * v / total).toFixed(1)}%;background:${CATS[c] || "#999"}" title="${esc(c)}: ${usd(v)}"></i>`).join("")}</span>`;
  }

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
      ${spendLine(s)}
      <div class="links">${stream}
        <a href="https://publicfiles.fcc.gov/tv-profile/${esc(s.slug)}/political-files" target="_blank" rel="noopener">Political ad buys</a>
        <a href="https://publicfiles.fcc.gov/tv-profile/${esc(s.slug)}" target="_blank" rel="noopener">FCC file</a>
      </div></li>`;
  }
  function spendLine(s) {
    const sp = spendIndex[s.fac];
    if (!sp) return "";
    if (!sp.total) return `<div class="spend none">No political buys filed for ${spendYear}</div>`;
    return `<div class="spend" data-fac="${s.fac}"><div class="row"><b>${usd(sp.total)}</b> political ad buys · ${sp.buyers} buyers · ${spendYear}
      <span class="more">buyers ▾</span></div>${catBar(sp.by_category, sp.total)}<div class="buyers" hidden></div></div>`;
  }
  async function toggleBuyers(box) {
    const list = box.querySelector(".buyers");
    if (!list.hidden) { list.hidden = true; return; }
    if (!list.dataset.loaded) {
      list.innerHTML = "Loading…";
      const d = await fetch(`data/spend/${box.dataset.fac}.json`).then(r => r.json());
      const max = d.buyers[0]?.gross || 1;
      list.innerHTML = d.buyers.slice(0, 25).map(b => `<div class="buyer">
          <div class="bname"><span class="dot" style="background:${CATS[b.category] || "#999"}"></span>${esc(b.name)}
            <span class="amt">${usd(b.gross)}</span></div>
          <div class="bar"><i style="width:${(100 * b.gross / max).toFixed(1)}%;background:${CATS[b.category] || "#999"}"></i></div>
          <div class="bmeta">${b.orders} order${b.orders === 1 ? "" : "s"}${b.invoiced ? ` · ${usd(b.invoiced)} invoiced` : ""}${b.ad_ids ? ` · ${b.ad_ids} creative${b.ad_ids === 1 ? "" : "s"}` : ""}${b.agencies.length ? ` · via ${esc(b.agencies.slice(0, 2).join(", "))}` : ""}</div>
        </div>`).join("") + (d.buyers.length > 25 ? `<div class="bmeta">…and ${d.buyers.length - 25} more</div>` : "") +
        `<div class="bmeta legend">${Object.entries(CATS).map(([c, col]) => `<span class="dot" style="background:${col}"></span>${c === "Non-Candidate Issue Ads" ? "Issue" : c}`).join(" ")} · ${d.docs} documents, ${Math.round(100 * (d.parse_status.ok || 0) / d.docs)}% parsed</div>`;
      list.dataset.loaded = 1;
    }
    list.hidden = false;
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
    const covered = found.filter(s => spendIndex[s.fac]);
    const spendTotal = covered.reduce((t, s) => t + spendIndex[s.fac].total, 0);
    where.innerHTML = `${esc(label)}<small>${found.length} station${found.length === 1 ? "" : "s"} predicted to reach ${p[0].toFixed(3)}, ${p[1].toFixed(3)}` +
      (found.length ? ` · ${found.filter(s => s.newson).length} with a live stream` : "") + `</small>` +
      (covered.length ? `<div class="rollup"><b>${usd(spendTotal)}</b> in ${spendYear} political TV buys filed by ${covered.length} of these stations${catBar(covered.reduce((m, s) => { for (const [c, v] of Object.entries(spendIndex[s.fac].by_category)) m[c] = (m[c] || 0) + v; return m; }, {}), spendTotal)}</div>` : "");
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
    const sp = e.target.closest(".spend[data-fac]");
    if (sp) { e.stopPropagation(); toggleBuyers(sp); return; }
    const li = e.target.closest(".st"); const pl = li && polysById.get(+li.dataset.id);
    if (pl) map.fitBounds(pl.getBounds(), { padding: [20, 20] });
  });

  // ---------- data ----------
  fetch("data/spend/index.json").then(r => r.ok ? r.json() : null).then(d => {
    if (d) { spendIndex = d.stations; spendYear = d.year; if (current) render(); }
  }).catch(() => {});
  fetch("data/stations.json").then(r => r.json()).then(d => {
    stations = d.stations;
    status.textContent = `${stations.length} licensed stations · ${stations.filter(s => s.newson).length} with NewsON streams · contours as of ${d.generated}`;
    const h = location.hash.slice(1).match(/^(-?[\d.]+),(-?[\d.]+)$/);
    if (h) lookup([+h[1], +h[2]]);
  }).catch(() => { status.textContent = "Failed to load station data."; });
})();

// DuckDB-WASM over the Parquet marts, in the browser. Loaded lazily by the Explore view. The engine itself (two
// 35-40 MB WASM binaries) comes from jsDelivr at the version pinned in package.json rather than from this site: it
// kept the build over Cloudflare Pages' 25 MB file limit, and the Explore view already needs the network for the marts.
import { dataUrl } from './base.js';

export const TABLES = ['station', 'buyer', 'buyer_station', 'station_total', 'station_daily', 'spend_daily', 'hex', 'station_hex', 'hex_total', 'creative', 'spot', 'hex_weekly_r5', 'order_', 'agency'];
const EAGER = ['station', 'buyer', 'buyer_station', 'station_total', 'station_daily'];   // small; the rest load when a query names them
let dbP = null, progress = () => {};
const loaded = new Set();

export function open(onProgress = () => {}) {
  progress = onProgress;
  return dbP ||= (async () => {
    const duckdb = await import('@duckdb/duckdb-wasm');
    const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
    const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }));   // a cross-origin worker needs a same-origin shim
    const worker = new Worker(workerUrl);
    const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    const conn = await db.connect();
    const h = { db, conn };
    for (const t of EAGER) await ensure(h, t);
    progress('');
    return h;
  })();
}

async function ensure(h, t) {
  if (loaded.has(t)) return;
  progress(`loading ${t}…`);
  try {
    const r = await fetch(dataUrl(`marts/${t}.parquet`));
    if (!r.ok) throw new Error(`${r.status}`);
    await h.db.registerFileBuffer(`${t}.parquet`, new Uint8Array(await r.arrayBuffer()));
    await h.conn.query(`CREATE VIEW ${t} AS SELECT * FROM read_parquet('${t}.parquet')`);
    loaded.add(t);
  } catch (e) { console.warn('mart missing', t, e); }
  progress('');
}

export async function query(sql) {
  const h = await open();
  for (const t of TABLES) if (new RegExp(`\\b${t}\\b`, 'i').test(sql)) await ensure(h, t);
  const res = await h.conn.query(sql);
  const cols = res.schema.fields.map(f => ({ name: f.name, type: String(f.type) }));
  const rows = res.toArray().map(r => { const o = r.toJSON(); for (const k in o) { const v = o[k]; if (typeof v === 'bigint') o[k] = Number(v); else if (v && typeof v === 'object' && 'toString' in v && !(v instanceof Date)) o[k] = String(v); } return o; });
  return { cols, rows };
}

export const PRESETS = [
  ['Top buyers', `SELECT b.canonical_name AS buyer, b.category, b.state,
       round(sum(bs.booked)) AS booked, round(sum(bs.invoiced)) AS invoiced, sum(bs.spots_aired) AS spots_aired
FROM buyer_station bs JOIN buyer b USING (buyer_id)
GROUP BY 1,2,3 ORDER BY booked DESC LIMIT 30`],
  ['Spend by station group', `SELECT s.station_group, count(DISTINCT s.facility_id) AS stations, round(sum(st.booked)) AS booked, round(sum(st.invoiced)) AS invoiced
FROM station_total st JOIN station s USING (facility_id)
WHERE st.booked > 0 GROUP BY 1 ORDER BY booked DESC`],
  ['Booked by week and category', `SELECT date_trunc('week', sd.day)::date AS week, b.category, round(sum(sd.booked)) AS booked
FROM spend_daily sd JOIN buyer b USING (buyer_id)
GROUP BY 1,2 ORDER BY 1,2`],
  ['Spend per state', `SELECT s.state, count(DISTINCT s.facility_id) AS stations, round(sum(st.booked)) AS booked, round(sum(st.booked)/1e6, 1) AS booked_m
FROM station_total st JOIN station s USING (facility_id) WHERE st.booked > 0 GROUP BY 1 ORDER BY booked DESC`],
  ['$ per person, densest cells', `SELECT h3, res, round(booked) AS booked, round(pop) AS pop, round(booked/pop, 2) AS per_person, stations_with_buys
FROM hex_total WHERE res = 5 AND pop > 20000 ORDER BY per_person DESC LIMIT 25`],
  ['Most-aired creatives', `SELECT sp.ad_id, b.canonical_name AS buyer, count(*) AS airings, min(sp.aired_on) AS first, max(sp.aired_on) AS last, count(DISTINCT sp.facility_id) AS stations
FROM spot sp LEFT JOIN buyer b USING (buyer_id) GROUP BY 1,2 ORDER BY airings DESC LIMIT 30`],
  ['Airings by hour of day', `SELECT ((CAST(regexp_extract(aired_time, '^\\s*(\\d{1,2}):', 1) AS INTEGER) % 12) + CASE WHEN aired_time ILIKE '%PM' THEN 12 ELSE 0 END) AS hour, count(*) AS airings
FROM spot WHERE aired_time IS NOT NULL GROUP BY 1 ORDER BY 1`],
  ['Party split per state (federal candidates)', `SELECT s.state, b.party, round(sum(bs.booked)) AS booked
FROM buyer_station bs JOIN buyer b USING (buyer_id) JOIN station s USING (facility_id)
WHERE b.category = 'federal' AND b.party IN ('Democratic','Republican') GROUP BY 1,2 ORDER BY 1,2`],
  ['Agencies by billings', `SELECT a.name AS agency, count(*) AS orders, round(sum(o.gross)) AS booked
FROM order_ o JOIN agency a USING (agency_id) GROUP BY 1 ORDER BY booked DESC LIMIT 25`]
];

// Pivot builder: dimensions + measure + filters -> SQL over the marts (DuckDB-WASM), plus a client-side pivot.
const PARTY_SQL = `CASE WHEN b.category = 'issue' THEN 'Issue groups'
  WHEN lower(b.party) SIMILAR TO '(d|dem|demo|democrat|democratic)%' THEN 'Democratic'
  WHEN lower(b.party) SIMILAR TO '(r|rep|repub|republican|gop)%' THEN 'Republican'
  WHEN lower(b.party) SIMILAR TO '%non.?partisan%' THEN 'Nonpartisan'
  WHEN lower(b.party) SIMILAR TO '(i|ind|independent)%' THEN 'Independent'
  WHEN b.party IS NULL OR b.party = '' THEN 'Unknown' ELSE b.party END`;

export const DIMS = {
  buyer: { label: 'Buyer', sql: 'b.canonical_name', needs: 'b' },
  party: { label: 'Party', sql: PARTY_SQL, needs: 'b' },
  category: { label: 'Category', sql: 'b.category', needs: 'b' },
  state: { label: 'State', sql: 's.state', needs: 's' },
  group: { label: 'Station group', sql: 's.station_group', needs: 's' },
  station: { label: 'Station', sql: 's.call', needs: 's' },
  agency: { label: 'Agency', sql: 'a.name', needs: 'a', source: 'orders' },
  week: { label: 'Week', sql: "date_trunc('week', sd.day)::date", needs: 'sd', source: 'daily' },
  month: { label: 'Month', sql: "date_trunc('month', sd.day)::date", needs: 'sd', source: 'daily' }
};
export const MEASURES = {
  booked: { label: 'Booked $', bs: 'round(sum(bs.booked))', daily: 'round(sum(sd.booked))', orders: "round(sum(o.gross) FILTER (WHERE o.status = 'booked'))" },
  invoiced: { label: 'Invoiced $', bs: 'round(sum(bs.invoiced))', daily: 'round(sum(sd.invoiced))', orders: null },
  orders: { label: 'Orders', bs: 'sum(bs.orders)', daily: null, orders: 'count(*)' },
  spots: { label: 'Spots aired', bs: 'sum(bs.spots_aired)', daily: 'sum(sd.spots_aired)', orders: null },
  creatives: { label: 'Creatives', bs: 'sum(bs.creatives)', daily: null, orders: null },
  buyers: { label: 'Distinct buyers', bs: 'count(DISTINCT b.buyer_id)', daily: 'count(DISTINCT sd.buyer_id)', orders: 'count(DISTINCT o.buyer_id)' }
};

export function buildSQL({ rows, cols = null, measure = 'booked', filters = {}, limit = 40 }) {
  const dims = [rows, cols].filter(Boolean).map(k => DIMS[k]);
  const source = dims.some(d => d.source === 'daily') || filters.from || filters.to ? 'daily' : dims.some(d => d.source === 'orders') ? 'orders' : 'bs';
  const m = MEASURES[measure][source] || MEASURES.booked[source] || 'round(sum(bs.booked))';
  const from = source === 'daily' ? 'spend_daily sd JOIN buyer b USING (buyer_id) JOIN station s USING (facility_id)'
             : source === 'orders' ? 'order_ o JOIN buyer b USING (buyer_id) JOIN station s USING (facility_id) LEFT JOIN agency a USING (agency_id)'
             : 'buyer_station bs JOIN buyer b USING (buyer_id) JOIN station s USING (facility_id)';
  const where = [];
  if (filters.category?.length) where.push(`b.category IN (${filters.category.map(c => `'${c}'`).join(',')})`);
  if (filters.party?.length) where.push(`(${PARTY_SQL}) IN (${filters.party.map(c => `'${c}'`).join(',')})`);
  if (filters.state?.length) where.push(`s.state IN (${filters.state.map(c => `'${c.toUpperCase()}'`).join(',')})`);
  if (filters.text) where.push(`lower(b.canonical_name) LIKE '%${filters.text.toLowerCase().replace(/'/g, "''")}%'`);
  if (source === 'daily' && filters.from) where.push(`sd.day >= DATE '${filters.from}'`);
  if (source === 'daily' && filters.to) where.push(`sd.day <= DATE '${filters.to}'`);
  const sel = dims.map((d, i) => `${d.sql} AS ${i === 0 ? rows : cols}`);
  const grp = dims.map((_, i) => i + 1).join(',');
  return `SELECT ${sel.join(',\n       ')},\n       ${m} AS ${measure}\nFROM ${from}${where.length ? '\nWHERE ' + where.join('\n  AND ') : ''}\nGROUP BY ${grp}\nORDER BY ${measure} DESC NULLS LAST${cols ? '' : `\nLIMIT ${limit}`}`;
}

/** Long rows -> { rowKeys, colKeys, cell(r,c), rowTotals } limited to the top N rows and M columns by total. */
export function pivotRows(data, rows, cols, measure, nRows = 30, nCols = 12) {
  const rt = new Map(), ct = new Map(), cell = new Map();
  for (const d of data) {
    const r = String(d[rows]), c = cols ? String(d[cols]) : '_', v = Number(d[measure]) || 0;
    rt.set(r, (rt.get(r) || 0) + v); ct.set(c, (ct.get(c) || 0) + v); cell.set(r + '\u0000' + c, v);
  }
  const timeLike = cols === 'week' || cols === 'month';
  const rowKeys = [...rt.entries()].sort((a, b) => b[1] - a[1]).slice(0, nRows).map(e => e[0]);
  const colKeys = timeLike ? [...ct.keys()].sort() : [...ct.entries()].sort((a, b) => b[1] - a[1]).slice(0, nCols).map(e => e[0]);
  return { rowKeys, colKeys, rowTotals: rt, colTotals: ct, cell: (r, c) => cell.get(r + '\u0000' + c) || 0 };
}

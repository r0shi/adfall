-- Census tracts carry population into cells (ingest.geo): ACS 2019-2023 5-year totals (B01003),
-- rescaled inside each county so the tracts sum to the county's 2024 estimate. County stays for names.
CREATE TABLE IF NOT EXISTS tract (
  geoid    text PRIMARY KEY,                  -- 11-digit state+county+tract
  state    text,
  county   text,                              -- 5-digit county geoid
  name     text,
  pop_acs  integer,                           -- ACS 5-year estimate as published
  pop      double precision,                  -- rescaled to the county's 2024 estimate
  aland    bigint,                            -- land area, m² (Census)
  geom     geometry(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS tract_gix ON tract USING gist (geom);
CREATE INDEX IF NOT EXISTS tract_county ON tract (county);

-- hex_total: resolution 8 exists only in metro cells, so a station's spread at res 8 is normalised by its
-- complete res-7 population reach. Dollars per person is then the same at res 7 and res 8, and res-8 cells
-- hold only the share of a station's money that reaches their people; the rural remainder is at res 7 only.
DROP MATERIALIZED VIEW IF EXISTS hex_total;
CREATE MATERIALIZED VIEW hex_total AS
WITH w AS (
  SELECT sh.facility_id, sh.h3, sh.res, COALESCE(h.pop, 0) * sh.coverage_share AS w
  FROM station_hex sh JOIN hex h USING (h3)
),
reach AS (SELECT facility_id, res, SUM(w) AS wsum FROM w GROUP BY 1, 2),
norm AS (
  SELECT r.facility_id, r.res, COALESCE(b.wsum, r.wsum) AS wsum
  FROM reach r LEFT JOIN reach b ON b.facility_id = r.facility_id AND b.res = 7 AND r.res = 8
)
SELECT w.h3, w.res,
       COALESCE(SUM(st.booked * w.w / NULLIF(n.wsum, 0)), 0) AS booked,
       COALESCE(SUM(st.invoiced * w.w / NULLIF(n.wsum, 0)), 0) AS invoiced,
       COALESCE(SUM(st.spots_aired * w.w / NULLIF(n.wsum, 0)), 0) AS spots_aired,
       COUNT(DISTINCT w.facility_id) FILTER (WHERE st.booked > 0) AS stations_with_buys,
       COALESCE(MAX(h.pop), 0) AS pop
FROM w JOIN norm n USING (facility_id, res) JOIN station_total st USING (facility_id) JOIN hex h ON h.h3 = w.h3
GROUP BY 1, 2;
CREATE UNIQUE INDEX hex_total_pk ON hex_total (h3);
CREATE INDEX hex_total_res ON hex_total (res);

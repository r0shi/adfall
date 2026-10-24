-- hex × day is too large at fine resolutions (cells × days × stations). Keep time at station
-- grain (station_daily) and space at cell grain (hex_total); the export step composes frames
-- (e.g. weekly at res 5) from the two, so adding a resolution never changes the marts.
DROP MATERIALIZED VIEW IF EXISTS hex_daily;

CREATE MATERIALIZED VIEW IF NOT EXISTS station_daily AS
SELECT facility_id, day, SUM(booked) booked, SUM(invoiced) invoiced, SUM(spots_booked) spots_booked,
       SUM(spots_aired) spots_aired, SUM(aired_value) aired_value
FROM spend_daily GROUP BY 1,2;
CREATE UNIQUE INDEX IF NOT EXISTS station_daily_pk ON station_daily (facility_id, day);

CREATE MATERIALIZED VIEW IF NOT EXISTS station_total AS
SELECT s.facility_id,
       COALESCE((SELECT SUM(gross) FROM order_ o WHERE o.facility_id = s.facility_id AND o.status = 'booked'), 0) AS booked,
       COALESCE((SELECT SUM(gross) FROM invoice i WHERE i.facility_id = s.facility_id), 0) AS invoiced,
       COALESCE((SELECT COUNT(*) FROM spot sp WHERE sp.facility_id = s.facility_id), 0) AS spots_aired,
       COALESCE((SELECT COUNT(DISTINCT ad_id) FROM spot sp WHERE sp.facility_id = s.facility_id), 0) AS creatives,
       (SELECT COUNT(DISTINCT buyer_id) FROM order_ o WHERE o.facility_id = s.facility_id) AS buyers,
       (SELECT COUNT(*) FROM opif_file f WHERE f.facility_id = s.facility_id AND f.deleted_at IS NULL) AS docs
FROM station s;
CREATE UNIQUE INDEX IF NOT EXISTS station_total_pk ON station_total (facility_id);

-- Money and ads reaching each cell: station totals spread across covered cells by population share.
CREATE MATERIALIZED VIEW IF NOT EXISTS hex_total AS
WITH weights AS (
  SELECT sh.facility_id, sh.h3, sh.res, h.pop * sh.coverage_share AS w,
         SUM(h.pop * sh.coverage_share) OVER (PARTITION BY sh.facility_id, sh.res) AS wsum
  FROM station_hex sh JOIN hex h USING (h3)
)
SELECT w.h3, w.res,
       SUM(st.booked * w.w / NULLIF(w.wsum, 0)) AS booked,
       SUM(st.invoiced * w.w / NULLIF(w.wsum, 0)) AS invoiced,
       SUM(st.spots_aired * w.w / NULLIF(w.wsum, 0)) AS spots_aired,
       COUNT(DISTINCT w.facility_id) FILTER (WHERE st.booked > 0) AS stations_with_buys,
       MAX(h.pop) AS pop
FROM weights w JOIN station_total st USING (facility_id) JOIN hex h ON h.h3 = w.h3
GROUP BY 1,2;
CREATE UNIQUE INDEX IF NOT EXISTS hex_total_pk ON hex_total (h3);

-- cells with no population (water, outside the US) must get 0, not NULL
DROP MATERIALIZED VIEW IF EXISTS hex_total;
CREATE MATERIALIZED VIEW hex_total AS
WITH weights AS (
  SELECT sh.facility_id, sh.h3, sh.res, COALESCE(h.pop, 0) * sh.coverage_share AS w,
         SUM(COALESCE(h.pop, 0) * sh.coverage_share) OVER (PARTITION BY sh.facility_id, sh.res) AS wsum
  FROM station_hex sh JOIN hex h USING (h3)
)
SELECT w.h3, w.res,
       COALESCE(SUM(st.booked * w.w / NULLIF(w.wsum, 0)), 0) AS booked,
       COALESCE(SUM(st.invoiced * w.w / NULLIF(w.wsum, 0)), 0) AS invoiced,
       COALESCE(SUM(st.spots_aired * w.w / NULLIF(w.wsum, 0)), 0) AS spots_aired,
       COUNT(DISTINCT w.facility_id) FILTER (WHERE st.booked > 0) AS stations_with_buys,
       COALESCE(MAX(h.pop), 0) AS pop
FROM weights w JOIN station_total st USING (facility_id) JOIN hex h ON h.h3 = w.h3
GROUP BY 1,2;
CREATE UNIQUE INDEX hex_total_pk ON hex_total (h3);

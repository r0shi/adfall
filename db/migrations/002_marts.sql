-- Derived marts. Refreshed by `ingest.pg marts` after every ingest.

-- Booked dollars on calendar days: finest grain available per order.
--   order lines with dates  -> spread each line's amount evenly over its date range
--   else                    -> spread the order's gross evenly over its flight window
CREATE MATERIALIZED VIEW IF NOT EXISTS spend_daily AS
WITH line_days AS (
  SELECT o.facility_id, o.buyer_id, o.order_id, d::date AS day,
         l.amount / GREATEST(1, (l.end_date - l.start_date) + 1) AS booked,
         l.spots::numeric / GREATEST(1, (l.end_date - l.start_date) + 1) AS spots_booked
  FROM order_ o JOIN order_line l USING (order_id)
  CROSS JOIN LATERAL generate_series(l.start_date, l.end_date, interval '1 day') d
  WHERE o.status = 'booked' AND l.start_date IS NOT NULL AND l.end_date IS NOT NULL AND l.amount IS NOT NULL
), has_lines AS (SELECT DISTINCT order_id FROM line_days),
flight_days AS (
  SELECT o.facility_id, o.buyer_id, o.order_id, d::date AS day,
         o.gross / GREATEST(1, (o.flight_end - o.flight_start) + 1) AS booked,
         o.spots::numeric / GREATEST(1, (o.flight_end - o.flight_start) + 1) AS spots_booked
  FROM order_ o
  CROSS JOIN LATERAL generate_series(o.flight_start, o.flight_end, interval '1 day') d
  WHERE o.status = 'booked' AND o.gross IS NOT NULL AND o.flight_start IS NOT NULL AND o.flight_end IS NOT NULL
    AND o.order_id NOT IN (SELECT order_id FROM has_lines)
), booked AS (
  SELECT facility_id, buyer_id, day, SUM(booked) booked, SUM(spots_booked) spots_booked, 'lines' AS grain FROM line_days GROUP BY 1,2,3
  UNION ALL
  SELECT facility_id, buyer_id, day, SUM(booked), SUM(spots_booked), 'flight' FROM flight_days GROUP BY 1,2,3
), invoiced AS (
  SELECT i.facility_id, i.buyer_id, d::date AS day,
         SUM(i.gross / GREATEST(1, (i.period_end - i.period_start) + 1)) AS invoiced
  FROM invoice i CROSS JOIN LATERAL generate_series(i.period_start, i.period_end, interval '1 day') d
  WHERE i.gross IS NOT NULL AND i.period_start IS NOT NULL AND i.period_end IS NOT NULL
  GROUP BY 1,2,3
), aired AS (
  SELECT facility_id, buyer_id, aired_on AS day, COUNT(*) AS spots_aired, SUM(rate) AS aired_value
  FROM spot GROUP BY 1,2,3
)
SELECT COALESCE(b.facility_id, i.facility_id, a.facility_id) AS facility_id,
       COALESCE(b.buyer_id, i.buyer_id, a.buyer_id) AS buyer_id,
       COALESCE(b.day, i.day, a.day) AS day,
       COALESCE(SUM(b.booked), 0) AS booked,
       COALESCE(SUM(b.spots_booked), 0) AS spots_booked,
       COALESCE(MAX(i.invoiced), 0) AS invoiced,
       COALESCE(MAX(a.spots_aired), 0) AS spots_aired,
       COALESCE(MAX(a.aired_value), 0) AS aired_value
FROM booked b
FULL OUTER JOIN invoiced i ON i.facility_id = b.facility_id AND i.buyer_id IS NOT DISTINCT FROM b.buyer_id AND i.day = b.day
FULL OUTER JOIN aired a ON a.facility_id = COALESCE(b.facility_id, i.facility_id) AND a.buyer_id IS NOT DISTINCT FROM COALESCE(b.buyer_id, i.buyer_id) AND a.day = COALESCE(b.day, i.day)
GROUP BY 1,2,3;
CREATE UNIQUE INDEX IF NOT EXISTS spend_daily_pk ON spend_daily (facility_id, buyer_id, day);

-- Money and ads on hex cells: each station's daily totals spread over the cells its contour
-- covers, in proportion to population inside the cell. A dollar reaching several stations'
-- cells is counted in each ("money reaching this place").
CREATE MATERIALIZED VIEW IF NOT EXISTS hex_daily AS
WITH station_day AS (
  SELECT facility_id, day, SUM(booked) booked, SUM(invoiced) invoiced, SUM(spots_booked) spots_booked, SUM(spots_aired) spots_aired
  FROM spend_daily GROUP BY 1,2
), weights AS (
  SELECT sh.facility_id, sh.h3, sh.res, h.pop * sh.coverage_share AS w,
         SUM(h.pop * sh.coverage_share) OVER (PARTITION BY sh.facility_id, sh.res) AS wsum
  FROM station_hex sh JOIN hex h USING (h3)
)
SELECT w.h3, w.res, sd.day,
       SUM(sd.booked * w.w / NULLIF(w.wsum, 0)) AS booked,
       SUM(sd.invoiced * w.w / NULLIF(w.wsum, 0)) AS invoiced,
       SUM(sd.spots_booked * w.w / NULLIF(w.wsum, 0)) AS spots_booked,
       SUM(sd.spots_aired * w.w / NULLIF(w.wsum, 0)) AS spots_aired,
       MAX(h.pop) AS pop
FROM station_day sd JOIN weights w USING (facility_id) JOIN hex h ON h.h3 = w.h3
GROUP BY 1,2,3;
CREATE UNIQUE INDEX IF NOT EXISTS hex_daily_pk ON hex_daily (h3, day);
CREATE INDEX IF NOT EXISTS hex_daily_res_day ON hex_daily (res, day);

CREATE MATERIALIZED VIEW IF NOT EXISTS buyer_station AS
SELECT o.facility_id, o.buyer_id,
       SUM(o.gross) FILTER (WHERE o.status = 'booked') AS booked,
       COUNT(*) FILTER (WHERE o.status = 'booked') AS orders,
       (SELECT COALESCE(SUM(i.gross), 0) FROM invoice i WHERE i.facility_id = o.facility_id AND i.buyer_id = o.buyer_id) AS invoiced,
       (SELECT COUNT(*) FROM spot s WHERE s.facility_id = o.facility_id AND s.buyer_id = o.buyer_id) AS spots_aired,
       (SELECT COUNT(DISTINCT s.ad_id) FROM spot s WHERE s.facility_id = o.facility_id AND s.buyer_id = o.buyer_id) AS creatives
FROM order_ o GROUP BY 1,2;
CREATE UNIQUE INDEX IF NOT EXISTS buyer_station_pk ON buyer_station (facility_id, buyer_id);

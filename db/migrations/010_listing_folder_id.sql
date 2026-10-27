-- The FCC year folder id per station-year, so the daily count check needs one API call per station, not two.
ALTER TABLE opif_listing ADD COLUMN IF NOT EXISTS folder_id text;
ALTER TABLE opif_listing ADD COLUMN IF NOT EXISTS checked_at timestamptz;   -- last time the FCC file_count was compared with ours

-- Stage run history, mirrored from the SQLite pipeline_run table by load_pg so export_methods can report it.
CREATE TABLE IF NOT EXISTS pipeline_run (
  run_id    integer PRIMARY KEY,
  stage     text NOT NULL,
  batch     text,
  started   timestamptz NOT NULL,
  ended     timestamptz,
  status    text NOT NULL,            -- running | ok | failed | killed
  pid       integer, host text,
  args      jsonb, counts jsonb,
  failures  integer DEFAULT 0,
  error     text,
  log_path  text
);
CREATE INDEX IF NOT EXISTS pipeline_run_stage ON pipeline_run (stage, started DESC);
-- per station-year listing state and per document OCR outcome, for coverage and status reporting
CREATE TABLE IF NOT EXISTS opif_listing (
  facility_id integer NOT NULL REFERENCES station,
  year        integer NOT NULL,
  status      text NOT NULL,          -- complete | partial | failed | empty
  files       integer, api_count integer,
  listed_at   timestamptz, error text,
  PRIMARY KEY (facility_id, year)
);
ALTER TABLE opif_file ADD COLUMN IF NOT EXISTS download_attempts integer DEFAULT 0;
ALTER TABLE opif_file ADD COLUMN IF NOT EXISTS download_error text;
ALTER TABLE document ADD COLUMN IF NOT EXISTS ocr_engine text;
ALTER TABLE document ADD COLUMN IF NOT EXISTS error text;

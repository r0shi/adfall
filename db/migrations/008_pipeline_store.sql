-- Postgres becomes the single store for the ingest pipeline: crawl state lives on opif_file, the OCR
-- ledger in ocr, listing walks in opif_listing, sync markers in meta and stage runs in pipeline_run.
-- (Before this, crawl/parse/OCR wrote data/political.sqlite and load_pg mirrored it here.)

-- crawl state per file (was SQLite files.downloaded / local_size)
ALTER TABLE opif_file ADD COLUMN IF NOT EXISTS downloaded boolean NOT NULL DEFAULT false;
ALTER TABLE opif_file ADD COLUMN IF NOT EXISTS local_size bigint;      -- bytes on disk after a verified download
UPDATE opif_file SET downloaded = true WHERE downloaded_at IS NOT NULL AND NOT downloaded;
CREATE INDEX IF NOT EXISTS opif_file_pending ON opif_file (facility_id, year) WHERE NOT downloaded AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS opif_file_downloaded ON opif_file (facility_id) WHERE downloaded AND deleted_at IS NULL;

-- the parser's "image-only PDF" flag, derived from raw so the OCR queue needs no JSON path in every query
ALTER TABLE document ADD COLUMN IF NOT EXISTS needs_ocr boolean
  GENERATED ALWAYS AS (COALESCE((raw->'fields'->>'needs_ocr')::boolean, false)) STORED;
CREATE INDEX IF NOT EXISTS document_needs_ocr ON document (file_id) WHERE needs_ocr;
CREATE INDEX IF NOT EXISTS document_status ON document (parse_status, kind);

-- OCR ledger: one row per document, retried until the attempt cap and then reported by ingest.status
CREATE TABLE IF NOT EXISTS ocr (
  file_id     text PRIMARY KEY REFERENCES opif_file,
  engine      text,                    -- vision | tesseract
  status      text NOT NULL,           -- ok | failed
  attempts    integer NOT NULL DEFAULT 1,
  pages_done  integer, pages_total integer,
  chars       integer,
  seconds     real,
  error       text,
  ocr_at      timestamptz
);

-- pipeline_run now gets its ids here (it was copied from SQLite with explicit ids before)
CREATE SEQUENCE IF NOT EXISTS pipeline_run_run_id_seq OWNED BY pipeline_run.run_id;
ALTER TABLE pipeline_run ALTER COLUMN run_id SET DEFAULT nextval('pipeline_run_run_id_seq');
SELECT setval('pipeline_run_run_id_seq', COALESCE((SELECT MAX(run_id) FROM pipeline_run), 0) + 1, false);
CREATE INDEX IF NOT EXISTS pipeline_run_running ON pipeline_run (stage) WHERE status = 'running';

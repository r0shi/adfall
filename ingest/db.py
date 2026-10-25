import os, sqlite3

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "political.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  file_manager_id TEXT PRIMARY KEY,
  facility_id     INTEGER NOT NULL,
  year            INTEGER NOT NULL,
  folder_path     TEXT NOT NULL,
  file_name       TEXT,
  file_size       INTEGER,          -- as listed by the FCC; NOT the byte size served (differs for ~99% of files)
  create_ts       TEXT,
  local_path      TEXT,
  downloaded      INTEGER DEFAULT 0,
  deleted         INTEGER DEFAULT 0,
  local_size      INTEGER,          -- bytes on disk after a verified download
  sha256          TEXT,
  downloaded_at   TEXT,
  download_attempts INTEGER DEFAULT 0,
  download_error  TEXT              -- last failure reason (HTTP code, 'not a PDF', ...); NULL once downloaded
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS files_fac_year ON files(facility_id, year);
CREATE INDEX IF NOT EXISTS files_pending ON files(downloaded, deleted);
CREATE TABLE IF NOT EXISTS docs (
  file_manager_id TEXT PRIMARY KEY REFERENCES files(file_manager_id),
  kind            TEXT,             -- order | invoice | form | other
  parse_status    TEXT,             -- ok | partial | failed
  order_no        TEXT,
  revision        TEXT,
  invoice_no      TEXT,
  advertiser      TEXT,
  agency          TEXT,
  product         TEXT,
  flight_start    TEXT,             -- ISO date
  flight_end      TEXT,
  print_date      TEXT,
  gross           REAL,
  net             REAL,
  spots           INTEGER,
  ad_ids          TEXT,             -- JSON list
  fields          TEXT,             -- JSON: form fields or line items
  parser_version  INTEGER,
  parsed_at       TEXT,
  error           TEXT              -- exception text when the parser crashed on this file
);
-- one row per (station, year) listing walk; a crawl only skips a station-year whose listing is complete
CREATE TABLE IF NOT EXISTS listing (
  facility_id INTEGER NOT NULL,
  year        INTEGER NOT NULL,
  status      TEXT NOT NULL,        -- complete | partial | failed | empty
  files       INTEGER,              -- files seen in the walk
  api_count   INTEGER,              -- file_count the API reports for the year folder
  listed_at   TEXT,
  error       TEXT,
  PRIMARY KEY (facility_id, year)
);
-- one row per OCR attempt outcome; a failed OCR is retried at most OCR_MAX_ATTEMPTS times, never forever
CREATE TABLE IF NOT EXISTS ocr (
  file_manager_id TEXT PRIMARY KEY,
  engine      TEXT,                 -- vision | tesseract
  status      TEXT NOT NULL,        -- ok | failed
  attempts    INTEGER DEFAULT 1,
  pages_done  INTEGER, pages_total INTEGER,
  chars       INTEGER,
  seconds     REAL,
  error       TEXT,
  ocr_at      TEXT
);
"""

UPGRADES = {  # table -> [(column, ddl)] for databases created before the column existed
    "files": [("deleted", "INTEGER DEFAULT 0"), ("local_size", "INTEGER"), ("sha256", "TEXT"), ("downloaded_at", "TEXT"),
              ("download_attempts", "INTEGER DEFAULT 0"), ("download_error", "TEXT")],
    "docs": [("parsed_at", "TEXT"), ("error", "TEXT")],
}


def connect(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")           # readers (status) never block the writing stage
    con.execute("PRAGMA busy_timeout=120000")
    con.executescript(SCHEMA)
    for table, cols in UPGRADES.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    con.commit()
    return con

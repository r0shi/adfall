import os, sqlite3

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "political.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  file_manager_id TEXT PRIMARY KEY,
  facility_id     INTEGER NOT NULL,
  year            INTEGER NOT NULL,
  folder_path     TEXT NOT NULL,
  file_name       TEXT,
  file_size       INTEGER,
  create_ts       TEXT,
  local_path      TEXT,
  downloaded      INTEGER DEFAULT 0,
  deleted         INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS files_fac_year ON files(facility_id, year);
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
  parser_version  INTEGER
);
"""


def connect(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(files)")}
    if "deleted" not in cols:                      # upgrade databases created before this column existed
        con.execute("ALTER TABLE files ADD COLUMN deleted INTEGER DEFAULT 0")
    return con

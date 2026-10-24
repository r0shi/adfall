-- TV Wormhole system of record. Written only by the ingest pipeline.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now());

-- ---------------------------------------------------------------- stations
CREATE TABLE IF NOT EXISTS station (
  facility_id   integer PRIMARY KEY,
  call          text NOT NULL,
  service       text NOT NULL,              -- DTV full power, DCA class A
  city          text, state text, licensee text,
  station_group text,                       -- Hearst / Nexstar / ... (derived from licensee, editable)
  rf_channel    text, virtual_channel text,
  tx            geometry(Point, 4326),
  contour       geometry(MultiPolygon, 4326),
  newson_id     text,
  public_file_slug text,
  updated_at    timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS station_contour_gix ON station USING gist (contour);

-- ---------------------------------------------------------------- raw OPIF
CREATE TABLE IF NOT EXISTS opif_file (
  file_id       text PRIMARY KEY,           -- FCC file_manager_id
  facility_id   integer NOT NULL REFERENCES station,
  year          integer NOT NULL,
  folder_path   text NOT NULL,
  file_name     text,
  size_bytes    integer,
  fcc_created_at timestamptz,
  downloaded_at timestamptz,
  deleted_at    timestamptz,
  sha256        text,
  local_path    text
);
CREATE INDEX IF NOT EXISTS opif_file_fac_year ON opif_file (facility_id, year);

CREATE TABLE IF NOT EXISTS document (
  file_id       text PRIMARY KEY REFERENCES opif_file,
  kind          text NOT NULL,              -- order | invoice | form | other
  template      text,                       -- wideorbit | wideorbit-ocr | katz | eport | sinclair
  source        text,                       -- text | ocr
  parse_status  text NOT NULL,
  parser_version integer,
  parsed_at     timestamptz DEFAULT now(),
  raw           jsonb NOT NULL              -- full extraction; entities are rebuilt from this
);

-- ---------------------------------------------------------------- entities
CREATE TABLE IF NOT EXISTS buyer (
  buyer_id      serial PRIMARY KEY,
  canonical_name text NOT NULL,
  category      text NOT NULL,              -- federal | state | local | issue | other
  kind          text DEFAULT 'unknown',     -- candidate | party | pac | issue | unknown
  party         text, office text, state text,
  fec_committee_id text, followthemoney_id text,
  notes         text,
  UNIQUE (canonical_name, category)
);
CREATE TABLE IF NOT EXISTS buyer_alias (
  alias         text NOT NULL,
  facility_id   integer,                    -- NULL = applies everywhere
  buyer_id      integer NOT NULL REFERENCES buyer,
  source        text,                       -- folder | advertiser | form | manual
  PRIMARY KEY (alias, facility_id)
);
CREATE TABLE IF NOT EXISTS agency (
  agency_id     serial PRIMARY KEY,
  name          text UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS order_ (
  order_id      serial PRIMARY KEY,
  facility_id   integer NOT NULL REFERENCES station,
  order_no      text NOT NULL,
  buyer_id      integer REFERENCES buyer,
  agency_id     integer REFERENCES agency,
  advertiser_text text, product text,
  flight_start  date, flight_end date,
  status        text NOT NULL DEFAULT 'booked',   -- booked | cancelled
  gross         numeric(14,2), net numeric(14,2), spots integer,
  latest_file_id text REFERENCES opif_file,
  first_seen    timestamptz, last_seen timestamptz,
  UNIQUE (facility_id, order_no)
);
CREATE TABLE IF NOT EXISTS order_revision (
  order_id      integer NOT NULL REFERENCES order_ ON DELETE CASCADE,
  file_id       text NOT NULL REFERENCES opif_file,
  print_date    date, fcc_created_at timestamptz,
  gross         numeric(14,2), net numeric(14,2), spots integer,
  PRIMARY KEY (order_id, file_id)
);
CREATE TABLE IF NOT EXISTS order_line (
  order_id      integer NOT NULL REFERENCES order_ ON DELETE CASCADE,
  line_no       integer NOT NULL,
  program       text,
  start_date    date, end_date date,
  spots         integer, length_sec integer,
  amount        numeric(14,2),
  PRIMARY KEY (order_id, line_no)
);
CREATE TABLE IF NOT EXISTS invoice (
  invoice_id    serial PRIMARY KEY,
  facility_id   integer NOT NULL REFERENCES station,
  invoice_no    text,
  order_id      integer REFERENCES order_,
  buyer_id      integer REFERENCES buyer,
  period_start  date, period_end date,
  gross         numeric(14,2), net numeric(14,2), spots integer,
  file_id       text REFERENCES opif_file,
  UNIQUE (facility_id, file_id)
);
CREATE TABLE IF NOT EXISTS spot (
  spot_id       bigserial PRIMARY KEY,
  invoice_id    integer NOT NULL REFERENCES invoice ON DELETE CASCADE,
  facility_id   integer NOT NULL,
  buyer_id      integer,
  aired_on      date NOT NULL,
  aired_time    text,
  program       text,
  rate          numeric(12,2),
  ad_id         text
);
CREATE INDEX IF NOT EXISTS spot_fac_day ON spot (facility_id, aired_on);
CREATE INDEX IF NOT EXISTS spot_ad ON spot (ad_id);
CREATE TABLE IF NOT EXISTS creative (
  ad_id         text PRIMARY KEY,
  prefix        text,
  buyer_id      integer,
  first_aired   date, last_aired date,
  airings       integer,
  title         text, video_url text
);
CREATE TABLE IF NOT EXISTS form (
  file_id       text PRIMARY KEY REFERENCES opif_file,
  facility_id   integer NOT NULL,
  buyer_id      integer,
  candidate text, committee text, office text, party text,
  election_date date, treasurer text, level text, issue text, sponsor text,
  raw           jsonb
);

-- ---------------------------------------------------------------- geography
CREATE TABLE IF NOT EXISTS county (
  geoid         text PRIMARY KEY,
  name          text, state text,
  pop           integer,
  geom          geometry(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS county_gix ON county USING gist (geom);
CREATE TABLE IF NOT EXISTS hex (
  h3            text NOT NULL,
  res           smallint NOT NULL,
  geom          geometry(Polygon, 4326),
  pop           double precision,           -- population allocated by county area share
  PRIMARY KEY (h3)
);
CREATE INDEX IF NOT EXISTS hex_res ON hex (res);
CREATE INDEX IF NOT EXISTS hex_gix ON hex USING gist (geom);
CREATE TABLE IF NOT EXISTS station_hex (
  facility_id   integer NOT NULL REFERENCES station,
  h3            text NOT NULL REFERENCES hex,
  res           smallint NOT NULL,
  coverage_share double precision NOT NULL, -- fraction of the cell inside the contour
  PRIMARY KEY (facility_id, h3)
);
CREATE INDEX IF NOT EXISTS station_hex_h3 ON station_hex (h3);

CREATE TABLE IF NOT EXISTS meta (key text PRIMARY KEY, value text);

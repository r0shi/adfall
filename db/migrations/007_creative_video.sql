-- Chain from Ad-ID creatives to watchable video (ingest.video).
-- buyer_channel: the campaign's / PAC's own channel on a video platform, found by name and evidence.
-- creative_video: the best (and runner-up) upload matched to each creative, with the signals that matched it.
CREATE TABLE IF NOT EXISTS buyer_channel (
  buyer_id      integer NOT NULL REFERENCES buyer ON DELETE CASCADE,
  source        text NOT NULL,                 -- youtube | override
  channel_id    text NOT NULL,
  channel_url   text,
  title         text,
  matched_by    text,                          -- api-search | ytdlp-search | override, plus the evidence
  confidence    real CHECK (confidence >= 0 AND confidence <= 1),
  uploads       integer,                       -- ad-length uploads seen on the last listing
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (buyer_id, source)
);
CREATE TABLE IF NOT EXISTS creative_video (
  ad_id         text NOT NULL REFERENCES creative ON DELETE CASCADE,
  rank          smallint NOT NULL DEFAULT 1,   -- 1 = best match, 2 = runner-up
  source        text NOT NULL,                 -- youtube | override | google-ads | ispot
  video_url     text NOT NULL,
  embed_url     text,                          -- NULL when the source cannot be embedded (link-out only)
  thumb_url     text,
  title         text,
  duration_sec  integer,
  published_at  date,
  confidence    real CHECK (confidence >= 0 AND confidence <= 1),
  matched_by    text,                          -- comma-separated signals: duration, date, order, title, override
  notes         text,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (ad_id, rank)
);
CREATE INDEX IF NOT EXISTS creative_video_source ON creative_video (source, confidence);

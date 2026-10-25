-- The entity rebuild (ingest.entities, run after every crawled state) recreates buyer and creative, so
-- buyer_id is not stable and ON DELETE CASCADE emptied both video tables. Key channels by the buyer slug
-- (category + name, the id the app uses) and drop the cascading foreign keys; ad_id is stable on its own.
ALTER TABLE creative_video DROP CONSTRAINT IF EXISTS creative_video_ad_id_fkey;
ALTER TABLE buyer_channel DROP CONSTRAINT IF EXISTS buyer_channel_buyer_id_fkey;
ALTER TABLE buyer_channel DROP CONSTRAINT IF EXISTS buyer_channel_pkey;
ALTER TABLE buyer_channel ADD COLUMN IF NOT EXISTS buyer_slug text;
UPDATE buyer_channel bc SET buyer_slug = b.category || '-' || left(trim(both '-' from regexp_replace(lower(b.canonical_name), '[^a-z0-9]+', '-', 'g')), 60)
  FROM buyer b WHERE b.buyer_id = bc.buyer_id AND bc.buyer_slug IS NULL;
DELETE FROM buyer_channel WHERE buyer_slug IS NULL;
ALTER TABLE buyer_channel ALTER COLUMN buyer_slug SET NOT NULL;
ALTER TABLE buyer_channel ALTER COLUMN buyer_id DROP NOT NULL;      -- convenience, refreshed by ingest.video at the start of every run
ALTER TABLE buyer_channel ADD PRIMARY KEY (buyer_slug, source);
CREATE INDEX IF NOT EXISTS buyer_channel_buyer ON buyer_channel (buyer_id);

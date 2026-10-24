ALTER TABLE buyer ADD COLUMN IF NOT EXISTS fec_candidate_id text;
ALTER TABLE buyer ADD COLUMN IF NOT EXISTS fec_committee_name text;
ALTER TABLE buyer ADD COLUMN IF NOT EXISTS district text;
ALTER TABLE buyer ADD COLUMN IF NOT EXISTS identity_method text;     -- fec-candidate | fec-committee | name-rule | manual | raw
ALTER TABLE buyer ADD COLUMN IF NOT EXISTS raw_labels integer;        -- how many distinct station labels merged into this buyer

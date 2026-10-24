PY := .venv/bin/python

.PHONY: db-up db-down migrate load entities identity geo marts export pipeline fec

db-up:        ## start PostGIS
	docker compose up -d db
db-down:
	docker compose down
migrate:      ## apply db/migrations/*.sql in order
	$(PY) -m ingest.pg migrate
load:         ## load stations.json and the pilot SQLite into Postgres
	$(PY) -m ingest.load_pg
identity:     ## merge station buyer labels into canonical buyers; match FEC candidates/committees (needs data/fec)
	$(PY) -m ingest.identity
entities:     ## build buyers/orders/invoices/spots/creatives from parsed documents (applies data/buyer_identity.json)
	$(PY) -m ingest.entities
geo:          ## counties, population, H3 cells, station coverage
	$(PY) -m ingest.geo
marts:        ## refresh materialized marts
	$(PY) -m ingest.pg marts
export:       ## write web/data artifacts and Parquet marts
	$(PY) -m ingest.export
pipeline: load entities identity entities marts export   ## identity needs a first entities pass for the raw labels
fec:          ## download FEC candidate/committee/linkage master files for the cycle
	mkdir -p data/fec && cd data/fec && for f in cn26 cm26 ccl26; do curl -s -L -A tv-wormhole -o $$f.zip https://www.fec.gov/files/bulk-downloads/2026/$$f.zip && unzip -oq $$f.zip; done

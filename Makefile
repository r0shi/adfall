PY := .venv/bin/python

.PHONY: db-up db-down migrate load entities geo marts export pipeline

db-up:        ## start PostGIS
	docker compose up -d db
db-down:
	docker compose down
migrate:      ## apply db/migrations/*.sql in order
	$(PY) -m ingest.pg migrate
load:         ## load stations.json and the pilot SQLite into Postgres
	$(PY) -m ingest.load_pg
entities:     ## build buyers/orders/invoices/spots/creatives from parsed documents
	$(PY) -m ingest.entities
geo:          ## counties, population, H3 cells, station coverage
	$(PY) -m ingest.geo
marts:        ## refresh materialized marts
	$(PY) -m ingest.pg marts
export:       ## write web/data artifacts and Parquet marts
	$(PY) -m ingest.export
pipeline: load entities marts export

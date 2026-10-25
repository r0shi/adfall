PY := .venv/bin/python

.PHONY: db-up db-down migrate crawl update ocr parse load entities identity geo marts places tiles export pipeline refresh fec status coverage validate batch

db-up:        ## start PostGIS
	docker compose up -d db
db-down:
	docker compose down
migrate:      ## apply db/migrations/*.sql in order
	$(PY) -m ingest.pg migrate
status:       ## pipeline status: counts per stage, running/failed stages, problems (add STATE=PA for per-station)
	$(PY) -m ingest.status $(if $(STATE),--state $(STATE),) $(if $(STATIONS),--stations,)
coverage:     ## crawled vs national document counts, by state and year
	$(PY) -m ingest.coverage $(if $(MISSING),--missing,)
validate:     ## parse invariants over document.raw in Postgres, failure rates per template, worst examples
	$(PY) -m ingest.validate
crawl:        ## list + download one state from the national target list: make crawl STATE=TX
	$(PY) -m ingest.crawl --stations-file data/crawl_targets_2026_national.txt --state $(STATE) --years 2026 --download --workers 6
update:       ## apply the FCC change feed since the last sync and download new files
	$(PY) -m ingest.update --download
ocr:          ## OCR image-only PDFs (Apple Vision; --engine tesseract elsewhere)
	$(PY) -m ingest.ocr --workers 4
parse:        ## parse new downloads; then re-parse the failed/unrecognised ones that now have OCR text
	$(PY) -m ingest.parse && $(PY) -m ingest.parse --only-failed
load:         ## load stations.json and the SQLite store into Postgres (also mirrors run history)
	$(PY) -m ingest.load_pg
identity:     ## merge station buyer labels into canonical buyers; match FEC candidates/committees (needs data/fec)
	$(PY) -m ingest.identity
entities:     ## build buyers/orders/invoices/spots/creatives from parsed documents (applies data/buyer_identity.json)
	$(PY) -m ingest.entities
geo:          ## counties, population, H3 cells, station coverage
	$(PY) -m ingest.geo
marts:        ## refresh materialized marts
	$(PY) -m ingest.pg marts
places:       ## static place index for search (Census Gazetteer ZIPs + places)
	$(PY) -m ingest.places
tiles:        ## PMTiles for hex layers and contours (needs tippecanoe)
	$(PY) -m ingest.tiles
export:       ## write web/data artifacts and Parquet marts
	$(PY) -m ingest.export
refresh: load entities identity entities marts   ## Postgres current with the SQLite store (what the batch driver runs after each state)
pipeline: load entities identity entities marts export tiles   ## identity needs a first entities pass for the raw labels
batch:        ## national 2026 crawl + OCR + parse, state by state, Postgres refreshed in the background (resumable)
	nohup $(PY) -m ingest.batch --targets data/crawl_targets_2026_national.txt --years 2026 > data/logs/batch-stdout.log 2>&1 &
	@echo "started; follow with: tail -f data/logs/batch-*.log   or   make status"
fec:          ## download FEC candidate/committee/linkage master files for the cycle
	mkdir -p data/fec && cd data/fec && for f in cn26 cm26 ccl26; do curl -s -L -A tv-wormhole -o $$f.zip https://www.fec.gov/files/bulk-downloads/2026/$$f.zip && unzip -oq $$f.zip; done

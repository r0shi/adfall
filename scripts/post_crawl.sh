#!/bin/sh
# Wait for scripts/crawl_states.sh to finish, then OCR image PDFs and run the Postgres pipeline.
# Detached: nohup scripts/post_crawl.sh &   (log: data/post_crawl.log)
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
until grep -q "all states done" data/crawl.log 2>/dev/null; do sleep 300; done
echo "== $(date '+%F %T') crawl finished; OCR" >> data/post_crawl.log
$PY -m ingest.ocr --workers 8 >> data/post_crawl.log 2>&1
$PY -m ingest.parse --only-failed >> data/post_crawl.log 2>&1
echo "== $(date '+%F %T') pipeline" >> data/post_crawl.log
$PY -m ingest.load_pg >> data/post_crawl.log 2>&1 && \
$PY -m ingest.entities >> data/post_crawl.log 2>&1 && \
$PY -m ingest.geo >> data/post_crawl.log 2>&1 && \
$PY -m ingest.pg marts >> data/post_crawl.log 2>&1 && \
$PY -m ingest.export >> data/post_crawl.log 2>&1
echo "== $(date '+%F %T') done" >> data/post_crawl.log

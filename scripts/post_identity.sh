#!/bin/sh
# After scripts/post_crawl.sh finishes, apply buyer identity and re-export (identity needs the entities pass first).
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
until grep -q "^== .* done$" data/post_crawl.log 2>/dev/null; do sleep 300; done
echo "== $(date '+%F %T') identity" >> data/post_crawl.log
$PY -m ingest.identity >> data/post_crawl.log 2>&1 && $PY -m ingest.entities >> data/post_crawl.log 2>&1 && \
$PY -m ingest.pg marts >> data/post_crawl.log 2>&1 && $PY -m ingest.export >> data/post_crawl.log 2>&1
echo "== $(date '+%F %T') identity done" >> data/post_crawl.log

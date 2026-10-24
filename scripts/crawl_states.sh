#!/bin/sh
# Crawl, download and parse 2026 political files for the stations listed in data/crawl_targets_2026.txt,
# one state at a time, logging to data/crawl.log. Resumable: re-running skips what is already done.
# OCR is deliberately left out (run `python3 -m ingest.ocr` afterwards; it is the expensive step).
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
while read -r state facs; do
  [ -z "$facs" ] && continue
  echo "== $(date '+%F %T') $state: listing + downloading" >> data/crawl.log
  $PY -m ingest.crawl --stations "$facs" --years 2026 --download --workers 6 >> data/crawl.log 2>&1
  echo "== $(date '+%F %T') $state: parsing" >> data/crawl.log
  $PY -m ingest.parse >> data/crawl.log 2>&1
done < data/crawl_targets_2026.txt
echo "== $(date '+%F %T') all states done" >> data/crawl.log

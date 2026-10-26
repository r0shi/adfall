#!/bin/sh
# After a national batch: wait for the driver and its refresh chain to finish, then publish everything the app reads.
#   nohup scripts/post_batch.sh > data/logs/post_batch.log 2>&1 &
# Steps: full export + PMTiles (safe_export waits for entity/marts locks), video re-alignment for the new buyers,
# the creative pages that depend on it, then the static site build. Idempotent; rerun any time.
#   --rerun   once the current driver is gone, run `make batch` again first (picks up states marked failed), then publish
cd "$(dirname "$0")/.." || exit 1
wait_driver() {
  echo "$(date '+%F %T') waiting for the batch driver (pipeline lock) to finish"
  .venv/bin/python - <<'PY'
import time
from ingest.runlog import lock_holder
while lock_holder("pipeline"):
    time.sleep(30)
PY
}
wait_driver
if [ "$1" = "--rerun" ]; then
  echo "$(date '+%F %T') rerunning the batch for the states still marked failed"
  .venv/bin/python -m ingest.batch --targets data/crawl_targets_2026_national.txt --years 2026 || echo "batch rerun exited non-zero; publishing what there is"
  wait_driver
fi
echo "$(date '+%F %T') batch done; exporting with tiles"
TVW_TILES=1 scripts/safe_export.sh || exit 1
echo "$(date '+%F %T') video re-alignment (cached listings, ~15 min)"
.venv/bin/python -m ingest.video videos || echo "video step failed; continuing"
scripts/safe_export.sh --only creatives,pages,details || exit 1
echo "$(date '+%F %T') building the app"
npm --prefix app run build >/dev/null 2>&1 && echo "$(date '+%F %T') app/build is current" || echo "app build failed"
.venv/bin/python -m ingest.status | head -40

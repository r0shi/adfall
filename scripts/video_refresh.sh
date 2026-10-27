#!/bin/sh
# One YouTube refresh, meant to run just after the Data API quota resets (midnight Pacific): channel search for the
# top buyers still without a channel (budgeted; cached searches are reused), uploads re-listed and matched to
# creatives, the creative pages re-exported, and the result published when .env is set up for Cloudflare.
#   scripts/video_refresh.sh [max new channel searches, default 90 = 9,000 of the 10,000 daily quota units]
# Log: data/logs/video-refresh-<date>.log (plus the stages' own logs). Exit 0 when every step passed.
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/node@22/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
PY=.venv/bin/python
MAX=${1:-90}
mkdir -p data/logs
LOG="data/logs/video-refresh-$(date +%F).log"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
run() { name=$1; shift; log "-- $name: $*"; t0=$(date +%s); "$@" >>"$LOG" 2>&1; rc=$?; log "-- $name: $([ $rc -eq 0 ] && echo ok || echo "FAILED exit=$rc") in $(( $(date +%s) - t0 ))s"; return $rc; }
[ -x "$PY" ] || { log "no interpreter at $PY"; exit 1; }
holder=$($PY -c 'from ingest.runlog import lock_holder; print(lock_holder("pipeline") or "")')
[ -n "$holder" ] && { log "batch driver running ($holder); not refreshing"; exit 0; }
log "== video refresh start  max_searches=$MAX"
run channels $PY -m ingest.video channels --top 300 --max-searches "$MAX" || { log "== exit 1"; exit 1; }
run videos   $PY -m ingest.video videos --top 300                        || { log "== exit 1"; exit 1; }
run export   scripts/safe_export.sh --only creatives,pages,details       || { log "== exit 1"; exit 1; }
if grep -qE '^(export )?R2_BUCKET=.' .env 2>/dev/null; then run publish scripts/publish.sh || { log "== exit 1"; exit 1; }
else log "-- publish: skipped (R2_BUCKET not in .env)"; fi
log "== video refresh done"; exit 0

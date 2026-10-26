#!/bin/sh
# Daily upkeep: pull the FCC change feed, parse and OCR what arrived, rebuild entities and marts, export, build the site.
#   scripts/daily.sh [--video]      scripts/launchd/com.adfall.daily.plist runs it at 05:10
# Steps, each a pipeline stage with its own lock, log and pipeline_run row:
#   update --download -> parse -> parse --only-failed -> ocr -> parse --only-failed -> entities -> identity -> entities -> marts
#   -> export + tiles (safe_export waits for entity/marts locks) -> [video + creatives export: Sundays or --video] -> npm build
# A failed step is reported and the steps that depend on it are skipped; export and build always run, so the site
# never falls behind what the database holds. Exit 0 when every step passed, 1 otherwise.
# Log: data/logs/daily-<date>.log (one timestamp line per step plus the stages' own output); the stage logs stay in
# data/logs/<stage>-<timestamp>.log. Steps down when a batch driver (ingest.batch, "pipeline" lock) is running.
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/node@22/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
PY=.venv/bin/python
mkdir -p data/logs data/locks
LOG="data/logs/daily-$(date +%F).log"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

VIDEO=0; [ "$(date +%u)" = 7 ] && VIDEO=1
for a in "$@"; do case "$a" in --video) VIDEO=1;; *) echo "usage: scripts/daily.sh [--video]" >&2; exit 2;; esac; done

# one daily run at a time: an flock on data/locks/daily.lock, held by this shell through fd 9 (ingest.runlog.lock_holder("daily") sees it)
[ -x "$PY" ] || { log "no interpreter at $PY (recreate the venv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"; exit 1; }
exec 9>>data/locks/daily.lock
if ! err=$($PY -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>&1); then
  case "$err" in *BlockingIOError*) log "daily already running ($(cat data/locks/daily.lock)); exiting"; exit 0;; esac
  log "cannot take data/locks/daily.lock: $err"; exit 1
fi
echo "pid $$ since $(date +%FT%T)" > data/locks/daily.lock

# a batch driver owns the pipeline while it runs; do not compete with it
holder=$($PY -c 'from ingest.runlog import lock_holder; print(lock_holder("pipeline") or "")')
if [ -n "$holder" ]; then log "batch driver running ($holder); skipping today's update"; exit 0; fi

log "== daily start  video=$VIDEO  log=$LOG"
FAILED=""; SKIPPED=""; TIMES=""
run() {  # run <name> <command...>: time it into the log, remember failures
  name=$1; shift
  log "-- $name: $*"
  t0=$(date +%s)
  "$@" >>"$LOG" 2>&1; rc=$?
  dt=$(( $(date +%s) - t0 ))
  TIMES="$TIMES
  $(printf '%-16s %6ds  %s' "$name" "$dt" "$([ $rc -eq 0 ] && echo ok || echo "FAILED exit=$rc")")"
  log "-- $name: $([ $rc -eq 0 ] && echo ok || echo "FAILED exit=$rc") in ${dt}s"
  [ $rc -ne 0 ] && FAILED="$FAILED $name"
  return $rc
}
skip() { SKIPPED="$SKIPPED $1"; log "-- $1: skipped ($2)"; }

run update        $PY -m ingest.update --download        # a feed failure keeps the sync marker, so tomorrow retries the day
run parse         $PY -m ingest.parse
run parse-failed  $PY -m ingest.parse --only-failed
run ocr           $PY -m ingest.ocr --workers 4
run parse-ocr     $PY -m ingest.parse --only-failed      # documents that now have OCR text

# refresh chain: each link reads the previous one's output, so stop at the first failure
if run entities $PY -m ingest.entities; then
  if run identity $PY -m ingest.identity; then
    if run entities-2 $PY -m ingest.entities; then run marts $PY -m ingest.pg marts; else skip marts "entities-2 failed"; fi
  else skip entities-2 "identity failed"; skip marts "identity failed"; fi
else skip identity "entities failed"; skip entities-2 "entities failed"; skip marts "entities failed"; fi

run export-tiles env TVW_TILES=1 scripts/safe_export.sh  # always: publish whatever the database holds now

if [ "$VIDEO" = 1 ]; then
  if run video $PY -m ingest.video videos; then run export-video scripts/safe_export.sh --only creatives,pages,details; else skip export-video "video failed"; fi
fi

run build npm --prefix app run build                     # always

log "== daily done  failed:${FAILED:- none}  skipped:${SKIPPED:- none}"
log "timings:$TIMES"
$PY -m ingest.status 2>/dev/null | head -30 >>"$LOG"
if [ -z "$FAILED" ]; then log "== exit 0"; exit 0; else log "== exit 1 (failed:$FAILED)"; exit 1; fi

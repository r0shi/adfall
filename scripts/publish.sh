#!/bin/sh
# Publish the site to Cloudflare: the data to R2, then the app shell to Pages. Unattended and idempotent. Nothing a
# visitor can see changes until the last step, the Pages deploy, which Cloudflare switches atomically; a failure before
# it leaves the previous deployment exactly as it was.
#   scripts/publish.sh             scripts/daily.sh runs it after a successful export when .env configures it
#   scripts/publish.sh --dry-run   rclone in --dry-run mode, no build, no deploy, no prune
# Steps:
#   1. live prefix    per-entity pages (creatives/id, buyers, stations, spend/<fac>, newscasts/<fac>) and health.json are
#                     synced in place with --checksum, so only changed files upload. Each is self-contained.
#   2. set prefix     everything else (aggregates, hex weights, tiles, marts, methods) is copied to v/<build id>, a
#                     prefix nothing references yet and that is never modified afterwards.
#   3. verify         the set answers through the public data URL, with Range and CORS, before anything depends on it.
#   4. build + deploy the app is built with VITE_DATA_SET=<url>/v/<id> and VITE_DATA_LIVE=<url>/live baked in
#                     (app/src/lib/base.js) and uploaded to Pages with wrangler. Every page of this build names this set.
#   5. prune          set prefixes older than the newest PUBLISH_KEEP are deleted.
# .env: R2_BUCKET, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, DATA_URL (the bucket's public base, a custom
#       domain with a CORS rule for the site), CLOUDFLARE_API_TOKEN (Pages edit), CLOUDFLARE_ACCOUNT_ID; optional
#       PAGES_PROJECT (adfall), SITE_URL (https://<project>.pages.dev; the Origin the CORS check sends), PUBLISH_KEEP (3),
#       PUBLISH_PING (a URL to GET on success and <url>/fail on failure, healthchecks.io style).
# Tools: rclone (brew install rclone), node, wrangler (app devDependency). Log: data/logs/publish-<date>.log, and
# data/publish.json records the last successful publish.
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
mkdir -p data/logs data/locks
LOG="data/logs/publish-$(date +%F).log"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
DRY=""; [ "$1" = "--dry-run" ] && DRY="--dry-run"
[ -f .env ] && { set -a; . ./.env; set +a; }
: "${PAGES_PROJECT:=adfall}" "${PUBLISH_KEEP:=3}" "${SITE_URL:=https://$PAGES_PROJECT.pages.dev}"

fail() { log "== FAILED: $*"; [ -n "$PUBLISH_PING" ] && curl -fsS -m 10 -o /dev/null "$PUBLISH_PING/fail" || true; exit 1; }
for v in R2_BUCKET R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY DATA_URL CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID; do
  eval "x=\$$v"; [ -n "$x" ] || fail "$v is not set in .env (see the header of this script)"
done
command -v rclone >/dev/null || fail "rclone not found (brew install rclone)"
[ -x app/node_modules/.bin/wrangler ] || fail "wrangler not installed (npm --prefix app install)"
DATA_URL=${DATA_URL%/}

# one publish at a time
if ! mkdir data/locks/publish.lock.d 2>/dev/null; then
  if [ -n "$(find data/locks/publish.lock.d -maxdepth 0 -mmin +180 2>/dev/null)" ]; then rm -rf data/locks/publish.lock.d; mkdir data/locks/publish.lock.d || exit 1
  else log "another publish is running; exiting"; exit 0; fi
fi
trap 'rm -rf data/locks/publish.lock.d' EXIT

id=$(python3 -I -c "import json; print(json.load(open('web/data/build.json'))['id'])" 2>/dev/null) || fail "web/data/build.json has no build id (run the export first)"
for f in stations.json buyers.json station_daily.json hex/weights_r5.json tiles/meta.json tiles/hex5.pmtiles methods.json creatives/all.json spend/index.json; do
  [ -s "web/data/$f" ] || fail "web/data/$f is missing or empty; not publishing an incomplete export"
done
log "== publish start  build=$id  bucket=$R2_BUCKET  project=$PAGES_PROJECT  $DRY"

# rclone's R2 remote from the environment, so no rclone.conf is needed
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_ACL=private RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
RC="rclone $DRY --checksum --fast-list --transfers 16 --checkers 32 --retries 3 --stats-one-line --stats 0 --log-level NOTICE --log-file $LOG"
B="r2:$R2_BUCKET"

# 1. live: per-entity pages, in place
t0=$(date +%s)
for d in creatives/id buyers stations; do [ -d "web/data/$d" ] && { $RC sync "web/data/$d" "$B/live/$d" || fail "sync of $d"; }; done
$RC sync web/data/spend "$B/live/spend" --include '[0-9]*.json' || fail "sync of spend"
[ -d web/data/newscasts ] && { $RC sync web/data/newscasts "$B/live/newscasts" --exclude index.json || fail "sync of newscasts"; }
[ -s web/data/health.json ] && { $RC copyto web/data/health.json "$B/live/health.json" || fail "copy of health.json"; }
log "-- live prefix synced in $(( $(date +%s) - t0 ))s"

# 2. set: everything else, to a new prefix
t0=$(date +%s)
FILTER=$(mktemp); cat > "$FILTER" <<'EOF'
- /creatives/id/**
- /buyers/**
- /stations/**
- /spend/[0-9]*.json
- /newscasts/[0-9]*.json
- /health.json
- .DS_Store
+ /**
EOF
$RC copy web/data "$B/v/$id" --filter-from "$FILTER" || { rm -f "$FILTER"; fail "copy of the set to v/$id"; }
rm -f "$FILTER"
log "-- set v/$id uploaded in $(( $(date +%s) - t0 ))s"
[ -n "$DRY" ] && { log "== dry run done"; exit 0; }

# 3. verify through the public URL: the id round-trips, a Range request works (PMTiles), CORS allows the site
got=$(curl -fsS -m 20 "$DATA_URL/v/$id/build.json" | python3 -I -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)
[ "$got" = "$id" ] || fail "$DATA_URL/v/$id/build.json does not answer with build $id (got '${got:-nothing}'); is DATA_URL the bucket's public domain?"
code=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -r 0-15 "$DATA_URL/v/$id/tiles/hex5.pmtiles")
[ "$code" = 206 ] || fail "Range request on tiles/hex5.pmtiles returned $code, not 206"
cors=$(curl -sI -m 20 -H "Origin: $SITE_URL" "$DATA_URL/v/$id/build.json" | tr -d '\r' | grep -i '^access-control-allow-origin:' | awk '{print $2}')
case "$cors" in "*"|"$SITE_URL") ;; *) fail "no CORS allow-origin for $SITE_URL on $DATA_URL (got '${cors:-none}'); add a CORS rule to the R2 bucket allowing GET and HEAD with the Range header from $SITE_URL";; esac
log "-- verified: build id, Range (206), CORS for $SITE_URL"

# 4. build with the bases baked in, deploy to Pages (atomic switch)
t0=$(date +%s)
VITE_DATA_SET="$DATA_URL/v/$id" VITE_DATA_LIVE="$DATA_URL/live" npm --prefix app run build >>"$LOG" 2>&1 || fail "app build"
[ "$(find app/build -type f | wc -l | tr -d ' ')" -lt 20000 ] || fail "app/build has 20,000 or more files; the data must not be in it"
[ -z "$(find app/build -type f -size +25M)" ] || fail "app/build has a file over 25 MB: $(find app/build -type f -size +25M)"
out=$(CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" app/node_modules/.bin/wrangler pages deploy app/build --project-name "$PAGES_PROJECT" --branch main --commit-dirty=true 2>&1) || { echo "$out" >>"$LOG"; fail "wrangler pages deploy"; }
echo "$out" >>"$LOG"
url=$(echo "$out" | grep -oE 'https://[a-z0-9.-]+\.pages\.dev' | tail -1)
log "-- deployed build $id to Pages in $(( $(date +%s) - t0 ))s: ${url:-see log}"

# 5. prune old sets, newest PUBLISH_KEEP kept (ids are timestamps, so sorting is chronological)
rclone lsd "$B/v" 2>/dev/null | awk '{print $NF}' | sort | sed -e :a -e '$d;N;2,'"$PUBLISH_KEEP"'ba' -e 'P;D' | while read -r old; do
  [ -n "$old" ] && [ "$old" != "$id" ] && { log "-- pruning v/$old"; rclone purge "$B/v/$old" >>"$LOG" 2>&1 || log "-- prune of v/$old failed (left in place)"; }
done

printf '{"id": "%s", "published_at": "%s", "site": "%s", "data": "%s/v/%s"}\n' "$id" "$(date -u +%FT%TZ)" "${url:-$SITE_URL}" "$DATA_URL" "$id" > data/publish.json
[ -n "$PUBLISH_PING" ] && curl -fsS -m 10 -o /dev/null "$PUBLISH_PING" || true
log "== publish done  build=$id"

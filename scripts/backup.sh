#!/bin/sh
# Nightly backup of the Adfall Postgres store: pg_dump -Fc into data/backups/ (newest 7 kept), then an upload to
# Backblaze B2 when a CLI for it is configured. Safe to run any time: pg_dump takes a consistent snapshot, and the
# script first waits (up to 30 min) for an entity rebuild or marts refresh to finish so the dump does not hold up
# or get blocked by their table swaps.
#
#   scripts/backup.sh                 # dump + prune + upload
#   scripts/backup.sh --no-upload     # dump + prune only
#   make backup                       # (none yet) -- scheduled by scripts/launchd/com.adfall.backup.plist
#
# Settings, all read from .env (or the environment):
#   DATABASE_URL   postgresql://tvw:tvw@127.0.0.1:5434/tvw      what to dump (ingest/pg.py default)
#   BACKUP_DIR     data/backups                                   where dumps go
#   BACKUP_KEEP    7                                              how many local dumps to keep
#   B2_BUCKET      (unset)                                        Backblaze bucket; no upload when unset
#   B2_PREFIX      adfall/postgres                                path inside the bucket
#   B2_RCLONE_REMOTE  b2                                          rclone remote name (rclone is tried before the b2 CLI)
#
# Restore (into an empty database, e.g. after `dropdb tvw && createdb -O tvw tvw`):
#   pg_restore -d "$DATABASE_URL" --no-owner --role=tvw -j 4 data/backups/tvw-YYYYmmdd-HHMMSS.dump
set -u
cd "$(dirname "$0")/.." || exit 1
ts() { date '+%F %T'; }

# .env: only the keys we use, so a stray line cannot run anything
if [ -f .env ]; then
  for key in DATABASE_URL BACKUP_DIR BACKUP_KEEP B2_BUCKET B2_PREFIX B2_RCLONE_REMOTE; do
    eval "cur=\${$key:-}"
    if [ -z "$cur" ]; then
      val=$(sed -n "s/^$key=//p" .env | tail -1)
      [ -n "$val" ] && eval "$key=\$val"
    fi
  done
fi
DATABASE_URL=${DATABASE_URL:-postgresql://tvw:tvw@127.0.0.1:5434/tvw}
BACKUP_DIR=${BACKUP_DIR:-data/backups}
BACKUP_KEEP=${BACKUP_KEEP:-7}
B2_BUCKET=${B2_BUCKET:-}
B2_PREFIX=${B2_PREFIX:-adfall/postgres}
B2_RCLONE_REMOTE=${B2_RCLONE_REMOTE:-b2}

# Homebrew postgresql@17 is keg-only; prefer its pg_dump (matches the server), else whatever is on PATH
for bin in /opt/homebrew/opt/postgresql@17/bin /usr/local/opt/postgresql@17/bin; do
  [ -x "$bin/pg_dump" ] && PATH="$bin:$PATH"
done
export PATH
command -v pg_dump >/dev/null 2>&1 || { echo "$(ts) pg_dump not found (brew install postgresql@17)"; exit 1; }

# wait for a table-swapping stage to finish, like scripts/safe_export.sh does; proceed anyway after 30 min
if [ -x .venv/bin/python ]; then
  .venv/bin/python - <<'PY'
import sys, time
try:
    from ingest.runlog import lock_holder
except Exception as e:   # no psycopg, no DB: the dump itself will say so
    sys.exit(0)
waited = 0
while waited < 1800:
    held = {n: lock_holder(n) for n in ("entities", "marts")}
    held = {n: h for n, h in held.items() if h}
    if not held:
        break
    if waited == 0:
        print(f"waiting for {', '.join(held)} to finish ({'; '.join(held.values())})", flush=True)
    time.sleep(15); waited += 15
PY
fi

mkdir -p "$BACKUP_DIR"
stamp=$(date '+%Y%m%d-%H%M%S')
out="$BACKUP_DIR/tvw-$stamp.dump"
echo "$(ts) pg_dump -> $out"
if ! pg_dump --format=custom --compress=zstd --no-password --dbname="$DATABASE_URL" --file="$out.part"; then
  echo "$(ts) pg_dump failed"; rm -f "$out.part"; exit 1
fi
# a dump that pg_restore cannot list is not a backup
if ! pg_restore --list "$out.part" >/dev/null; then
  echo "$(ts) dump is unreadable"; rm -f "$out.part"; exit 1
fi
mv "$out.part" "$out"
echo "$(ts) wrote $out ($(du -h "$out" | cut -f1))"

# keep the newest BACKUP_KEEP
ls -1t "$BACKUP_DIR"/tvw-*.dump 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | while read -r old; do
  echo "$(ts) pruning $old"; rm -f "$old"
done

[ "${1:-}" = "--no-upload" ] && exit 0

if [ -z "$B2_BUCKET" ]; then
  cat <<MSG
$(ts) no upload: B2_BUCKET is not set. To send dumps to Backblaze B2, add to .env
    B2_BUCKET=<bucket name>
and configure one CLI (both read an application key you create in the B2 console):
    brew install rclone && rclone config        # remote type "b2", name it "$B2_RCLONE_REMOTE"
  or
    brew install b2-tools && b2 account authorize
MSG
  exit 0
fi

dest="$B2_PREFIX/$(basename "$out")"
if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -qx "$B2_RCLONE_REMOTE:"; then
  echo "$(ts) rclone copy -> $B2_RCLONE_REMOTE:$B2_BUCKET/$B2_PREFIX/"
  rclone copyto "$out" "$B2_RCLONE_REMOTE:$B2_BUCKET/$dest" || { echo "$(ts) rclone upload failed"; exit 1; }
  # mirror the local retention in the bucket
  rclone delete --min-age "$((BACKUP_KEEP + 1))d" "$B2_RCLONE_REMOTE:$B2_BUCKET/$B2_PREFIX/" 2>/dev/null || true
elif command -v b2 >/dev/null 2>&1 && b2 account get >/dev/null 2>&1; then
  echo "$(ts) b2 file upload -> b2://$B2_BUCKET/$dest"
  b2 file upload --no-progress "$B2_BUCKET" "$out" "$dest" >/dev/null || { echo "$(ts) b2 upload failed"; exit 1; }
else
  cat <<MSG
$(ts) no upload: B2_BUCKET=$B2_BUCKET is set but no configured client was found. One of:
    brew install rclone && rclone config        # remote type "b2", name it "$B2_RCLONE_REMOTE"
    brew install b2-tools && b2 account authorize
MSG
  exit 0
fi
echo "$(ts) uploaded $(basename "$out")"

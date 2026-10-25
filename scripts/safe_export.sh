#!/bin/sh
# Export web artifacts only when no entity rebuild or marts refresh holds its lock (ingest.runlog flocks).
# Usage: scripts/safe_export.sh [export args...]      TVW_TILES=1 also rebuilds PMTiles afterwards.
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python - <<'PY' || exit 1
import sys, time
from ingest.runlog import lock_holder
waited = 0
while True:
    held = {n: lock_holder(n) for n in ("entities", "marts", "identity")}
    held = {n: h for n, h in held.items() if h}
    if not held:
        break
    if waited == 0:
        print(f"waiting for {', '.join(held)} to finish ({'; '.join(held.values())})", file=sys.stderr)
    if waited >= 2400:
        print("gave up after 40 min; locks still held", file=sys.stderr); sys.exit(1)
    time.sleep(15); waited += 15
PY
.venv/bin/python -m ingest.export "$@" || exit 1
if [ -n "$TVW_TILES" ]; then .venv/bin/python -m ingest.tiles; fi

#!/bin/sh
# Health check for the daily pipeline: the database answers, and the newest ok `update` and `export` runs are recent.
#   scripts/health.sh            scripts/launchd/com.adfall.health.plist runs it hourly
# Writes web/data/health.json ({ok, checks, checked_at}; the About page shows it) and exits 1 when any check fails.
# The window is 30 hours: the daily job runs at 05:10, so one missed day fails the check and a slow run does not.
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
.venv/bin/python - "$@" <<'PY'
import datetime, json, os, sys
MAX_AGE_H = 30
checks, now = {}, datetime.datetime.now().astimezone()

def check(name, ok, detail, **extra):
    checks[name] = {"ok": bool(ok), "detail": detail, **extra}

con = None
try:
    from ingest import db
    con = db.connect()
    con.execute("SELECT 1").fetchone()
    check("db", True, f"{db.dbname()} answers")
except BaseException as e:                              # SystemExit from the schema check counts as a failure too
    check("db", False, f"{type(e).__name__}: {str(e)[:200]}")

for stage in ("update", "export"):
    if con is None:
        check(stage, False, "no database"); continue
    row = con.execute("SELECT ended, counts FROM pipeline_run WHERE stage=%s AND status='ok' AND ended IS NOT NULL ORDER BY ended DESC LIMIT 1", (stage,)).fetchone()
    if not row:
        check(stage, False, "no successful run recorded"); continue
    age = (now - row[0]).total_seconds() / 3600
    last_status = con.execute("SELECT status, error FROM pipeline_run WHERE stage=%s ORDER BY started DESC LIMIT 1", (stage,)).fetchone()
    detail = f"last ok {age:.1f}h ago"
    if last_status and last_status[0] != "ok":
        detail += f"; newest run {last_status[0]}" + (f" ({last_status[1][:120]})" if last_status[1] else "")
    check(stage, age <= MAX_AGE_H, detail, last_ok=row[0].isoformat(timespec="seconds"), age_hours=round(age, 1), max_age_hours=MAX_AGE_H)

try:
    from ingest.runlog import lock_holder
    running = {n: h for n in ("pipeline", "daily", "update", "parse", "ocr", "entities", "identity", "marts", "export", "tiles", "video") if (h := lock_holder(n))}
except Exception:
    running = {}

out = {"ok": all(c["ok"] for c in checks.values()), "checks": checks, "running": running, "checked_at": now.isoformat(timespec="seconds")}
path = os.path.join("web", "data", "health.json")
tmp = path + ".tmp"
json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, path)
print(f"{now:%F %T} health {'ok' if out['ok'] else 'FAIL'}: " + "; ".join(f"{k} {'ok' if c['ok'] else 'FAIL'} ({c['detail']})" for k, c in checks.items()) + (f"; running: {', '.join(running)}" if running else ""))
sys.exit(0 if out["ok"] else 1)
PY

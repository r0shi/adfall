#!/bin/sh
# Install, remove and inspect Adfall's launchd agents (per-user, in ~/Library/LaunchAgents).
#   scripts/launchd/agents.sh install [name...]    copy + load (default: all of daily health backup video web)
#   scripts/launchd/agents.sh uninstall [name...]  unload + delete the copy (the repo's plists stay)
#   scripts/launchd/agents.sh status               each agent: loaded?, running pid, last exit, next log; plus Postgres
#   scripts/launchd/agents.sh run <name>           start a job now instead of waiting for its slot
#   scripts/launchd/agents.sh restart <name>       kill the running job and start it again (web after a serve.mjs change)
#   scripts/launchd/agents.sh stop <name>          kill the running job; a scheduled job runs again at its next slot,
#                                                  web comes straight back (KeepAlive): use uninstall to keep it down
# Names: daily (05:10 13:10 21:10), health (hourly :30), backup (03:30), video (03:10), web (serve.mjs on :4173, always on).
# Postgres is not one of these: Homebrew runs it (brew services start|stop|restart postgresql@17).
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
SRC="$REPO/scripts/launchd"
DST="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
ALL="daily health backup video web"

names() { [ $# -gt 0 ] && echo "$@" || echo "$ALL"; }
check() { [ -f "$SRC/com.adfall.$1.plist" ] || { echo "no such agent: $1 (one of: $ALL)" >&2; exit 2; }; }
loaded() { launchctl print "$DOMAIN/com.adfall.$1" >/dev/null 2>&1; }

cmd=${1:-status}; [ $# -gt 0 ] && shift
case "$cmd" in
install)
  mkdir -p "$DST" "$REPO/data/logs"
  for n in $(names "$@"); do
    check "$n"; f="$DST/com.adfall.$n.plist"
    plutil -lint -s "$SRC/com.adfall.$n.plist" || exit 1
    loaded "$n" && launchctl bootout "$DOMAIN/com.adfall.$n" 2>/dev/null
    cp "$SRC/com.adfall.$n.plist" "$f"
    launchctl enable "$DOMAIN/com.adfall.$n"
    launchctl bootstrap "$DOMAIN" "$f" && echo "installed com.adfall.$n" || { echo "bootstrap failed: com.adfall.$n" >&2; exit 1; }
  done ;;
uninstall)
  for n in $(names "$@"); do
    check "$n"
    loaded "$n" && launchctl bootout "$DOMAIN/com.adfall.$n" && echo "unloaded com.adfall.$n"
    rm -f "$DST/com.adfall.$n.plist"
  done ;;
run)     [ $# -eq 1 ] || { echo "usage: $0 run <name>" >&2; exit 2; }; check "$1"; launchctl kickstart "$DOMAIN/com.adfall.$1" && echo "started com.adfall.$1" ;;
restart) [ $# -eq 1 ] || { echo "usage: $0 restart <name>" >&2; exit 2; }; check "$1"; launchctl kickstart -k "$DOMAIN/com.adfall.$1" && echo "restarted com.adfall.$1" ;;
stop)    [ $# -eq 1 ] || { echo "usage: $0 stop <name>" >&2; exit 2; }; check "$1"; launchctl kill TERM "$DOMAIN/com.adfall.$1" && echo "sent TERM to com.adfall.$1" ;;
status)
  printf '%-18s %-8s %-8s %-10s %s\n' agent loaded pid last-exit log
  for n in $ALL; do
    if loaded "$n"; then
      info=$(launchctl print "$DOMAIN/com.adfall.$n")
      pid=$(echo "$info" | sed -n 's/^[[:space:]]*pid = //p' | head -1)
      ex=$(echo "$info" | sed -n 's/^[[:space:]]*last exit code = //p' | head -1)
      log=$(plutil -extract StandardOutPath raw "$SRC/com.adfall.$n.plist" 2>/dev/null | sed "s|^$REPO/||")
      printf '%-18s %-8s %-8s %-10s %s\n' "com.adfall.$n" yes "${pid:--}" "${ex:--}" "$log"
    else
      printf '%-18s %-8s\n' "com.adfall.$n" no
    fi
  done
  echo; brew services info postgresql@17 2>/dev/null | sed -n '1,4p' ;;
*) sed -n '2,12p' "$0"; exit 2 ;;
esac

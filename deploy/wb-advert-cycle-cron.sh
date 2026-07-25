#!/usr/bin/env bash
# Host-side wrapper for /etc/cron.d/wb-advert: dated logs + size cap.
# Invoked under flock from cron; runs full daily cycle inside wb-advert container.
set -uo pipefail

LOG_DIR=/opt/wb_malibri/data/pilot/logs
LOG_FILE="$LOG_DIR/daily_cycle.log"
MAX_BYTES=10485760 # 10 MiB

mkdir -p "$LOG_DIR"

if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE") -gt $MAX_BYTES ]]; then
  : >"$LOG_FILE"
fi

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

log "=== daily cycle start ===" >>"$LOG_FILE"
set +e
docker exec wb-advert bash -lc 'cd /app/wb_advert && bash run_daily_cycle.sh' 2>&1 | while IFS= read -r line; do
  log "$line" >>"$LOG_FILE"
done
rc=${PIPESTATUS[0]}
set -e
log "=== daily cycle end (exit=$rc) ===" >>"$LOG_FILE"
exit "$rc"

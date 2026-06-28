#!/bin/bash

# Daily Pendle positions digest (by wallet) -> "TID Pendle Tracking" channel.
# Reads the latest data/pendle_markets.json (refreshed hourly by
# cron_pendle_tracker.sh) + the riskAnalyst holdings feed, renders, and sends.

SCRIPT_DIR="/home/danger/PendleTracker"
cd "$SCRIPT_DIR" || exit 1

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/pendle_digest_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting Pendle digest"
python3 pendle_digest.py 2>&1 | tee -a "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

if [ "$STATUS" -ne 0 ]; then
    log "ERROR: pendle digest failed with exit code $STATUS"
fi

find "$LOG_DIR" -name "pendle_digest_*.log" -mtime +30 -delete 2>/dev/null

log "Pendle digest completed with exit code $STATUS"
echo "" >> "$LOG_FILE"

exit "$STATUS"

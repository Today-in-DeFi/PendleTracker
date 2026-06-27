#!/bin/bash

# Daily Pendle broad market index sweep (all active ETH markets).
# Separate from the hourly cron_pendle_tracker.sh (watchlist snapshot + alerter):
# this is the lighter, broader sweep that feeds top-PT discovery and Chunk C's
# held-PT -> market address resolution. ~2 min / ~120 throttled API calls.

SCRIPT_DIR="/home/danger/PendleTracker"
cd "$SCRIPT_DIR" || exit 1

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/pendle_index_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting Pendle index sweep"

python3 -m pendle_tracker index 2>&1 | tee -a "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

if [ "$STATUS" -ne 0 ]; then
    log "ERROR: index sweep failed with exit code $STATUS"
fi

find "$LOG_DIR" -name "pendle_index_*.log" -mtime +30 -delete 2>/dev/null

log "Pendle index sweep completed with exit code $STATUS"
echo "" >> "$LOG_FILE"

exit "$STATUS"

#!/bin/bash

# Hourly Pendle watchlist producer + risk alerter.

SCRIPT_DIR="/home/danger/PendleTracker"
cd "$SCRIPT_DIR" || exit 1

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/pendle_tracker_$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

run_step() {
    local label="$1"
    shift

    log "$label"
    "$@" 2>&1 | tee -a "$LOG_FILE"
    local status=${PIPESTATUS[0]}
    if [ "$status" -ne 0 ]; then
        log "ERROR: $label failed with exit code $status"
        return "$status"
    fi
    return 0
}

log "Starting PendleTracker cron job"

run_step "Writing Pendle market snapshot" python3 -m pendle_tracker snapshot
SNAPSHOT_STATUS=$?

if [ "$SNAPSHOT_STATUS" -eq 0 ]; then
    run_step "Running Pendle risk alerter" python3 pendle_risk_alerter.py
    ALERT_STATUS=$?
else
    ALERT_STATUS=0
fi

find "$LOG_DIR" -name "pendle_tracker_*.log" -mtime +30 -delete 2>/dev/null

if [ "$SNAPSHOT_STATUS" -ne 0 ]; then
    EXIT_CODE="$SNAPSHOT_STATUS"
else
    EXIT_CODE="$ALERT_STATUS"
fi

log "PendleTracker cron job completed with exit code $EXIT_CODE"
echo "" >> "$LOG_FILE"

exit "$EXIT_CODE"

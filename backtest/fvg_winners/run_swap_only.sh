#!/bin/bash
cd "$(dirname "$0")"
PY=/home/double_st_strategy/venv/bin/python
LOG_DIR=grid_logs
mkdir -p "$LOG_DIR"

for SYM in SOLUSDT XRPUSDT; do
  LOG="$LOG_DIR/grid_swap_${SYM}.log"
  echo "[$(date '+%H:%M:%S')] starting: swap $SYM"
  $PY grid_search.py swap "$SYM" > "$LOG" 2>&1
  echo "[$(date '+%H:%M:%S')] done: swap $SYM"
done
echo "[$(date '+%H:%M:%S')] ALL DONE"

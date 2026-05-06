#!/bin/bash
cd "$(dirname "$0")"
PY=/home/double_st_strategy/venv/bin/python
LOG_DIR=grid_logs
mkdir -p "$LOG_DIR"
unset FVG_TF

for SPEC in swap market; do
  for SYM in SOLUSDT XRPUSDT ETHUSDT; do
    LOG="$LOG_DIR/grid_partial_${SPEC}_${SYM}.log"
    echo "[$(date '+%H:%M:%S')] starting: partial $SPEC $SYM"
    $PY grid_search_partial.py "$SPEC" "$SYM" > "$LOG" 2>&1
    echo "[$(date '+%H:%M:%S')] done: partial $SPEC $SYM"
  done
done
echo "[$(date '+%H:%M:%S')] ALL DONE"

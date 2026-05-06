#!/bin/bash
cd "$(dirname "$0")"
PY=/home/double_st_strategy/venv/bin/python
LOG_DIR=grid_logs
mkdir -p "$LOG_DIR"
export FVG_TF=5m

for SPEC in swap market; do
  for SYM in SOLUSDT XRPUSDT; do
    LOG="$LOG_DIR/grid_${SPEC}_${SYM}_5m.log"
    echo "[$(date '+%H:%M:%S')] starting: $SPEC $SYM (5m)"
    $PY grid_search.py "$SPEC" "$SYM" > "$LOG" 2>&1
    echo "[$(date '+%H:%M:%S')] done: $SPEC $SYM (5m)"
  done
done
echo "[$(date '+%H:%M:%S')] ALL DONE"

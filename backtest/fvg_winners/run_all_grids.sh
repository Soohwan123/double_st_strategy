#!/bin/bash
# A 단계: SOL/XRP/ETH × swap/market = 6 runs, 15m, wider grid
cd "$(dirname "$0")"
PY=/home/double_st_strategy/venv/bin/python
LOG_DIR=grid_logs
mkdir -p "$LOG_DIR"
unset FVG_TF  # 15m 기본

for SPEC in swap market; do
  for SYM in SOLUSDT XRPUSDT ETHUSDT; do
    LOG="$LOG_DIR/grid_${SPEC}_${SYM}_15m.log"
    echo "[$(date '+%H:%M:%S')] starting: $SPEC $SYM"
    $PY grid_search.py "$SPEC" "$SYM" > "$LOG" 2>&1
    echo "[$(date '+%H:%M:%S')] done: $SPEC $SYM"
  done
done
echo "[$(date '+%H:%M:%S')] ALL DONE"

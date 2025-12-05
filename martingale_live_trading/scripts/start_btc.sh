#!/bin/bash
#
# BTCUSDC Grid Martingale 트레이딩 시작
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 이미 실행 중인지 확인
PID_FILE="$PROJECT_DIR/state/btc.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "BTC 트레이딩이 이미 실행 중입니다 (PID: $OLD_PID)"
        exit 1
    fi
fi

# Python 경로 설정
PYTHON="../venv/bin/python"
if [ ! -f "$PYTHON" ]; then
    PYTHON="python3"
fi

# 백그라운드 실행
echo "BTCUSDC Grid Martingale 트레이딩 시작..."
nohup $PYTHON trade_btc.py > /dev/null 2>&1 &
NEW_PID=$!

# PID 저장
echo $NEW_PID > "$PID_FILE"
echo "시작됨 (PID: $NEW_PID)"
echo "로그 확인: tail -f logs/btc_grid_$(date +%Y-%m-%d).log"

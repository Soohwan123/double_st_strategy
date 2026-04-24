#!/bin/bash
#
# Hyper Scalper V2 (BTCUSDT, 별도 계정) 트레이딩 시작
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

PID_FILE="$PROJECT_DIR/state/hyper_v2.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Hyper V2가 이미 실행 중입니다 (PID: $OLD_PID)"
        exit 1
    fi
fi

PYTHON="../venv/bin/python"
if [ ! -f "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "Hyper Scalper V2 (BTCUSDT) 트레이딩 시작..."
nohup $PYTHON trade_hyper_v2.py > /dev/null 2>&1 &
NEW_PID=$!

mkdir -p "$PROJECT_DIR/state"
echo $NEW_PID > "$PID_FILE"
echo "시작됨 (PID: $NEW_PID)"
echo "로그 확인: tail -f logs/hyper_v2_$(date -u +%Y-%m-%d).log"

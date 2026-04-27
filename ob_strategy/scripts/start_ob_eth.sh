#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
PID_FILE="$PROJECT_DIR/state/ob_eth.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "OB ETH 이미 실행 중 (PID: $OLD_PID)"
        exit 1
    fi
fi
PYTHON="../venv/bin/python"
[ ! -f "$PYTHON" ] && PYTHON="python3"
echo "OB ETH 트레이딩 시작..."
nohup $PYTHON trade_ob_eth.py > /dev/null 2>&1 &
NEW_PID=$!
mkdir -p "$PROJECT_DIR/state"
echo $NEW_PID > "$PID_FILE"
echo "시작됨 (PID: $NEW_PID)"
echo "로그: tail -f logs/ob_eth_$(date -u +%Y-%m-%d).log"

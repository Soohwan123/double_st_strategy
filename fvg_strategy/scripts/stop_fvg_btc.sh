#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/state/fvg_btc.pid"
if [ ! -f "$PID_FILE" ]; then
    echo "FVG BTC 실행 중 아님"
    exit 0
fi
PID=$(cat "$PID_FILE")
if ps -p "$PID" > /dev/null 2>&1; then
    echo "FVG BTC 중지 중... (PID: $PID)"
    kill "$PID"
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "FVG BTC 중지 완료"
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done
    kill -9 "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "FVG BTC 강제 종료"
else
    echo "FVG BTC 실행 중 아님"
    rm -f "$PID_FILE"
fi

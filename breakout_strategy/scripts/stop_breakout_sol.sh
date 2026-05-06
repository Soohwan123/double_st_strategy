#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/state/breakout_sol.pid"
if [ ! -f "$PID_FILE" ]; then
    echo "PID 파일 없음 - 실행 중 아님"
    exit 0
fi
PID=$(cat "$PID_FILE")
if ps -p "$PID" > /dev/null 2>&1; then
    echo "breakout_sol 중지 중... (PID: $PID)"
    kill "$PID"
    sleep 2
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "강제 종료..."
        kill -9 "$PID"
    fi
    rm -f "$PID_FILE"
    echo "breakout_sol 중지 완료"
else
    echo "프로세스 이미 종료됨"
    rm -f "$PID_FILE"
fi

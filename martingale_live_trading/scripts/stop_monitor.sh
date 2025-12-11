#!/bin/bash
#
# Monitor Alert 모니터링 중지
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PID_FILE="$PROJECT_DIR/state/monitor.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID"
        echo "Monitor Alert 중지됨 (PID: $PID)"
    else
        echo "프로세스가 이미 종료됨"
    fi
    rm -f "$PID_FILE"
else
    echo "Monitor Alert이 실행 중이 아닙니다"
fi

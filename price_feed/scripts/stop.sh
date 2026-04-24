#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/state/price_feed.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "price_feed 실행 중 아님 (PID 파일 없음)"
    exit 0
fi

PID=$(cat "$PID_FILE")
if [ -z "$PID" ] || ! ps -p "$PID" > /dev/null 2>&1; then
    echo "price_feed 실행 중 아님"
    rm -f "$PID_FILE"
    exit 0
fi

echo "price_feed 중지 중... (PID: $PID)"
kill "$PID"
for i in 1 2 3 4 5; do
    sleep 1
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "중지 완료"
        rm -f "$PID_FILE"
        exit 0
    fi
done
kill -9 "$PID" 2>/dev/null
echo "강제 종료 (SIGKILL)"
rm -f "$PID_FILE"

#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/state/price_feed.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "price_feed 이미 실행 중 (PID: $OLD_PID)"
        exit 1
    fi
fi

cd "$PROJECT_DIR" || exit 1
echo "price_feed 시작..."
nohup ../venv/bin/python price_feed.py > /dev/null 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "시작됨 (PID: $PID)"
echo "로그: tail -f $PROJECT_DIR/logs/price_feed_\$(date -u +%Y-%m-%d).log"

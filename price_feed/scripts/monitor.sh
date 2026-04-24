#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/state/price_feed.pid"
TG_TOKEN="8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
TG_CHAT_ID="8084935783"

HOSTNAME=$(hostname)
send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" -d text="$1" > /dev/null 2>&1
}
send_telegram "🟢 [price_feed monitor] 시작 | Host: ${HOSTNAME}"

ALERTED=0
while true; do
    if [ ! -f "$PID_FILE" ]; then
        if [ "$ALERTED" != "1" ]; then
            send_telegram "🔴 [price_feed] PID 파일 없음 | Host: ${HOSTNAME}"
            ALERTED=1
        fi
        sleep 30
        continue
    fi
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -z "$PID" ]; then
        sleep 30
        continue
    fi
    if ps -p "$PID" > /dev/null 2>&1; then
        if [ "$ALERTED" = "1" ]; then
            send_telegram "🟢 [price_feed] 복구됨 PID=${PID} | Host: ${HOSTNAME}"
            ALERTED=0
        fi
    else
        if [ "$ALERTED" != "1" ]; then
            send_telegram "🔴 [price_feed] DOWN! PID ${PID} 실행중 아님 | Host: ${HOSTNAME} | Time: $(date '+%Y-%m-%d %H:%M:%S KST')"
            ALERTED=1
        fi
    fi
    sleep 30
done

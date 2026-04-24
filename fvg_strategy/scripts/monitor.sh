#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$PROJECT_DIR/state"
TG_TOKEN="8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
TG_CHAT_ID="8084935783"
declare -A ALERTED
send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" -d text="$1" -d parse_mode="HTML" > /dev/null 2>&1
}
HOSTNAME=$(hostname)
send_telegram "🟢 <b>FVG Strategy Monitor Started</b>
Host: ${HOSTNAME}
Path: ${PROJECT_DIR}"
while true; do
    for pid_file in "$STATE_DIR"/*.pid; do
        [ ! -f "$pid_file" ] && continue
        bot_name=$(basename "$pid_file" .pid)
        pid=$(cat "$pid_file" 2>/dev/null)
        [ -z "$pid" ] && continue
        if ps -p "$pid" > /dev/null 2>&1; then
            if [ "${ALERTED[$bot_name]}" = "1" ]; then
                send_telegram "🟢 <b>${bot_name} Recovered</b>
PID: ${pid}"
                ALERTED[$bot_name]="0"
            fi
        else
            if [ "${ALERTED[$bot_name]}" != "1" ]; then
                send_telegram "🔴 <b>${bot_name} DOWN!</b>
PID ${pid} not running!
Time: $(date '+%Y-%m-%d %H:%M:%S KST')"
                ALERTED[$bot_name]="1"
            fi
        fi
    done
    sleep 30
done

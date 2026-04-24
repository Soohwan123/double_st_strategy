#!/bin/bash
#
# PID 모니터링 + 텔레그램 알림
# 30초마다 state/*.pid 확인, 프로세스 죽으면 텔레그램 알림
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$PROJECT_DIR/state"

# 텔레그램 설정
TG_TOKEN="8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
TG_CHAT_ID="8084935783"

# 알림 상태 추적 (이미 알림 보낸 PID 파일)
declare -A ALERTED

send_telegram() {
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" \
        -d text="${message}" \
        -d parse_mode="HTML" > /dev/null 2>&1
}

# 시작 알림
HOSTNAME=$(hostname)
send_telegram "🟢 <b>Monitor Started</b>
Host: ${HOSTNAME}
Path: ${PROJECT_DIR}"

while true; do
    for pid_file in "$STATE_DIR"/*.pid; do
        # pid 파일이 없으면 skip
        [ ! -f "$pid_file" ] && continue

        bot_name=$(basename "$pid_file" .pid)
        pid=$(cat "$pid_file" 2>/dev/null)

        # PID가 비어있으면 skip
        [ -z "$pid" ] && continue

        if ps -p "$pid" > /dev/null 2>&1; then
            # 프로세스 살아있음 -> 알림 상태 초기화
            if [ "${ALERTED[$bot_name]}" = "1" ]; then
                send_telegram "🟢 <b>${bot_name} Recovered</b>
PID: ${pid}
Host: ${HOSTNAME}"
                ALERTED[$bot_name]="0"
            fi
        else
            # 프로세스 죽어있음 -> 아직 알림 안보냈으면 보냄
            if [ "${ALERTED[$bot_name]}" != "1" ]; then
                send_telegram "🔴 <b>${bot_name} DOWN!</b>
PID ${pid} is not running!
Host: ${HOSTNAME}
Time: $(date '+%Y-%m-%d %H:%M:%S KST')"
                ALERTED[$bot_name]="1"
            fi
        fi
    done

    sleep 30
done

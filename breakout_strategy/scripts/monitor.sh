#!/bin/bash
# 통합 monitor — PID liveness + 로그 ERROR 스캔 (옵션 A)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$PROJECT_DIR/state"
LOGS_DIR="$PROJECT_DIR/logs"
TG_TOKEN="8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
TG_CHAT_ID="8084935783"
HOSTNAME=$(hostname)
STRATEGY_NAME=$(basename "$PROJECT_DIR")

declare -A ALERTED
declare -A LOG_OFFSET

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" -d text="$1" -d parse_mode="HTML" > /dev/null 2>&1
}

# 거래 실패 / 비상 청산 패턴 (한국어 로그 메시지)
ERROR_PATTERNS='긴급 시장가 청산|TP 1분간 설정 실패|SL 1분간 설정 실패|지정가 청산 주문 실패|SL 주문 실패|code=-4014|code=-4131|긴급 청산'

send_telegram "🟢 <b>${STRATEGY_NAME} Monitor Started</b>
Host: ${HOSTNAME}
Path: ${PROJECT_DIR}"

# 로그 오프셋 초기화 (현재 끝부터 모니터링 — 시작 시 과거 ERROR 무시)
if [ -d "$LOGS_DIR" ]; then
    for log_file in "$LOGS_DIR"/*.log; do
        [ ! -f "$log_file" ] && continue
        LOG_OFFSET[$log_file]=$(stat -c %s "$log_file" 2>/dev/null || echo 0)
    done
fi

while true; do
    # === PID liveness ===
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

    # === 로그 ERROR 스캔 ===
    if [ -d "$LOGS_DIR" ]; then
        for log_file in "$LOGS_DIR"/*.log; do
            [ ! -f "$log_file" ] && continue
            prev_offset=${LOG_OFFSET[$log_file]:-0}
            cur_size=$(stat -c %s "$log_file" 2>/dev/null || echo 0)
            # 새 파일 (rotation) 인 경우 offset 0 부터 — 새 파일은 prev_offset 없으니 자동 0
            if [ "$cur_size" -gt "$prev_offset" ]; then
                new_content=$(tail -c +$((prev_offset + 1)) "$log_file" 2>/dev/null | head -c 50000)
                matched=$(echo "$new_content" | grep -E "$ERROR_PATTERNS" | head -1)
                if [ -n "$matched" ]; then
                    first_match=$(echo "$matched" | head -c 250)
                    bot_name=$(basename "$log_file" .log | sed 's/_[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}$//')
                    send_telegram "⚠️ <b>${bot_name} ERROR</b>
${first_match}
Host: ${HOSTNAME}"
                fi
                LOG_OFFSET[$log_file]=$cur_size
            fi
        done
    fi

    sleep 30
done

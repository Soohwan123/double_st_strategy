#!/bin/bash
#
# 트레이딩 상태 확인 (USDC + USDT 4개 프로세스)
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "  Grid Martingale Trading Status"
echo "========================================"
echo ""

# 공통 함수: 프로세스 상태 체크
check_process_status() {
    local NAME=$1
    local PID_FILE=$2
    local STATE_FILE=$3

    echo "[ $NAME ]"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  상태: 실행 중 (PID: $PID)"
            ps -p "$PID" -o %cpu,%mem,etime --no-headers | awk '{printf "  CPU: %s%%, MEM: %s%%, 실행시간: %s\n", $1, $2, $3}'
        else
            echo "  상태: 중지됨 (stale PID file)"
        fi
    else
        echo "  상태: 중지됨"
    fi

    if [ -f "$STATE_FILE" ]; then
        echo "  상태 파일: 존재"
        LAST_UPDATE=$(python3 -c "import json; f=open('$STATE_FILE'); d=json.load(f); print(d.get('last_updated', 'N/A'))" 2>/dev/null)
        echo "  마지막 업데이트: $LAST_UPDATE"
    fi
    echo ""
}

# BTCUSDC 상태
check_process_status "BTCUSDC" "$PROJECT_DIR/state/btc.pid" "$PROJECT_DIR/state/state_btc.json"

# ETHUSDC 상태
check_process_status "ETHUSDC" "$PROJECT_DIR/state/eth.pid" "$PROJECT_DIR/state/state_eth.json"

# BTCUSDT 상태
check_process_status "BTCUSDT" "$PROJECT_DIR/state/btc_usdt.pid" "$PROJECT_DIR/state/state_btc_usdt.json"

# ETHUSDT 상태
check_process_status "ETHUSDT" "$PROJECT_DIR/state/eth_usdt.pid" "$PROJECT_DIR/state/state_eth_usdt.json"

# 오늘 로그 파일
TODAY=$(date +%Y-%m-%d)
echo "[ 오늘 로그 파일 ]"

BTC_LOG="$PROJECT_DIR/logs/grid_martingale_btc_$TODAY.log"
ETH_LOG="$PROJECT_DIR/logs/grid_martingale_eth_$TODAY.log"
BTC_USDT_LOG="$PROJECT_DIR/logs/grid_martingale_btc_usdt_$TODAY.log"
ETH_USDT_LOG="$PROJECT_DIR/logs/grid_martingale_eth_usdt_$TODAY.log"

if [ -f "$BTC_LOG" ]; then
    echo "  BTCUSDC: $(wc -l < "$BTC_LOG") lines"
else
    echo "  BTCUSDC: 없음"
fi

if [ -f "$ETH_LOG" ]; then
    echo "  ETHUSDC: $(wc -l < "$ETH_LOG") lines"
else
    echo "  ETHUSDC: 없음"
fi

if [ -f "$BTC_USDT_LOG" ]; then
    echo "  BTCUSDT: $(wc -l < "$BTC_USDT_LOG") lines"
else
    echo "  BTCUSDT: 없음"
fi

if [ -f "$ETH_USDT_LOG" ]; then
    echo "  ETHUSDT: $(wc -l < "$ETH_USDT_LOG") lines"
else
    echo "  ETHUSDT: 없음"
fi

echo ""

# Monitor Alert 상태
MONITOR_PID_FILE="$PROJECT_DIR/state/monitor.pid"
echo "[ Monitor Alert ]"
if [ -f "$MONITOR_PID_FILE" ]; then
    MONITOR_PID=$(cat "$MONITOR_PID_FILE")
    if ps -p "$MONITOR_PID" > /dev/null 2>&1; then
        echo "  상태: 실행 중 (PID: $MONITOR_PID)"
        ps -p "$MONITOR_PID" -o %cpu,%mem,etime --no-headers | awk '{printf "  CPU: %s%%, MEM: %s%%, 실행시간: %s\n", $1, $2, $3}'
    else
        echo "  상태: 중지됨 (stale PID file)"
    fi
else
    echo "  상태: 중지됨"
fi

echo ""
echo "========================================"

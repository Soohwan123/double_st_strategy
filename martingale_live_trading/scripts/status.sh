#!/bin/bash
#
# 트레이딩 상태 확인
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "  Grid Martingale Trading Status"
echo "========================================"
echo ""

# BTC 상태
BTC_PID_FILE="$PROJECT_DIR/state/btc.pid"
echo "[ BTCUSDC ]"
if [ -f "$BTC_PID_FILE" ]; then
    BTC_PID=$(cat "$BTC_PID_FILE")
    if ps -p "$BTC_PID" > /dev/null 2>&1; then
        echo "  상태: 실행 중 (PID: $BTC_PID)"
        # CPU/메모리 사용량
        ps -p "$BTC_PID" -o %cpu,%mem,etime --no-headers | awk '{printf "  CPU: %s%%, MEM: %s%%, 실행시간: %s\n", $1, $2, $3}'
    else
        echo "  상태: 중지됨 (stale PID file)"
    fi
else
    echo "  상태: 중지됨"
fi

# BTC 상태 파일
BTC_STATE="$PROJECT_DIR/state/state_btc.json"
if [ -f "$BTC_STATE" ]; then
    echo "  상태 파일: 존재"
    # 마지막 업데이트 시간
    LAST_UPDATE=$(python3 -c "import json; f=open('$BTC_STATE'); d=json.load(f); print(d.get('last_updated', 'N/A'))" 2>/dev/null)
    echo "  마지막 업데이트: $LAST_UPDATE"
fi
echo ""

# ETH 상태
ETH_PID_FILE="$PROJECT_DIR/state/eth.pid"
echo "[ ETHUSDC ]"
if [ -f "$ETH_PID_FILE" ]; then
    ETH_PID=$(cat "$ETH_PID_FILE")
    if ps -p "$ETH_PID" > /dev/null 2>&1; then
        echo "  상태: 실행 중 (PID: $ETH_PID)"
        ps -p "$ETH_PID" -o %cpu,%mem,etime --no-headers | awk '{printf "  CPU: %s%%, MEM: %s%%, 실행시간: %s\n", $1, $2, $3}'
    else
        echo "  상태: 중지됨 (stale PID file)"
    fi
else
    echo "  상태: 중지됨"
fi

# ETH 상태 파일
ETH_STATE="$PROJECT_DIR/state/state_eth.json"
if [ -f "$ETH_STATE" ]; then
    echo "  상태 파일: 존재"
    LAST_UPDATE=$(python3 -c "import json; f=open('$ETH_STATE'); d=json.load(f); print(d.get('last_updated', 'N/A'))" 2>/dev/null)
    echo "  마지막 업데이트: $LAST_UPDATE"
fi
echo ""

# 오늘 로그 파일
TODAY=$(date +%Y-%m-%d)
echo "[ 오늘 로그 파일 ]"
BTC_LOG="$PROJECT_DIR/logs/btc_grid_$TODAY.log"
ETH_LOG="$PROJECT_DIR/logs/eth_grid_$TODAY.log"

if [ -f "$BTC_LOG" ]; then
    echo "  BTC: $BTC_LOG ($(wc -l < "$BTC_LOG") lines)"
else
    echo "  BTC: 없음"
fi

if [ -f "$ETH_LOG" ]; then
    echo "  ETH: $ETH_LOG ($(wc -l < "$ETH_LOG") lines)"
else
    echo "  ETH: 없음"
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

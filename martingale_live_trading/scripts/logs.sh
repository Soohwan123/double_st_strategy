#!/bin/bash
#
# 실시간 로그 확인 (tail -f)
#
# 사용법:
#   ./logs.sh btc     - BTC 로그만
#   ./logs.sh eth     - ETH 로그만
#   ./logs.sh all     - 둘 다 (multitail 필요)
#   ./logs.sh         - 둘 다 (기본)
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

TODAY=$(date +%Y-%m-%d)
BTC_LOG="$PROJECT_DIR/logs/btc_grid_$TODAY.log"
ETH_LOG="$PROJECT_DIR/logs/eth_grid_$TODAY.log"

case "${1:-all}" in
    btc)
        if [ -f "$BTC_LOG" ]; then
            tail -f "$BTC_LOG"
        else
            echo "BTC 로그 파일 없음: $BTC_LOG"
            exit 1
        fi
        ;;
    eth)
        if [ -f "$ETH_LOG" ]; then
            tail -f "$ETH_LOG"
        else
            echo "ETH 로그 파일 없음: $ETH_LOG"
            exit 1
        fi
        ;;
    all|*)
        # multitail 있으면 사용, 없으면 tail 두 개
        if command -v multitail &> /dev/null; then
            multitail "$BTC_LOG" "$ETH_LOG" 2>/dev/null || tail -f "$BTC_LOG" "$ETH_LOG"
        else
            tail -f "$BTC_LOG" "$ETH_LOG" 2>/dev/null
        fi
        ;;
esac

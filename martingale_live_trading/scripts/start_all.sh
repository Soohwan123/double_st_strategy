#!/bin/bash
#
# BTC + ETH 동시 시작
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 모든 트레이딩 시작 ==="
echo ""

"$SCRIPT_DIR/start_btc.sh"
sleep 2
"$SCRIPT_DIR/start_eth.sh"

echo ""
echo "=== 완료 ==="

#!/bin/bash
#
# BTC + ETH 동시 중지
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 모든 트레이딩 중지 ==="
echo ""

"$SCRIPT_DIR/stop_btc.sh"
"$SCRIPT_DIR/stop_eth.sh"

echo ""
echo "=== 완료 ==="

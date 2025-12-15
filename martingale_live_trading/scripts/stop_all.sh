#!/bin/bash
#
# BTC + ETH (USDC + USDT) 동시 중지
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 모든 트레이딩 중지 ==="
echo ""

echo "[1/4] BTCUSDC 중지..."
sh "$SCRIPT_DIR/stop_btc.sh"

echo "[2/4] ETHUSDC 중지..."
sh "$SCRIPT_DIR/stop_eth.sh"

echo "[3/4] BTCUSDT 중지..."
sh "$SCRIPT_DIR/stop_btc_usdt.sh"

echo "[4/4] ETHUSDT 중지..."
sh "$SCRIPT_DIR/stop_eth_usdt.sh"

echo ""
echo "=== 완료 ==="

#!/bin/bash
#
# BTC + ETH (USDC + USDT) 동시 시작
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 모든 트레이딩 시작 ==="
echo ""

echo "[1/4] BTCUSDC 시작..."
sh "$SCRIPT_DIR/start_btc.sh"
sleep 2

echo "[2/4] ETHUSDC 시작..."
sh "$SCRIPT_DIR/start_eth.sh"
sleep 2

echo "[3/4] BTCUSDT 시작..."
sh "$SCRIPT_DIR/start_btc_usdt.sh"
sleep 2

echo "[4/4] ETHUSDT 시작..."
sh "$SCRIPT_DIR/start_eth_usdt.sh"

echo ""
echo "=== 완료 ==="

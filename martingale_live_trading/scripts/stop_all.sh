#!/bin/bash
#
# BTC + ETH + XRP (USDC + USDT) 동시 중지
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 모든 트레이딩 중지 ==="
echo ""

echo "[1/5] BTCUSDC 중지..."
sh "$SCRIPT_DIR/stop_btc.sh"

echo "[2/5] ETHUSDC 중지..."
sh "$SCRIPT_DIR/stop_eth.sh"

echo "[3/5] BTCUSDT 중지..."
sh "$SCRIPT_DIR/stop_btc_usdt.sh"

echo "[4/5] ETHUSDT 중지..."
sh "$SCRIPT_DIR/stop_eth_usdt.sh"

echo "[5/5] XRPUSDT 중지..."
sh "$SCRIPT_DIR/stop_xrp_usdt.sh"

echo ""
echo "=== 완료 ==="

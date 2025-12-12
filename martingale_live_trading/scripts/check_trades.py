#!/usr/bin/env python3
"""
체결 내역 데이터 포맷 확인
"""

import sys
import json
sys.path.insert(0, '/home/soohwan/projects/double_st_strategy/martingale_live_trading')

from binance.client import Client
from config import Config

client = Client(Config.API_KEY, Config.API_SECRET)

# 최근 체결 내역 조회
trades = client.futures_account_trades(symbol='BTCUSDC', limit=20)

print(f"총 {len(trades)}개 체결 내역\n")
print("=" * 80)

for trade in trades[-5:]:  # 최근 5개만 출력
    print(json.dumps(trade, indent=2))
    print("-" * 80)

# 특정 주문번호 확인
print("\n\n=== 주문번호 타입 확인 ===")
if trades:
    sample = trades[-1]
    print(f"orderId: {sample.get('orderId')} (type: {type(sample.get('orderId'))})")
    print(f"id: {sample.get('id')} (type: {type(sample.get('id'))})")

# 문자열 vs 정수 비교 테스트
print("\n\n=== 문자열 vs 정수 비교 테스트 ===")
order_id_str = "37174117899"
order_id_int = 37174117899

matching_str = [t for t in trades if t.get('orderId') == order_id_str]
matching_int = [t for t in trades if t.get('orderId') == order_id_int]
matching_converted = [t for t in trades if t.get('orderId') == int(order_id_str)]

print(f"문자열로 비교: {len(matching_str)}개 매칭")
print(f"정수로 비교: {len(matching_int)}개 매칭")
print(f"변환 후 비교: {len(matching_converted)}개 매칭")

if matching_int:
    print(f"\n매칭된 거래 PnL: {matching_int[0].get('realizedPnl')}")

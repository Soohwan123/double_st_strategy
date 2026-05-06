"""
_common_swap 으로 SOL/XRP 풀 백테스트 (2020-2026) + yearly breakdown.

- 원본 파라미터 (bt_25 SOL, bt_27 XRP) 그대로 사용
- INITIAL_CAPITAL=1000, MAX_LEV=90 (원본 winners 와 동일)
- 전체 기간 + 연도별 결과 출력
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common_swap as C
from _common_swap import run_backtest

CONFIGS = [
    ('bt_25 SOL 15m v6_1', 'SOLUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.003, rr=1.2, max_wait=10, risk_per_trade=0.03, min_fvg_pct=0.0)),
    ('bt_27 XRP 15m v6_1', 'XRPUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.004, rr=1.2, max_wait=20, risk_per_trade=0.02, min_fvg_pct=0.0)),
]

YEARS = [
    ('20-21', '2020-01-06', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-26'),
]

ALL = ('20-26 ALL', '2020-01-06', '2026-04-26')


def fmt_ret(r):
    if abs(r) >= 1e9:  return f"{r:+.2e}%"
    if abs(r) >= 1e6:  return f"{r/1e6:+.2f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.2f}%"


def run_one(label, sym, tf, ver, params, start, end, ylabel):
    C.START = start
    C.END = end
    trades, cap, mdd = run_backtest(symbol=sym, tf=tf, version=ver, **params)
    tt = len(trades)
    wins = len([t for t in trades if t['pnl'] > 0])
    liqs = len([t for t in trades if t.get('reason') == 'LIQ'])
    wr = wins / tt * 100 if tt > 0 else 0
    ret = (cap / C.INITIAL_CAPITAL - 1) * 100
    print(f"  {ylabel:<10} | {tt:>5} | {wr:>5.1f}% | {mdd*100:>5.2f}% | {fmt_ret(ret):>14} | LIQ={liqs}")
    return cap, mdd, ret


print(f"\n{'='*80}")
print(f"  _common_swap.py 풀 백테스트  (CAP=${C.INITIAL_CAPITAL}, MAX_LEV={C.MAX_LEV})")
print(f"{'='*80}")

for label, sym, tf, ver, params in CONFIGS:
    print(f"\n[{label}]  RR={params['rr']}, SL_BUF={params['sl_buffer_pct']}, MAX_WAIT={params['max_wait']}, RPT={params['risk_per_trade']}")
    print(f"  {'기간':<10} | {'거래':>5} | {'WR':>5} | {'MDD':>6} | {'수익률':>14} | LIQ")
    print(f"  {'-'*10}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}-+-{'-'*14}-+-{'-'*5}")

    # 풀 기간
    cap_all, mdd_all, ret_all = run_one(label, sym, tf, ver, params, ALL[1], ALL[2], ALL[0])

    # 연도별
    for yname, ystart, yend in YEARS:
        run_one(label, sym, tf, ver, params, ystart, yend, yname)

    print(f"  → 풀 기간 최종 자본: ${cap_all:.2f}, MDD {mdd_all*100:.2f}%, 수익률 {fmt_ret(ret_all)}")

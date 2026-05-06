"""bt_06 XRP 5m OB SWAP 연도별 백테스트."""
import sys; sys.path.insert(0, '..')
import _common_swap as C
from _common_swap import run_backtest

PARAMS = dict(impulse_lookback=15, impulse_min_pct=0.03, sl_buffer_pct=0.002,
              rr=2.5, max_wait=350, risk_per_trade=0.04, use_htf=True)

YEARS = [
    ('20-21', '2020-09-14', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-23'),
]

def fmt(r):
    if abs(r)>=1e6: return f"{r/1e6:+.2f}M%"
    if abs(r)>=1e3: return f"{r/1e3:+.1f}K%"
    return f"{r:+.2f}%"

C.START='2020-09-14'; C.END='2026-04-23'
trades_all, cap_all, mdd_all = run_backtest(symbol='XRPUSDT', tf='5m', **PARAMS)
ret_all = (cap_all/C.INITIAL_CAPITAL-1)*100
wins_all = sum(1 for t in trades_all if t['pnl']>0)
print(f"\n{'='*78}\n  bt_06 XRP 5m OB SWAP v4")
print(f"  전체: {fmt(ret_all)}  MDD={mdd_all*100:.1f}%  Trades={len(trades_all)}  WR={wins_all/len(trades_all)*100:.1f}%")
print(f"{'='*78}")
print(f"  {'Year':<6} | {'Trades':>7} | {'WR%':>6} | {'MDD%':>6} | {'Return':>12} | {'Final Cap':>14}")
print(f"  {'-'*70}")
for yname, ys, ye in YEARS:
    C.START=ys; C.END=ye
    trades, cap, mdd = run_backtest(symbol='XRPUSDT', tf='5m', **PARAMS)
    tt = len(trades); wins = sum(1 for t in trades if t['pnl']>0)
    wr = wins/tt*100 if tt>0 else 0
    ret = (cap/C.INITIAL_CAPITAL-1)*100
    print(f"  {yname:<6} | {tt:>7} | {wr:>6.2f} | {mdd*100:>6.2f} | {fmt(ret):>12} | {cap:>14.2f}")

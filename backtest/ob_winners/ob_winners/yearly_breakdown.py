"""
OB Retest winners 연도별 백테스트.
각 config 상단에 전체 기간 수익률 출력 후 연도별 breakdown.
"""
import sys; sys.path.insert(0, '..')
import _common as C
from _common import run_backtest

CONFIGS = [
    ('bt_01 SOL 15m MDD≤50%', 'SOLUSDT', '15m',
     dict(impulse_lookback=7,  impulse_min_pct=0.026, sl_buffer_pct=0.0001,  rr=1.5, max_wait=400, risk_per_trade=0.045)),
    ('bt_02 SOL 15m MDD≤60%', 'SOLUSDT', '15m',
     dict(impulse_lookback=7,  impulse_min_pct=0.026, sl_buffer_pct=0.00015, rr=1.5, max_wait=400, risk_per_trade=0.05)),
    ('bt_03 SOL  5m MDD≤40%', 'SOLUSDT', '5m',
     dict(impulse_lookback=16, impulse_min_pct=0.027, sl_buffer_pct=0.0001,  rr=1.7, max_wait=600, risk_per_trade=0.04)),
    ('bt_04 SOL  5m MDD≤50%', 'SOLUSDT', '5m',
     dict(impulse_lookback=18, impulse_min_pct=0.027, sl_buffer_pct=0.0001,  rr=1.7, max_wait=400, risk_per_trade=0.05)),
    ('bt_05 SOL  5m MDD≤60%', 'SOLUSDT', '5m',
     dict(impulse_lookback=16, impulse_min_pct=0.025, sl_buffer_pct=0.00015, rr=1.5, max_wait=400, risk_per_trade=0.05)),
]

YEARS = [
    ('20-21', '2020-01-06', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-23'),
]

FULL_START = '2020-01-06'
FULL_END   = '2026-04-23'


def fmt_ret(r):
    if abs(r) >= 1e6: return f"{r/1e6:+.2f}M%"
    if abs(r) >= 1e3: return f"{r/1e3:+.0f}K%"
    return f"{r:+.2f}%"


for label, sym, tf, params in CONFIGS:
    # 전체 기간 수익률
    C.START = FULL_START; C.END = FULL_END
    trades_all, cap_all, mdd_all = run_backtest(sym, tf, **params)
    tt_all = len(trades_all)
    wins_all = len([t for t in trades_all if t['pnl'] > 0])
    ret_all = (cap_all / C.INITIAL_CAPITAL - 1) * 100

    print(f"\n{'='*72}")
    print(f"  {label}  |  전체: {fmt_ret(ret_all)}  MDD={mdd_all*100:.1f}%  "
          f"Trades={tt_all}  WR={wins_all/tt_all*100 if tt_all else 0:.1f}%")
    print(f"{'='*72}")
    print(f"  {'Year':<6} | {'Trades':>7} | {'WR%':>6} | {'MDD%':>6} | {'Return':>12} | {'Final Cap':>12}")
    print(f"  {'-'*62}")

    for yname, ystart, yend in YEARS:
        C.START = ystart; C.END = yend
        trades, cap, mdd = run_backtest(sym, tf, **params)
        tt = len(trades)
        wins = len([t for t in trades if t['pnl'] > 0])
        wr = wins / tt * 100 if tt > 0 else 0
        ret = (cap / C.INITIAL_CAPITAL - 1) * 100
        print(f"  {yname:<6} | {tt:>7} | {wr:>6.2f} | {mdd*100:>6.2f} | {fmt_ret(ret):>12} | {cap:>12.2f}")

print()

"""
bt_26 / bt_27 / bt_28 연도별 백테스트 (1m resolve 신규 winners).
"""
import sys; sys.path.insert(0, '..')
import _common as C
from _common import run_backtest

CONFIGS = [
    ('bt_26 XRP 15m MDD≤40% v6_1 1m', 'XRPUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.004, rr=1.2, max_wait=20, risk_per_trade=0.015, min_fvg_pct=0.0)),
    ('bt_27 XRP 15m MDD≤50% v6_1 1m', 'XRPUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.004, rr=1.2, max_wait=20, risk_per_trade=0.02, min_fvg_pct=0.0)),
    ('bt_28 ETH 15m MDD≤50% v3 1m', 'ETHUSDT', '15m', 'v3',
     dict(sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.015, min_fvg_pct=0.0)),
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
    if abs(r) >= 1e9: return f"{r/1e9:+.2f}B%"
    if abs(r) >= 1e6: return f"{r/1e6:+.2f}M%"
    if abs(r) >= 1e3: return f"{r/1e3:+.1f}K%"
    return f"{r:+.2f}%"


for label, sym, tf, ver, params in CONFIGS:
    C.START = FULL_START; C.END = FULL_END
    trades_all, cap_all, mdd_all = run_backtest(
        symbol=sym, tf=tf, version=ver, **params)
    tt_all = len(trades_all)
    wins_all = len([t for t in trades_all if t['pnl'] > 0])
    ret_all = (cap_all / C.INITIAL_CAPITAL - 1) * 100

    print(f"\n{'='*78}")
    print(f"  {label}")
    print(f"  전체: {fmt_ret(ret_all)}  MDD={mdd_all*100:.1f}%  "
          f"Trades={tt_all}  WR={wins_all/tt_all*100 if tt_all else 0:.1f}%")
    print(f"{'='*78}")
    print(f"  {'Year':<6} | {'Trades':>7} | {'WR%':>6} | {'MDD%':>6} | {'Return':>12} | {'Final Cap':>14}")
    print(f"  {'-'*70}")

    for yname, ystart, yend in YEARS:
        C.START = ystart; C.END = yend
        trades, cap, mdd = run_backtest(
            symbol=sym, tf=tf, version=ver, **params)
        tt = len(trades)
        wins = len([t for t in trades if t['pnl'] > 0])
        wr = wins / tt * 100 if tt > 0 else 0
        ret = (cap / C.INITIAL_CAPITAL - 1) * 100
        print(f"  {yname:<6} | {tt:>7} | {wr:>6.2f} | {mdd*100:>6.2f} | {fmt_ret(ret):>12} | {cap:>14.2f}")

print()

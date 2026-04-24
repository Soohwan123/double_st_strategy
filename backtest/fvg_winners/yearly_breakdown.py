"""
SOL/BNB 7개 winner 전략 연도별 백테스트.
START/END 를 매해 교체하며 총 7 × 6 = 42 runs.
"""
import _common as C
from _common import run_backtest

CONFIGS = [
    # Original winners
    ('04 BTC 15m MDD60 v6_1', 'BTCUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.003, rr=1.3, max_wait=25, risk_per_trade=0.03, min_fvg_pct=0.0)),
    ('10 ETH 15m MDD60 v3',   'ETHUSDT', '15m', 'v3',
     dict(sl_buffer_pct=0.005, rr=1.5, max_wait=20, risk_per_trade=0.02, min_fvg_pct=0.0)),
    ('15 XRP 15m MDD60 v6_2', 'XRPUSDT', '15m', 'v6_2',
     dict(sl_buffer_pct=0.0045, rr=1.4, max_wait=15, risk_per_trade=0.025, min_fvg_pct=0.0)),
    # SOL / BNB new winners
    ('17 SOL 15m MDD40 v3',   'SOLUSDT', '15m', 'v3',
     dict(sl_buffer_pct=0.005, rr=1.5, max_wait=60, risk_per_trade=0.02, min_fvg_pct=0.0)),
    ('18 SOL 15m MDD40 v6_1', 'SOLUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.004, rr=1.7, max_wait=7,  risk_per_trade=0.025, min_fvg_pct=0.0)),
    ('19 SOL 15m MDD40 v6_2', 'SOLUSDT', '15m', 'v6_2',
     dict(sl_buffer_pct=0.004, rr=1.9, max_wait=10, risk_per_trade=0.02, min_fvg_pct=0.0)),
    ('20 SOL 5m  MDD50 v3',   'SOLUSDT', '5m',  'v3',
     dict(sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.01, min_fvg_pct=0.0)),
    ('21 SOL 5m  MDD40 v6_1', 'SOLUSDT', '5m',  'v6_1',
     dict(sl_buffer_pct=0.003, rr=1.8, max_wait=15, risk_per_trade=0.01, min_fvg_pct=0.0)),
    ('22 BNB 15m MDD50 v3',   'BNBUSDT', '15m', 'v3',
     dict(sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.015, min_fvg_pct=0.0)),
    ('23 BNB 15m MDD50 v6_1', 'BNBUSDT', '15m', 'v6_1',
     dict(sl_buffer_pct=0.005, rr=1.8, max_wait=25, risk_per_trade=0.015, min_fvg_pct=0.0)),
]

YEARS = [
    ('20-21', '2020-01-06', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-03-02'),
]

def fmt_ret(r):
    if abs(r) >= 1e9:  return f"{r:+.2e}%"
    if abs(r) >= 1e6:  return f"{r/1e6:+.2f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.2f}%"

print(f"\n{'Config':<22} | {'Year':<6} | {'Trades':>7} | {'WR%':>6} | {'MDD%':>6} | {'Return':>12}")
print('-' * 80)

for label, sym, tf, ver, params in CONFIGS:
    for yname, ystart, yend in YEARS:
        C.START = ystart
        C.END = yend
        trades, cap, mdd = run_backtest(symbol=sym, tf=tf, version=ver, **params)
        tt = len(trades)
        wins = len([t for t in trades if t['pnl'] > 0])
        wr = wins / tt * 100 if tt > 0 else 0
        ret = (cap / C.INITIAL_CAPITAL - 1) * 100
        print(f"{label:<22} | {yname:<6} | {tt:>7} | {wr:>6.2f} | {mdd*100:>6.2f} | {fmt_ret(ret):>12}")
    print('-' * 80)

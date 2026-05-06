"""bt_31 + RPT=0.030 yearly breakdown."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common_swap as S

PARAMS = dict(
    symbol='SOLUSDT', tf='5m', version='v3',
    sl_buffer_pct=0.0205, rr=1.59, max_wait=17,
    risk_per_trade=0.030, min_fvg_pct=0.002,
)

YEARS = [
    ('20-21', '2020-09-14', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-26'),
    ('FULL',  '2020-09-14', '2026-04-26'),
]


def fmt(r):
    if abs(r) >= 1e6:  return f"{r/1e6:+.2f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.1f}%"


print(f"파라미터: {PARAMS}")
print()
print(f"{'기간':<10} | {'trades':>6} | {'WR':>5} | {'MDD':>6} | {'Final cap':>15} | {'return':>10} | {'avg_lev':>7}")
print('-' * 90)
for yname, ystart, yend in YEARS:
    S.START, S.END = ystart, yend
    trades, cap, mdd = S.run_backtest(**PARAMS)
    if not trades:
        continue
    import pandas as pd
    df = pd.DataFrame(trades)
    wr = (df['pnl']>0).sum()/len(df)*100
    avg_lev = df['leverage'].mean()
    ret = (cap/1000-1)*100
    print(f"{yname:<10} | {len(trades):>6} | {wr:>4.0f}% | {mdd*100:>5.1f}% | ${cap:>14,.0f} | {fmt(ret):>10} | {avg_lev:>7.2f}")

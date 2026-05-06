"""
B 단계: A 의 best 후보들 yearly breakdown.
SOL/XRP/ETH × swap/market 의 best 후보 ~6개를 6 연도 별로 검증.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common_jit as J
import pandas as pd

CONFIGS = []
# 각 (spec, sym) 의 trades>=500 MDD<=60 best 1개 + trades>=1200 MDD<=70 best 1개 (있으면)
for spec in ['swap', 'market']:
    for sym in ['SOLUSDT', 'XRPUSDT', 'ETHUSDT']:
        df = pd.read_csv(f'/home/double_st_strategy/backtest/fvg_winners/grid_results_{spec}_{sym}_15m.csv')
        # best balanced (>=500 trades, <=60% MDD)
        b = df[(df.return_pct>0)&(df.trades>=500)&(df.mdd<=0.6)]
        if len(b)>0:
            t = b.sort_values('return_pct',ascending=False).iloc[0]
            label = f'{spec[:3]} {sym[:3]} bal'
            CONFIGS.append((label, spec, sym, dict(
                sl_buffer_pct=float(t.sl_buf), rr=float(t.rr),
                max_wait=int(t.max_wait), risk_per_trade=float(t.rpt),
                min_fvg_pct=float(t.min_fvg_pct))))
        # best high-trade (>=1200 trades, <=70% MDD)
        h = df[(df.return_pct>0)&(df.trades>=1200)&(df.mdd<=0.7)]
        if len(h)>0:
            t = h.sort_values('return_pct',ascending=False).iloc[0]
            label = f'{spec[:3]} {sym[:3]} 1200+'
            CONFIGS.append((label, spec, sym, dict(
                sl_buffer_pct=float(t.sl_buf), rr=float(t.rr),
                max_wait=int(t.max_wait), risk_per_trade=float(t.rpt),
                min_fvg_pct=float(t.min_fvg_pct))))

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
    if abs(r) >= 1e6:  return f"{r/1e6:+.1f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.0f}%"


print(f'후보 {len(CONFIGS)}개:')
for label, spec, sym, p in CONFIGS:
    print(f"  {label}: SL_BUF={p['sl_buffer_pct']}, RR={p['rr']}, WAIT={p['max_wait']}, RPT={p['risk_per_trade']}, MIN_FVG={p['min_fvg_pct']}")
print()

# JIT warmup
print('JIT warmup...', flush=True)
J.START, J.END = '2020-09-14', '2020-12-31'
J.run_backtest('SOLUSDT', '15m', 'v6_1', mode='market',
    sl_buffer_pct=0.02, rr=2.0, max_wait=50, risk_per_trade=0.01, min_fvg_pct=0.01)
print('warmup done')
print()

results = {}
for yname, ystart, yend in YEARS:
    J._DATA_CACHE.clear()
    J.START, J.END = ystart, yend
    print(f'Year {yname}...', flush=True)
    for label, spec, sym, p in CONFIGS:
        try:
            trades, cap, mdd = J.run_backtest(sym, '15m', 'v6_1', mode=spec, **p)
            ret = (cap / J.INITIAL_CAPITAL - 1) * 100
            results[(label, yname)] = (ret, len(trades), mdd)
        except Exception as e:
            results[(label, yname)] = (None, 0, 0)

# print return matrix
print()
header = f"{'후보':<22} | " + ' | '.join(f"{y[0]:>8}" for y in YEARS)
print(header)
print('-' * len(header))
for label, _, _, _ in CONFIGS:
    row = [f"{label:<22}"]
    for yname, _, _ in YEARS:
        ret, _, _ = results.get((label, yname), (None, 0, 0))
        row.append(f"{fmt(ret) if ret is not None else 'ERR':>8}")
    print(' | '.join(row))

# trades + MDD 요약
print()
print(f"{'후보':<22} | trades(FULL) | MDD(FULL) | yearly losers")
print('-' * len(header))
for label, _, _, _ in CONFIGS:
    full_ret, full_t, full_mdd = results[(label, 'FULL')]
    losers = sum(1 for y in YEARS if y[0] != 'FULL' and results.get((label, y[0]), (0, 0, 0))[0] is not None and results[(label, y[0])][0] < 0)
    print(f"{label:<22} | {full_t:>12} | {full_mdd*100:>8.1f}% | {losers} of 6")

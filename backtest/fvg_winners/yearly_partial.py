"""
Partial TP winner 후보들 yearly breakdown.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common_jit as J
import pandas as pd

CONFIGS = []

# 각 spec/sym 의 best 후보 자동 추출
for spec in ['swap', 'market']:
    for sym in ['SOLUSDT', 'XRPUSDT', 'ETHUSDT']:
        try:
            df = pd.read_csv(f'/home/double_st_strategy/backtest/fvg_winners/grid_results_partial_{spec}_{sym}_15m.csv')
        except FileNotFoundError:
            continue
        # best 균형 (≥500/MDD60)
        b = df[(df.return_pct>0)&(df.trades>=500)&(df.mdd<=0.6)]
        if len(b)>0:
            t = b.sort_values('return_pct',ascending=False).iloc[0]
            label = f'{spec[:3]} {sym[:3]} bal'
            CONFIGS.append((label, spec, sym, dict(
                sl_buffer_pct=float(t.sl_buf), rr1=float(t.rr1), rr2=float(t.rr2),
                max_wait=int(t.max_wait), risk_per_trade=float(t.rpt),
                min_fvg_pct=float(t.min_fvg_pct), be_after_tp1=bool(t.be))))
        # best ≥1200 trades, MDD≤70
        h = df[(df.return_pct>0)&(df.trades>=1200)&(df.mdd<=0.7)]
        if len(h)>0:
            t = h.sort_values('return_pct',ascending=False).iloc[0]
            label = f'{spec[:3]} {sym[:3]} 1200'
            CONFIGS.append((label, spec, sym, dict(
                sl_buffer_pct=float(t.sl_buf), rr1=float(t.rr1), rr2=float(t.rr2),
                max_wait=int(t.max_wait), risk_per_trade=float(t.rpt),
                min_fvg_pct=float(t.min_fvg_pct), be_after_tp1=bool(t.be))))

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
    if r is None: return '   ERR'
    if abs(r) >= 1e6:  return f"{r/1e6:+.1f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.0f}%"


print(f'후보 {len(CONFIGS)}개:')
for label, spec, sym, p in CONFIGS:
    print(f"  {label}: SL={p['sl_buffer_pct']} RR1={p['rr1']} RR2={p['rr2']} W={p['max_wait']} RPT={p['risk_per_trade']} MIN={p['min_fvg_pct']} BE={p['be_after_tp1']}")
print()

# warmup
print('warmup...', flush=True)
J.START, J.END = '2020-09-14', '2020-12-31'
J.run_backtest('SOLUSDT', '15m', 'v6_1', mode='market',
    sl_buffer_pct=0.02, rr=2.0, max_wait=50, risk_per_trade=0.01, min_fvg_pct=0.01,
    is_partial=True, rr1=1.5, rr2=2.5, be_after_tp1=False)
print('done')

results = {}
for yname, ystart, yend in YEARS:
    J._DATA_CACHE.clear()
    J.START, J.END = ystart, yend
    print(f'Year {yname}...', flush=True)
    for label, spec, sym, p in CONFIGS:
        try:
            trades, cap, mdd = J.run_backtest(sym, '15m', 'v6_1', mode=spec,
                sl_buffer_pct=p['sl_buffer_pct'], rr=2.0,
                max_wait=p['max_wait'], risk_per_trade=p['risk_per_trade'],
                min_fvg_pct=p['min_fvg_pct'],
                is_partial=True, rr1=p['rr1'], rr2=p['rr2'],
                be_after_tp1=p['be_after_tp1'])
            ret = (cap / J.INITIAL_CAPITAL - 1) * 100
            results[(label, yname)] = (ret, len(trades), mdd)
        except Exception as e:
            results[(label, yname)] = (None, 0, 0)

print()
hd = f"{'후보':<22} | " + ' | '.join(f"{y[0]:>8}" for y in YEARS)
print(hd)
print('-'*len(hd))
for label, _, _, _ in CONFIGS:
    row = [f"{label:<22}"]
    for yname, _, _ in YEARS:
        ret, _, _ = results.get((label, yname), (None, 0, 0))
        row.append(f"{fmt(ret):>8}")
    print(' | '.join(row))

print()
print(f"{'후보':<22} | trades(FULL) | MDD(FULL) | yearly losers (out of 6)")
print('-'*len(hd))
for label, _, _, _ in CONFIGS:
    full = results.get((label, 'FULL'), (None, 0, 0))
    losers = sum(1 for y in YEARS if y[0] != 'FULL' and results.get((label, y[0]), (0, 0, 0))[0] is not None and results[(label, y[0])][0] < 0)
    print(f"{label:<22} | {full[1]:>12} | {full[2]*100:>8.1f}% | {losers}")

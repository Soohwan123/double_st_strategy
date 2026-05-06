"""market SOL 균형 winner 후보 yearly breakdown.

각 후보를 6 연도 별로 돌려서 매년 양수인지 / 단일 강세장 의존인지 확인.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common_jit as J

CANDIDATES = [
    ('A High RR',     dict(sl_buffer_pct=0.02, rr=5.0, max_wait=50, risk_per_trade=0.015, min_fvg_pct=0.007)),
    ('B Sweet RR3',   dict(sl_buffer_pct=0.02, rr=3.0, max_wait=50, risk_per_trade=0.020, min_fvg_pct=0.010)),
    ('C RR3 short',   dict(sl_buffer_pct=0.02, rr=3.0, max_wait=30, risk_per_trade=0.015, min_fvg_pct=0.010)),
    ('D RR2.5',       dict(sl_buffer_pct=0.02, rr=2.5, max_wait=30, risk_per_trade=0.020, min_fvg_pct=0.010)),
    ('E RR2 wait30',  dict(sl_buffer_pct=0.02, rr=2.0, max_wait=30, risk_per_trade=0.010, min_fvg_pct=0.010)),
    ('F RR2 wait50',  dict(sl_buffer_pct=0.02, rr=2.0, max_wait=50, risk_per_trade=0.010, min_fvg_pct=0.010)),
    ('G many trades', dict(sl_buffer_pct=0.02, rr=2.0, max_wait=30, risk_per_trade=0.020, min_fvg_pct=0.007)),
    ('H most trades', dict(sl_buffer_pct=0.02, rr=2.0, max_wait=50, risk_per_trade=0.005, min_fvg_pct=0.007)),
]

YEARS = [
    ('20-21', '2020-09-14', '2021-01-06'),  # SOL 상장 ~ 2021 초
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-26'),
    ('FULL',  '2020-09-14', '2026-04-26'),
]


def fmt_ret(r):
    if abs(r) >= 1e9:  return f"{r:+.1e}%"
    if abs(r) >= 1e6:  return f"{r/1e6:+.1f}M%"
    if abs(r) >= 1e4:  return f"{r/1e3:+.0f}K%"
    return f"{r:+.1f}%"


# 연도-바깥, 후보-안쪽 — 연도별 캐시 1번만 빌드
results = {}  # (label, yname) -> (ret, trades, mdd)

print('JIT warmup...', flush=True)
J.START, J.END = YEARS[0][1], YEARS[0][2]
J.run_backtest('SOLUSDT', '15m', 'v6_1', mode='market', **CANDIDATES[0][1])
print('warmup done', flush=True)

for yname, ystart, yend in YEARS:
    J._DATA_CACHE.clear()
    J.START, J.END = ystart, yend
    print(f'Year {yname} loading...', flush=True)
    for label, params in CANDIDATES:
        try:
            trades, cap, mdd = J.run_backtest('SOLUSDT', '15m', 'v6_1', mode='market', **params)
            ret = (cap / J.INITIAL_CAPITAL - 1) * 100
            results[(label, yname)] = (ret, len(trades), mdd)
        except Exception as e:
            results[(label, yname)] = (None, 0, 0)

print()
header = f"{'후보':<14} | " + ' | '.join(f"{y[0]:>10}" for y in YEARS)
print(header)
print('-' * len(header))
for label, _ in CANDIDATES:
    row = [f"{label:<14}"]
    for yname, _, _ in YEARS:
        ret, tt, mdd = results.get((label, yname), (None, 0, 0))
        if ret is None:
            row.append('  ERROR')
        else:
            row.append(f"{fmt_ret(ret):>10}")
    print(' | '.join(row))

# Trade counts row
print()
print(f"{'후보 (거래수)':<14} | " + ' | '.join(f"{y[0]:>10}" for y in YEARS))
print('-' * len(header))
for label, _ in CANDIDATES:
    row = [f"{label:<14}"]
    for yname, _, _ in YEARS:
        _, tt, _ = results.get((label, yname), (None, 0, 0))
        row.append(f"{tt:>10}")
    print(' | '.join(row))

# MDD row
print()
print(f"{'후보 (MDD%)':<14} | " + ' | '.join(f"{y[0]:>10}" for y in YEARS))
print('-' * len(header))
for label, _ in CANDIDATES:
    row = [f"{label:<14}"]
    for yname, _, _ in YEARS:
        _, _, mdd = results.get((label, yname), (None, 0, 0))
        row.append(f"{mdd*100:>9.1f}%")
    print(' | '.join(row))

print()
print('파라미터:')
for label, p in CANDIDATES:
    print(f"  {label}: SL_BUF={p['sl_buffer_pct']}, RR={p['rr']}, WAIT={p['max_wait']}, RPT={p['risk_per_trade']}, MIN_FVG={p['min_fvg_pct']}")

"""신규 추가된 BTC/ETH OB BT 5종 yearly breakdown 통합."""
import sys; sys.path.insert(0, '..')
import _common_swap as C
from _common_swap import run_backtest

CONFIGS = [
    # bt_11 BTC v3 MDD≤40 deprecated (RPT=0.08)
    ('11d BTC v3 MDD40 (RPT 0.08, deprecated)', 'BTCUSDT',
     dict(impulse_lookback=7, impulse_min_pct=0.01, sl_buffer_pct=0.005,
          rr=0.15, max_wait=50, risk_per_trade=0.08, use_htf=True)),
    # bt_11 BTC v3 MDD≤50 (RPT=0.12)
    ('11  BTC v3 MDD50 (RPT 0.12)', 'BTCUSDT',
     dict(impulse_lookback=7, impulse_min_pct=0.01, sl_buffer_pct=0.005,
          rr=0.15, max_wait=50, risk_per_trade=0.12, use_htf=True)),
    # bt_14 BTC v3 MDD≤60 (RPT=0.15)
    ('14  BTC v3 MDD60 (RPT 0.15)', 'BTCUSDT',
     dict(impulse_lookback=7, impulse_min_pct=0.01, sl_buffer_pct=0.005,
          rr=0.15, max_wait=50, risk_per_trade=0.15, use_htf=True)),
    # bt_12 ETH v11 MDD≤50 (RPT=0.10, IP=0.012)
    ('12  ETH v11 MDD50 (RPT 0.10)', 'ETHUSDT',
     dict(impulse_lookback=12, impulse_min_pct=0.012, sl_buffer_pct=0.003,
          rr=0.25, max_wait=50, risk_per_trade=0.10, use_htf=True)),
    # bt_13 ETH v11 MDD≤60 (RPT=0.10, IP=0.010)
    ('13  ETH v11 MDD60 (RPT 0.10)', 'ETHUSDT',
     dict(impulse_lookback=12, impulse_min_pct=0.01, sl_buffer_pct=0.003,
          rr=0.25, max_wait=50, risk_per_trade=0.10, use_htf=True)),
]

YEARS = [
    ('20-21', '2020-09-14', '2021-01-06'),
    ('21-22', '2021-01-06', '2022-01-06'),
    ('22-23', '2022-01-06', '2023-01-06'),
    ('23-24', '2023-01-06', '2024-01-06'),
    ('24-25', '2024-01-06', '2025-01-06'),
    ('25-26', '2025-01-06', '2026-04-23'),
]


def fmt(r):
    if abs(r) >= 1e9: return f"{r/1e9:+.2f}B%"
    if abs(r) >= 1e6: return f"{r/1e6:+.1f}M%"
    if abs(r) >= 1e4: return f"{r/1e3:+.0f}K%"
    if abs(r) >= 1e3: return f"{r/1e3:+.1f}K%"
    return f"{r:+.1f}%"


# Header
print(f"\n{'='*135}")
print(f"  OB Winners 신규 5종 yearly breakdown (BTC v3 / ETH v11)")
print(f"{'='*135}")

# 각 후보 별 행
print(f"\n{'후보':<42} | {'FULL':>10} | {'MDD':>5} | {'T':>5} | {'WR':>5} | " + " | ".join(f"{y[0]:>8}" for y in YEARS))
print('-' * 135)

for label, sym, p in CONFIGS:
    # Full first
    C.START = '2020-09-14'; C.END = '2026-04-23'
    trades_all, cap_all, mdd_all = run_backtest(symbol=sym, tf='5m', **p)
    ret_all = (cap_all/C.INITIAL_CAPITAL-1)*100
    wins_all = sum(1 for t in trades_all if t['pnl']>0)
    wr_all = wins_all/len(trades_all)*100 if trades_all else 0

    # Yearly
    yearly_rets = []
    for yname, ys, ye in YEARS:
        C.START = ys; C.END = ye
        try:
            trades_y, cap_y, mdd_y = run_backtest(symbol=sym, tf='5m', **p)
            ret_y = (cap_y/C.INITIAL_CAPITAL-1)*100
            yearly_rets.append(ret_y)
        except Exception as e:
            yearly_rets.append(None)

    row = f"{label:<42} | {fmt(ret_all):>10} | {mdd_all*100:>4.1f}% | {len(trades_all):>5} | {wr_all:>4.1f}% | "
    row += " | ".join(f"{fmt(r) if r is not None else 'ERR':>8}" for r in yearly_rets)
    print(row)

print()
print(f"{'='*135}")
print(f"  요약: BT optimizer 결과 vs 재실행 (FULL) 차이 / MDD / Trades / WR / yearly 분포")
print(f"{'='*135}")

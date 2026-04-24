"""
SOL 15m  MDD ≤ 50%  Top 1 (v6_1 — HTF + Single TP, 1m entry-bar resolve)

1m resolve 반영 후 최적 파라미터:
  Return +9.25e+13%  MDD 48.51%  Trades 9263  WR 56.22%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.003, rr=1.2, max_wait=10, risk_per_trade=0.03,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_25_SOL_15m_mdd50_v6_1_1m.csv')
    print_summary(trades, cap, mdd)

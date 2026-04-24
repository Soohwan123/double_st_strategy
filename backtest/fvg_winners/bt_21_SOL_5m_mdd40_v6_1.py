"""
SOL 5m  MDD ≤ 40%  Top 1 (v6_1 — HTF + Single TP)
Return +1.05e+09%  MDD 36.25%  Trades 23094  WR 43.68%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '5m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.003, rr=1.8, max_wait=15, risk_per_trade=0.01,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_21_SOL_5m_mdd40_v6_1.csv')
    print_summary(trades, cap, mdd)

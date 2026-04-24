"""
SOL 15m  MDD ≤ 40%  Top 1 (v6_2 — HTF + Single TP, refined grid)
Return +5.01e+12%  MDD 38.26%  Trades 7964  WR 44.30%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '15m'; VERSION = 'v6_2'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.004, rr=1.9, max_wait=10, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_19_SOL_15m_mdd40_v6_2.csv')
    print_summary(trades, cap, mdd)

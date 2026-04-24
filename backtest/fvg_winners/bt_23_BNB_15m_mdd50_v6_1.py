"""
BNB 15m  MDD ≤ 50%  Top 1 (v6_1 — HTF + Single TP)
Return +1.18e+06%  MDD 47.70%  Trades 6983  WR 42.86%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BNBUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.8, max_wait=25, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_23_BNB_15m_mdd50_v6_1.csv')
    print_summary(trades, cap, mdd)

"""
XRP 15m  MDD ≤ 40%  Top 1 (v6_1 — HTF + Single TP, 1m entry-bar resolve)

  Return +7.77e+06%  MDD 39.70%  Trades 8925  WR 54.39%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'XRPUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.004, rr=1.2, max_wait=20, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_26_XRP_15m_mdd40_v6_1_1m.csv')
    print_summary(trades, cap, mdd)

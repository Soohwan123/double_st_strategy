"""
ETH 15m  MDD ≤ 50%  Top 1 (v3 — no HTF, Single TP, 1m entry-bar resolve)

  Return +3.40e+07%  MDD 47.42%  Trades 10857  WR 47.14%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '15m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_28_ETH_15m_mdd50_v3_1m.csv')
    print_summary(trades, cap, mdd)

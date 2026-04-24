"""
ETH 15m  MDD ≤ 50%  Top 1
Return +296,432,686%  MDD 49.96%  Trades 9501  WR 50.74%
Version: v4 (no HTF, Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '15m'; VERSION = 'v4'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.006, rr=1.3, max_wait=3, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_11_ETH_15m_mdd50.csv')
    print_summary(trades, cap, mdd)

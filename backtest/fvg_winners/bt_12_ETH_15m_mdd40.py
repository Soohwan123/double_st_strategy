"""
ETH 15m  MDD ≤ 40%  Top 1
Return +1,499,087%  MDD 39.74%  Trades 9855  WR 46.28%
Version: v3
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '15m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=120, risk_per_trade=0.015,
        min_fvg_pct=0.0005,
    )
    save_trades(trades, 'trades_bt_12_ETH_15m_mdd40.csv')
    print_summary(trades, cap, mdd)

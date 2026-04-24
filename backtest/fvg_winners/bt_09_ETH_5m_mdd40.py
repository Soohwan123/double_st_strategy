"""
ETH 5m  MDD ≤ 40%  Top 1
Return +15,402%  MDD 39.98%  Trades 10955  WR 44.03%
Version: v3 (no HTF, Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '5m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.009, rr=1.5, max_wait=30, risk_per_trade=0.005,
        min_fvg_pct=0.0002,
    )
    save_trades(trades, 'trades_bt_09_ETH_5m_mdd40.csv')
    print_summary(trades, cap, mdd)

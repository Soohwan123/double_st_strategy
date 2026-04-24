"""
ETH 5m  MDD ≤ 60%  Top 1
Return +804,757%  MDD 53.33%  Trades 11201  WR 44.37%
Version: v5 (no HTF, Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '5m'; VERSION = 'v5'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.009, rr=1.5, max_wait=15, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_07_ETH_5m_mdd60.csv')
    print_summary(trades, cap, mdd)

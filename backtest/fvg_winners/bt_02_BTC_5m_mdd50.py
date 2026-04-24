"""
BTC 5m  MDD ≤ 50%  Top 1
Return +43,932%  MDD 49.45%  Trades 6495  WR 28.76%
Version: v7_partial
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BTCUSDT'; TF = '5m'; VERSION = 'v7_partial'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.006, rr1=0.5, rr2=3.0, be_after_tp1=0,
        max_wait=15, risk_per_trade=0.025,
    )
    save_trades(trades, 'trades_bt_02_BTC_5m_mdd50.csv')
    print_summary(trades, cap, mdd)

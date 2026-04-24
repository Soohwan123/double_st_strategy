"""
BTC 5m  MDD ≤ 60%  Top 1
Return +123,087%  MDD 59.82%  Trades 7503  WR 32.71%
Version: v7_partial (HTF 1h EMA200 + Partial TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BTCUSDT'
TF = '5m'
VERSION = 'v7_partial'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.006,
        rr1=0.8, rr2=2.5, be_after_tp1=0,
        max_wait=15,
        risk_per_trade=0.025,
    )
    save_trades(trades, 'trades_bt_01_BTC_5m_mdd60.csv')
    print_summary(trades, cap, mdd)

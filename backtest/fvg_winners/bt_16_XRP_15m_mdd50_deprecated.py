"""
XRP 15m  MDD ≤ 50%  Top 1
Return +168,999,908%  MDD 49.77%  Trades 9295  WR 28.93%
Version: v7_partial (HTF + Partial TP + BE after TP1)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'XRPUSDT'; TF = '15m'; VERSION = 'v7_partial'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.0055, rr1=0.5, rr2=1.5, be_after_tp1=1,
        max_wait=20, risk_per_trade=0.03,
    )
    save_trades(trades, 'trades_bt_16_XRP_15m_mdd50.csv')
    print_summary(trades, cap, mdd)

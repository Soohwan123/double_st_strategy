"""
XRP 15m  MDD ≤ 60%  Top 1
Return +1,017,996,472%  MDD 57.51%  Trades 8176  WR 49.61%
Version: v6_2 (HTF 1h EMA200 + Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'XRPUSDT'; TF = '15m'; VERSION = 'v6_2'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.0045, rr=1.4, max_wait=15, risk_per_trade=0.025,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_15_XRP_15m_mdd60.csv')
    print_summary(trades, cap, mdd)

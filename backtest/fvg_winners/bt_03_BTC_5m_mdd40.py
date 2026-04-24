"""
BTC 5m  MDD ≤ 40%  Top 1
Return +1,917%  MDD 38.81%  Trades 4847  WR 43.94%
Version: v6_htf (HTF 1h EMA200 + Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BTCUSDT'; TF = '5m'; VERSION = 'v6_htf'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.012, rr=1.5, max_wait=5, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_03_BTC_5m_mdd40.csv')
    print_summary(trades, cap, mdd)

"""
BTC 15m  MDD ≤ 40%  Top 1
Return +693,392%  MDD 34.88%  Trades 8750  WR 52.91%
Version: v6_1
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BTCUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.003, rr=1.3, max_wait=25, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_06_BTC_15m_mdd40.csv')
    print_summary(trades, cap, mdd)

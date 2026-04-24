"""
ETH 15m  MDD ≤ 60%  Top 1
Return +9,695,115,885%  MDD 55.84%  Trades 10960  WR 47.52%
Version: v3
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '15m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=20, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_10_ETH_15m_mdd60.csv')
    print_summary(trades, cap, mdd)

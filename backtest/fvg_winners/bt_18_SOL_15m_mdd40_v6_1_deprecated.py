"""
SOL 15m  MDD ≤ 40%  Top 1 (v6_1 — HTF + Single TP)
Return +2.38e+14%  MDD 39.94%  Trades 8001  WR 47.09%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.004, rr=1.7, max_wait=7, risk_per_trade=0.025,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_18_SOL_15m_mdd40_v6_1.csv')
    print_summary(trades, cap, mdd)

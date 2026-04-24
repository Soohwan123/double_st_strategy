"""
SOL 15m  MDD ≤ 40%  Top 1 (v3 — no HTF, Single TP)
Return +6.36e+14%  MDD 37.72%  Trades 12367  WR 48.81%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '15m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=60, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_17_SOL_15m_mdd40_v3.csv')
    print_summary(trades, cap, mdd)

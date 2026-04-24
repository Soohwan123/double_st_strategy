"""
SOL 5m  MDD ≤ 50%  Top 1 (v3 — no HTF, Single TP)
Return +5.13e+09%  MDD 46.46%  Trades 27498  WR 46.52%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '5m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.01,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_20_SOL_5m_mdd50_v3.csv')
    print_summary(trades, cap, mdd)

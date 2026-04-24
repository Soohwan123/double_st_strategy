"""
BNB 15m  MDD ≤ 50%  Top 1 (v3 — no HTF, Single TP)
Return +1.41e+07%  MDD 41.16%  Trades 10189  WR 47.18%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BNBUSDT'; TF = '15m'; VERSION = 'v3'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.015,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_22_BNB_15m_mdd50_v3.csv')
    print_summary(trades, cap, mdd)

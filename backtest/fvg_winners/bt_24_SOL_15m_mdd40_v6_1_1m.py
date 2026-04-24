"""
SOL 15m  MDD ≤ 40%  Top 1 (v6_1 — HTF + Single TP, 1m entry-bar resolve)

1m resolve 반영 후 최적 파라미터 (기존 bt_18 deprecated):
  Return +4.46e+10%  MDD 39.60%  Trades 9193  WR 54.12%
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.003, rr=1.3, max_wait=12, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_24_SOL_15m_mdd40_v6_1_1m.csv')
    print_summary(trades, cap, mdd)

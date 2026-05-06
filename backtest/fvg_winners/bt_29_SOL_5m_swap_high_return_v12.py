"""
SOL 5m SWAP — High Return winner (v12 ultra-fine 결과)

  Return +47,766.7%  MDD 67.7%  Trades 5,227  WR 41.9%
  파라미터: BUF=0.02 RR=1.6 W=19 RPT=0.003 MFP=0.002

코드: SWAP variant (LIMIT entry, entry-before-invalidation, 1m intrabar resolve, no HTF)
"""
from _common_swap import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '5m'; VERSION = 'v3'  # no HTF

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.02, rr=1.6, max_wait=19, risk_per_trade=0.003,
        min_fvg_pct=0.002,
    )
    save_trades(trades, 'trades_bt_29_SOL_5m_swap_high_return_v12.csv')
    print_summary(trades, cap, mdd)

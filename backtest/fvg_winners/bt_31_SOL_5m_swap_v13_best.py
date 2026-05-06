"""
SOL 5m SWAP — v13 ultra-fine 최고 winner

  Return +63,640.9%  MDD 62.2%  Trades 5,086  WR 42.2%
  파라미터: BUF=0.0205 RR=1.59 W=17 RPT=0.003 MFP=0.002

v12 best (+47,766% MDD 67.7%) 대비:
  - 수익 +33% 향상
  - MDD 5.5%p 동시 개선
  - Trades 5,086 (~140 적음)

코드: SWAP variant (LIMIT entry, entry-before-invalidation, 1m intrabar resolve, no HTF)
"""
from _common_swap import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '5m'; VERSION = 'v3'  # no HTF

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.0205, rr=1.59, max_wait=17, risk_per_trade=0.003,
        min_fvg_pct=0.002,
    )
    save_trades(trades, 'trades_bt_31_SOL_5m_swap_v13_best.csv')
    print_summary(trades, cap, mdd)

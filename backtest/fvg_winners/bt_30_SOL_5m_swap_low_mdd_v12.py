"""
SOL 5m SWAP — Low MDD winner (v12 ultra-fine 결과)

  Return +46,829.2%  MDD 63.6%  Trades 5,123  WR 42.2%
  파라미터: BUF=0.0205 RR=1.58 W=17 RPT=0.003 MFP=0.002
  (수익은 high_return 대비 1.9% 낮지만 MDD 4.1%p 더 안정)

코드: SWAP variant (LIMIT entry, entry-before-invalidation, 1m intrabar resolve, no HTF)
"""
from _common_swap import run_backtest, save_trades, print_summary

SYMBOL = 'SOLUSDT'; TF = '5m'; VERSION = 'v3'  # no HTF

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.0205, rr=1.58, max_wait=17, risk_per_trade=0.003,
        min_fvg_pct=0.002,
    )
    save_trades(trades, 'trades_bt_30_SOL_5m_swap_low_mdd_v12.csv')
    print_summary(trades, cap, mdd)

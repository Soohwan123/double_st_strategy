"""
SOL 5m TrendBreak v2 Trendline-SL best (v2n6 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +131,436%  MDD 68.9%  Trades 1,228  WR 40.2%
    LENGTH=36 MULT=2.4 MIN_SL_ATR=3.15 RR=1.92 RPT=0.025
  Yearly: y0+89 y1+300 y2+428 y3+254 y4+8 y5+474 y6+50 (y0~y5 모두 양수, GOAL +100K% 만족)
"""
from _common_v2 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='SOLUSDT', tf='5m',
        length=36, mult=2.4, min_sl_atr=3.15, rr=1.92, risk_per_trade=0.025,
    )
    save_trades(trades, 'trades_bt_05_SOL_5m_v2_trendsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

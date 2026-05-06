"""
SOL 15m TrendBreak v3 Swing-SL best (v3n7 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +13,383%  MDD 63.8%  Trades 1,225  WR 80%
    LENGTH=30 MULT=1.4 MIN_SL_ATR=4.7 RR=0.33 RPT=0.055
  Yearly: y0+18 y1+379 y2+8 y3+91 y4+342 y5+189 y6-10 (y0~y5 모두 양수, y3-6 sum=+612)
  Note: y4(2024) +342, y5(2025) +189 — recent 강함. y6 -10 (partial)
"""
from _common_v3 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='SOLUSDT', tf='15m',
        length=30, mult=1.4, min_sl_atr=4.7, rr=0.33, risk_per_trade=0.055,
    )
    save_trades(trades, 'trades_bt_10_SOL_15m_v3_swingsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

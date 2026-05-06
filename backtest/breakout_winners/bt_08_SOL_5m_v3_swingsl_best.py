"""
SOL 5m TrendBreak v3 Swing-SL best (v3n7 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +95,734%  MDD 67.6%  Trades 1,268  WR 44%
    LENGTH=7 MULT=1.92 MIN_SL_ATR=5.32 RR=1.57 RPT=0.006
  Yearly: y0+31 y1+992 y2+272 y3+357 y4+126 y5+19 y6+46 (y0~y5 모두 양수, y3-6 sum=+548)
  Note: SOL v2 (+131K) 다음으로 강한 SOL winner. v3 변형이라 SL 정의 달라 (swing low/high)
"""
from _common_v3 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='SOLUSDT', tf='5m',
        length=7, mult=1.92, min_sl_atr=5.32, rr=1.57, risk_per_trade=0.006,
    )
    save_trades(trades, 'trades_bt_08_SOL_5m_v3_swingsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

"""
ETH 5m TrendBreak v3 Swing-SL best (v3n7 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +44,441%  MDD 69.3%  Trades 1,532  WR 79%
    LENGTH=72 MULT=0.91 MIN_SL_ATR=7.0 RR=0.35 RPT=0.092
  Yearly: y0+272 y1+4 y2+494 y3+8 y4+1107 y5+53 y6-2 (y0~y5 모두 양수, y3-6 sum=+1,165)
  Note: y4(2024)에 +1,107% 폭발. WR 79% 매우 높음 (low RR/SL 영역)
"""
from _common_v3 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='ETHUSDT', tf='5m',
        length=72, mult=0.91, min_sl_atr=7.0, rr=0.35, risk_per_trade=0.092,
    )
    save_trades(trades, 'trades_bt_09_ETH_5m_v3_swingsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

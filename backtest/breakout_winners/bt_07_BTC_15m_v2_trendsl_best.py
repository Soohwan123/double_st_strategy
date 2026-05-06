"""
BTC 15m TrendBreak v2 Trendline-SL best (v2n12 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +4,328%  MDD 61.0%  Trades 1,238  WR ~43%
    LENGTH=24 MULT=8.13 MIN_SL_ATR=4.22 RR=1.72 RPT=0.036
  Yearly: y0+161 y1+118 y2+2 y3+115 y4+12 y5+53 y6+108 (y0~y5 모두 양수, y3-6 sum=+288)
"""
from _common_v2 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='BTCUSDT', tf='15m',
        length=24, mult=8.13, min_sl_atr=4.22, rr=1.72, risk_per_trade=0.036,
    )
    save_trades(trades, 'trades_bt_07_BTC_15m_v2_trendsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

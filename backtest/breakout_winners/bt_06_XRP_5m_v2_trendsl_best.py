"""
XRP 5m TrendBreak v2 Trendline-SL best (v2n13 narrow)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +34,543%  MDD 45.1%  Trades 1,044  WR ~68%
    LENGTH=61 MULT=0.35 MIN_SL_ATR=4.72 RR=0.5805 RPT=0.0001
  Yearly: y0+676 y1+482 y2+10 y3+171 y4+32 y5+66 y6+17 (y0~y5 모두 양수)
"""
from _common_v2 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='XRPUSDT', tf='5m',
        length=61, mult=0.35, min_sl_atr=4.72, rr=0.5805, risk_per_trade=0.0001,
    )
    save_trades(trades, 'trades_bt_06_XRP_5m_v2_trendsl_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

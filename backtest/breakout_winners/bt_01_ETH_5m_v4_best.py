"""
ETH 5m TrendBreak v4 narrow best
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +104,725%  MDD 69.5%  Trades 1,040  WR 13.6%
    LENGTH=190 MULT=0.5 SL_ATR=2.5 RR=11.0 RPT=0.03
  Yearly: y0+474 y1+263 y2+316 y3+187 y4+136 y5+51 y6+18 (모든 해 양수, min +18%)
"""
from _common import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='ETHUSDT', tf='5m',
        length=190, mult=0.5, sl_atr_mult=2.5, rr=11.0, risk_per_trade=0.03,
    )
    save_trades(trades, 'trades_bt_01_ETH_5m_v4_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

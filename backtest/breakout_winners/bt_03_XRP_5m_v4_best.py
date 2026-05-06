"""
XRP 5m TrendBreak v4 narrow best
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +132,516%  MDD 66.8%  Trades 1,157  WR 40.4%
    LENGTH=150 MULT=1.1 SL_ATR=7.0 RR=2.0 RPT=0.06
  Yearly: y0+61 y1+976 y2+317 y3+43 y4+194 y5+130 y6+91 (모든 해 양수, min +43%)
"""
from _common import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='XRPUSDT', tf='5m',
        length=150, mult=1.1, sl_atr_mult=7.0, rr=2.0, risk_per_trade=0.06,
    )
    save_trades(trades, 'trades_bt_03_XRP_5m_v4_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

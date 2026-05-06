"""
SOL 5m TrendBreak v4 narrow best
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +293,024%  MDD 69.2%  Trades 1,011  WR 57.3%
    LENGTH=180 MULT=0.47 SL_ATR=4.2 RR=1.1 RPT=0.08
  Yearly: y0+19 y1+343 y2+271 y3+54 y4+524 y5+507 y6+156 (모든 해 양수, min +19%)
"""
from _common import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='SOLUSDT', tf='5m',
        length=180, mult=0.47, sl_atr_mult=4.2, rr=1.1, risk_per_trade=0.08,
    )
    save_trades(trades, 'trades_bt_02_SOL_5m_v4_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

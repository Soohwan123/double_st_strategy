"""
SOL 15m TrendBreak T≥2000 phase v10/v11 best (CEILING)
  Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
    +20,200%  MDD 70.0%  Trades 2,922  WR ~66%
    LENGTH=25 MULT=1.112 SL_ATR=3.5 RR=0.63 RPT=0.0595
  Yearly: y0+49 y1+855 y2+103 y3+135 y4+8 y5+96 y6+42 (y0~y5 양수, y6 partial)
  Note: T≥2000 + y0~y5 모두 양수 조건 하에서 도달한 ceiling. v10=v11 동일 결과.
"""
from _common import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='SOLUSDT', tf='15m',
        length=25, mult=1.112, sl_atr_mult=3.5, rr=0.63, risk_per_trade=0.0595,
    )
    save_trades(trades, 'trades_bt_04_SOL_15m_t2k_v10_best.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

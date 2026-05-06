"""
ETH 15m TrendBreak v4 Trailing+ATR (천문학 수익형, 검증 필요)
  Optimizer wide v4 결과 (전체기간 2020-01-06 ~ 2026-04-23):
    +1,362,311,033,452% (1.4조%)  MDD 48.6%  Trades 1,213  WR 49%
    LENGTH=60 MULT=0.35 SL_ATR_MULT=0.5 TRAIL_ATR_MULT=1.0 RPT=0.05
  Yearly (wide opt 기록): y0+10k y1+50 y2+9k y3+360k y4+280 y5+1k y6+354
  Note: y3=+360,367% 단일 해 폭발. 거래기록 점검 필요.
"""
from _common_v4 import run_backtest, save_trades, print_summary, yearly_breakdown

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol='ETHUSDT', tf='15m',
        length=60, mult=0.35, sl_atr_mult=0.5, trail_atr_mult=1.0, risk_per_trade=0.05,
    )
    save_trades(trades, 'trades_bt_13_ETH_15m_v4_trail.csv')
    print_summary(trades, cap, mdd)
    yearly_breakdown(trades)

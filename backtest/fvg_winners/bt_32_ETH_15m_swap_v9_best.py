"""
ETH 15m FVG SWAP — v9 best (saturation 정점)

Optimizer (전체기간 2020-01-06 ~ 2026-04-23):
  +65,427%  MDD 70.0%  Trades 1,558  WR 55%
  MFP=0.000332 BUF=0.05 RR=0.72 W=10 RPT=0.10
Optimizer Yearly (year boundaries: 365일 단위, 모든 해 양수 min +2.3%):
  y0(20-21):  +1564%   y1(21-22):  +685%   y2(22-23):    +2%
  y3(23-24):    +23%   y4(24-25):   +64%   y5(25-26):   +18%
  y6(26-PT):   +62%

bt 검증 (calendar year, INITIAL_CAPITAL=1000):
  Total: T=1,536 WR=63.1% MDD=70.0% Final=$491,726 (+49,073%)
  2020: T=278 WR=66.2% endbal=$13,246    ret=+1,225%
  2021: T=477 WR=63.5% endbal=$130,613   ret=  +886%
  2022: T=278 WR=60.8% endbal=$133,559   ret=    +2%
  2023: T= 71 WR=63.4% endbal=$182,705   ret=   +37%
  2024: T=175 WR=62.9% endbal=$342,977   ret=   +88%
  2025: T=217 WR=61.3% endbal=$403,440   ret=   +18%
  2026: T= 40 WR=62.5% endbal=$491,726   ret=   +22%   (~3.7개월 partial)

코드: SWAP variant + 1m intrabar resolve + LIQ>SL>ENTRY>TP 보수 우선순위.
"""
from _common_swap import run_backtest, save_trades, print_summary

SYMBOL = 'ETHUSDT'; TF = '15m'; VERSION = 'v3'  # no HTF, single TP

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.05, rr=0.72, max_wait=10, risk_per_trade=0.10,
        min_fvg_pct=0.000332,
    )
    save_trades(trades, 'trades_bt_32_ETH_15m_swap_v9_best.csv')
    print_summary(trades, cap, mdd)

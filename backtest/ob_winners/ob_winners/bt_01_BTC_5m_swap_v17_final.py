"""
BTC 5m OB SWAP — v17 nano final winner (saturation 도달)

Optimizer (전체기간 2020-2026):
  +46,075%  MDD 69.6%  Trades 1,325  WR 66.34%
  IL=38 IP=0.010 BUF=0.0278 RR=0.655 W=50 RPT=0.083
Yearly (모든 해 양수, min +39%):
  y0(20-21):  +740%
  y1(21-22):  +129%
  y2(22-23):   +87%
  y3(23-24):   +67%
  y4(24-25):  +284%
  y5(25-26):   +44%
  y6(26-PT):   +39%

코드: SWAP variant + 1m intrabar resolve + LIQ>SL>ENTRY>TP 보수 우선순위.
"""
import sys
sys.path.insert(0, '.')
import _common_swap as M
M.START = '2020-01-06'  # 전체기간

if __name__ == '__main__':
    trades, cap, mdd = M.run_backtest(
        symbol='BTCUSDT', tf='5m',
        impulse_lookback=38, impulse_min_pct=0.010,
        sl_buffer_pct=0.0278, rr=0.655, max_wait=50, risk_per_trade=0.083,
        use_htf=True,
    )
    M.save_trades(trades, 'trades_bt_01_BTC_5m_swap_v17_final.csv')
    M.print_summary(trades, cap, mdd)

    import pandas as pd
    df = pd.DataFrame(trades)
    if len(df) > 0:
        df['et'] = pd.to_datetime(df['entry_time'])
        df['year'] = df['et'].dt.year
        print('\n=== Yearly breakdown ===')
        for y, g in df.groupby('year'):
            wr = (g['pnl'] > 0).mean() * 100
            print(f'  {y}: trades={len(g):4d} WR={wr:5.1f}% pnl_sum={g["pnl"].sum():+12.2f}')
        df = df.sort_values('et').reset_index(drop=True)
        df['gap_days'] = df['et'].diff().dt.total_seconds() / 86400
        big = df[df['gap_days'] >= 7]
        print(f'\n=== Trade gaps >= 7 days: {len(big)} ===')
        if len(big) > 0:
            print(big[['entry_time','gap_days']].to_string(index=False))

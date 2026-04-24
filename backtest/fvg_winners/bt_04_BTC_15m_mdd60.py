"""
BTC 15m  MDD ≤ 60%  Top 1
Return +1,078,408,421%  MDD 57.51%  Trades 8750  WR 52.91%
Version: v6_1 (HTF 1h EMA200 + Single TP)
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'BTCUSDT'; TF = '15m'; VERSION = 'v6_1'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.003, rr=1.3, max_wait=25, risk_per_trade=0.03,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_04_BTC_15m_mdd60.csv')
    print_summary(trades, cap, mdd)

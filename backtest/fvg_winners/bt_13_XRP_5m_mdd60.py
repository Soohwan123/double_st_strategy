"""
XRP 5m  MDD ≤ 60%  Top 1
Return +3,851,298,137%  MDD 54.20%  Trades 20451  WR 55.52%
Version: v4
"""
from _common import run_backtest, save_trades, print_summary

SYMBOL = 'XRPUSDT'; TF = '5m'; VERSION = 'v4'

if __name__ == '__main__':
    trades, cap, mdd = run_backtest(
        symbol=SYMBOL, tf=TF, version=VERSION,
        sl_buffer_pct=0.008, rr=1.0, max_wait=15, risk_per_trade=0.02,
        min_fvg_pct=0.0,
    )
    save_trades(trades, 'trades_bt_13_XRP_5m_mdd60.csv')
    print_summary(trades, cap, mdd)

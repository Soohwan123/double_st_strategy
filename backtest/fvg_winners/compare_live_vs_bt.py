"""Live vs Backtest 중간점검 비교.

- INITIAL_CAPITAL=200, MAX_LEV=5 로 오버라이드
- 3 심볼 (ETH/XRP/SOL) bt_28/bt_27/bt_25 파라미터 사용
- entry_time >= 2026-04-24 12:15:00 UTC 거래만 비교
- live trades CSV 와 trade-by-trade 매칭
"""
import sys
import os
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _common  # noqa
_common.INITIAL_CAPITAL = 200.0
_common.MAX_LEV = 5.0
_common.START = '2026-04-01'
_common.END = '2026-04-27'

from _common import run_backtest  # after override

CUTOFF = pd.Timestamp('2026-04-24 12:15:00')
LIVE_DIR = '/home/double_st_strategy/fvg_strategy/trades'

CONFIGS = [
    {
        'symbol': 'ETHUSDT', 'tf': '15m', 'version': 'v3',
        'sl_buffer_pct': 0.005, 'rr': 1.5, 'max_wait': 10, 'risk_per_trade': 0.015,
        'min_fvg_pct': 0.0,
        'live_csv': 'trades_fvg_eth.csv',
    },
    {
        'symbol': 'XRPUSDT', 'tf': '15m', 'version': 'v6_1',
        'sl_buffer_pct': 0.004, 'rr': 1.2, 'max_wait': 20, 'risk_per_trade': 0.02,
        'min_fvg_pct': 0.0,
        'live_csv': 'trades_fvg_xrp.csv',
    },
    {
        'symbol': 'SOLUSDT', 'tf': '15m', 'version': 'v6_1',
        'sl_buffer_pct': 0.003, 'rr': 1.2, 'max_wait': 10, 'risk_per_trade': 0.03,
        'min_fvg_pct': 0.0,
        'live_csv': 'trades_fvg_sol.csv',
    },
]


def load_live(csv_name):
    path = os.path.join(LIVE_DIR, csv_name)
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_localize(None)
    return df


def pair_live_trades(live_df):
    """ENTRY + matching exit -> trade rows."""
    trades = []
    open_entry = None
    for _, row in live_df.iterrows():
        if row['type'] == 'ENTRY':
            open_entry = row
        elif row['type'] in ('TP', 'SL', 'LIQ'):
            if open_entry is None:
                continue
            trades.append({
                'entry_time': open_entry['timestamp'],
                'exit_time': row['timestamp'],
                'direction': open_entry['direction'],
                'entry_price': open_entry['price'],
                'exit_price': row['price'],
                'tp': open_entry['take_profit'],
                'sl': open_entry['stop_loss'],
                'lev': open_entry['leverage'],
                'pnl': row['pnl'],
                'reason': row['type'],
                'cap_after': row['capital'],
            })
            open_entry = None
    # leftover open entry
    if open_entry is not None:
        trades.append({
            'entry_time': open_entry['timestamp'],
            'exit_time': None, 'direction': open_entry['direction'],
            'entry_price': open_entry['price'], 'exit_price': None,
            'tp': open_entry['take_profit'], 'sl': open_entry['stop_loss'],
            'lev': open_entry['leverage'], 'pnl': None, 'reason': 'OPEN',
            'cap_after': None,
        })
    return pd.DataFrame(trades)


def filter_bt(trades_df):
    if 'entry_time' not in trades_df.columns:
        return trades_df.iloc[0:0]
    df = trades_df.copy()
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    return df[df['entry_time'] >= CUTOFF].reset_index(drop=True)


def fmt(ts):
    if ts is None or pd.isna(ts):
        return '         OPEN        '
    return pd.Timestamp(ts).strftime('%m-%d %H:%M')


def compare_one(cfg):
    print(f"\n{'='*80}")
    print(f"  {cfg['symbol']}  ({cfg['version']}, RR={cfg['rr']}, SL_BUF={cfg['sl_buffer_pct']}, "
          f"MAX_WAIT={cfg['max_wait']}, RPT={cfg['risk_per_trade']})")
    print(f"  CAPITAL=$200, MAX_LEV=5x")
    print('='*80)

    bt_trades_raw, bt_cap, bt_mdd = run_backtest(
        symbol=cfg['symbol'], tf=cfg['tf'], version=cfg['version'],
        sl_buffer_pct=cfg['sl_buffer_pct'], rr=cfg['rr'],
        max_wait=cfg['max_wait'], risk_per_trade=cfg['risk_per_trade'],
        min_fvg_pct=cfg['min_fvg_pct'],
    )

    bt_df = pd.DataFrame(bt_trades_raw)
    bt_period = filter_bt(bt_df)

    live_raw = load_live(cfg['live_csv'])
    live_paired = pair_live_trades(live_raw)
    live_period = live_paired[live_paired['entry_time'] >= CUTOFF].reset_index(drop=True)

    print(f"\n[BACKTEST] period trades: {len(bt_period)}, final cap: ${bt_cap:.2f}")
    print(f"[LIVE]     period trades: {len(live_period)}")

    if len(bt_period):
        print("\n  BT  trades (period):")
        for _, t in bt_period.iterrows():
            d = 'LONG' if t.get('direction', t.get('side', 0)) in (1, 'LONG') else 'SHORT'
            ep = t.get('entry_price', t.get('ep'))
            xp = t.get('exit_price', t.get('xp'))
            sl = t.get('stop_loss', t.get('sl'))
            tp = t.get('take_profit', t.get('tp'))
            r = t.get('reason', '?')
            pnl = t.get('pnl', 0)
            print(f"    {fmt(t.get('entry_time'))} → {fmt(t.get('exit_time'))} {d:5s} "
                  f"ep={ep:.5g} xp={xp:.5g} SL={sl:.5g} TP={tp:.5g} {r:4s} pnl=${pnl:+.2f}")

    if len(live_period):
        print("\n  LIVE trades (period):")
        for _, t in live_period.iterrows():
            print(f"    {fmt(t['entry_time'])} → {fmt(t['exit_time'])} {t['direction']:5s} "
                  f"ep={t['entry_price']:.5g} xp={(t['exit_price'] if t['exit_price'] else 0):.5g} "
                  f"SL={(t['sl'] if pd.notna(t['sl']) else 0):.5g} TP={(t['tp'] if pd.notna(t['tp']) else 0):.5g} "
                  f"{t['reason']:4s} pnl={('$%+.2f' % t['pnl']) if t['pnl'] is not None and pd.notna(t['pnl']) else 'OPEN'}")

    # match attempt
    print("\n  매칭 결과:")
    n = max(len(bt_period), len(live_period))
    for i in range(n):
        b = bt_period.iloc[i] if i < len(bt_period) else None
        l = live_period.iloc[i] if i < len(live_period) else None
        if b is None:
            print(f"    [{i+1}] BT 없음 / LIVE {fmt(l['entry_time'])} {l['direction']} ep={l['entry_price']}")
            continue
        if l is None:
            d = 'LONG' if b.get('direction', b.get('side', 0)) in (1, 'LONG') else 'SHORT'
            print(f"    [{i+1}] BT  {fmt(b.get('entry_time'))} {d} ep={b.get('entry_price', b.get('ep')):.5g} / LIVE 없음")
            continue
        bt_dir = 'LONG' if b.get('direction', b.get('side', 0)) in (1, 'LONG') else 'SHORT'
        bt_ep = b.get('entry_price', b.get('ep'))
        bt_et = pd.Timestamp(b.get('entry_time'))
        l_et = pd.Timestamp(l['entry_time'])
        et_match = abs((bt_et - l_et).total_seconds()) <= 15 * 60
        ep_match = abs(bt_ep - l['entry_price']) / l['entry_price'] < 0.001
        dir_match = bt_dir == l['direction']
        ok = '✅' if (et_match and ep_match and dir_match) else '⚠️'
        print(f"    [{i+1}] {ok} entry={fmt(bt_et)} BT/{fmt(l_et)} LIVE  dir={bt_dir}/{l['direction']}  "
              f"ep={bt_ep:.5g}/{l['entry_price']:.5g}")

    return {'symbol': cfg['symbol'], 'bt_n': len(bt_period), 'live_n': len(live_period),
            'bt_cap': bt_cap}


if __name__ == '__main__':
    results = []
    for cfg in CONFIGS:
        r = compare_one(cfg)
        results.append(r)
    print("\n" + "=" * 80)
    print("  요약")
    print("=" * 80)
    for r in results:
        print(f"  {r['symbol']:10s}  BT trades={r['bt_n']}, LIVE trades={r['live_n']}, BT cap=${r['bt_cap']:.2f}")

"""SWAP 버전 (entry before invalidation) 으로 백테스트 재실행 후 LIVE/원본 BT 와 비교.

CAP=$200, MAX_LEV=5x.
"""
import sys, os
import importlib
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _common as orig
import _common_swap as swap

for mod in (orig, swap):
    mod.INITIAL_CAPITAL = 200.0
    mod.MAX_LEV = 5.0
    mod.START = '2026-04-01'
    mod.END = '2026-04-27'

CUTOFF = pd.Timestamp('2026-04-24 12:15:00')
LIVE_DIR = '/home/double_st_strategy/fvg_strategy/trades'

CONFIGS = [
    dict(symbol='ETHUSDT', tf='15m', version='v3',
         sl_buffer_pct=0.005, rr=1.5, max_wait=10, risk_per_trade=0.015,
         min_fvg_pct=0.0, live_csv='trades_fvg_eth.csv'),
    dict(symbol='XRPUSDT', tf='15m', version='v6_1',
         sl_buffer_pct=0.004, rr=1.2, max_wait=20, risk_per_trade=0.02,
         min_fvg_pct=0.0, live_csv='trades_fvg_xrp.csv'),
    dict(symbol='SOLUSDT', tf='15m', version='v6_1',
         sl_buffer_pct=0.003, rr=1.2, max_wait=10, risk_per_trade=0.03,
         min_fvg_pct=0.0, live_csv='trades_fvg_sol.csv'),
]


def load_live(name):
    df = pd.read_csv(os.path.join(LIVE_DIR, name))
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_localize(None)
    return df


def pair_live(df):
    rows = []
    e = None
    for _, r in df.iterrows():
        if r['type'] == 'ENTRY':
            if e is not None:
                rows.append({'entry_time': e['timestamp'], 'direction': e['direction'],
                             'entry_price': e['price'], 'tp': e['take_profit'],
                             'sl': e['stop_loss'], 'exit_time': None, 'exit_price': None,
                             'reason': 'MISSING_EXIT', 'pnl': None})
            e = r
        elif r['type'] in ('TP', 'SL', 'LIQ'):
            if e is not None:
                rows.append({'entry_time': e['timestamp'], 'direction': e['direction'],
                             'entry_price': e['price'], 'tp': e['take_profit'],
                             'sl': e['stop_loss'], 'exit_time': r['timestamp'],
                             'exit_price': r['price'], 'reason': r['type'], 'pnl': r['pnl']})
                e = None
    if e is not None:
        rows.append({'entry_time': e['timestamp'], 'direction': e['direction'],
                     'entry_price': e['price'], 'tp': e['take_profit'],
                     'sl': e['stop_loss'], 'exit_time': None, 'exit_price': None,
                     'reason': 'OPEN', 'pnl': None})
    return pd.DataFrame(rows)


def run_one(mod, cfg):
    trades, cap, mdd = mod.run_backtest(
        symbol=cfg['symbol'], tf=cfg['tf'], version=cfg['version'],
        sl_buffer_pct=cfg['sl_buffer_pct'], rr=cfg['rr'],
        max_wait=cfg['max_wait'], risk_per_trade=cfg['risk_per_trade'],
        min_fvg_pct=cfg['min_fvg_pct'])
    df = pd.DataFrame(trades)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    return df[df['entry_time'] >= CUTOFF].reset_index(drop=True), cap, mdd


def fmt_t(t):
    if t is None or pd.isna(t):
        return '   OPEN  '
    return pd.Timestamp(t).strftime('%m-%d %H:%M')


def line(t, label):
    if len(t) == 0:
        print(f"    [{label}] (no trades)")
        return
    for _, r in t.iterrows():
        d = r.get('direction', '?')
        ep = r.get('entry_price', 0)
        xp = r.get('exit_price', 0) if pd.notna(r.get('exit_price')) else 0
        sl = r.get('stop_loss', r.get('sl', 0))
        tp = r.get('take_profit', r.get('tp', 0))
        rs = r.get('reason', '?')
        pnl = r.get('pnl', 0)
        pnl_s = f"${pnl:+.2f}" if pd.notna(pnl) else 'OPEN'
        print(f"    [{label}] {fmt_t(r.get('entry_time'))} → {fmt_t(r.get('exit_time'))} "
              f"{d:5s} ep={ep:.5g} xp={xp:.5g} SL={sl:.5g} TP={tp:.5g} {rs:6s} {pnl_s}")


def total_pnl(df):
    if 'pnl' not in df.columns:
        return 0.0
    return df['pnl'].fillna(0).sum()


for cfg in CONFIGS:
    print(f"\n{'='*90}")
    print(f"  {cfg['symbol']}  ({cfg['version']}, RR={cfg['rr']}, SL_BUF={cfg['sl_buffer_pct']}, "
          f"MAX_WAIT={cfg['max_wait']}, RPT={cfg['risk_per_trade']})  CAP=$200, MAX_LEV=5x")
    print('='*90)

    orig_t, orig_cap, _ = run_one(orig, cfg)
    swap_t, swap_cap, _ = run_one(swap, cfg)
    live_t = pair_live(load_live(cfg['live_csv']))
    live_t = live_t[live_t['entry_time'] >= CUTOFF].reset_index(drop=True)

    print(f"\n  [원본 BT  ] trades={len(orig_t)}  기간 PnL=${total_pnl(orig_t):+.2f}")
    line(orig_t, 'BT  ')
    print(f"\n  [SWAP BT  ] trades={len(swap_t)}  기간 PnL=${total_pnl(swap_t):+.2f}")
    line(swap_t, 'SWAP')
    print(f"\n  [LIVE     ] trades={len(live_t)}  기간 PnL=${total_pnl(live_t):+.2f}")
    line(live_t, 'LIVE')

    # 매칭: SWAP vs LIVE
    print(f"\n  [매칭] SWAP vs LIVE")
    n = max(len(swap_t), len(live_t))
    for i in range(n):
        s = swap_t.iloc[i] if i < len(swap_t) else None
        l = live_t.iloc[i] if i < len(live_t) else None
        if s is None:
            print(f"    [{i+1}] SWAP 없음 / LIVE {fmt_t(l['entry_time'])} {l['direction']} ep={l['entry_price']:.5g}")
            continue
        if l is None:
            print(f"    [{i+1}] SWAP {fmt_t(s.get('entry_time'))} {s.get('direction')} ep={s.get('entry_price'):.5g} / LIVE 없음")
            continue
        s_et = pd.Timestamp(s.get('entry_time'))
        l_et = pd.Timestamp(l['entry_time'])
        et_match = abs((s_et - l_et).total_seconds()) <= 15 * 60
        ep_match = abs(s.get('entry_price') - l['entry_price']) / l['entry_price'] < 0.001
        dir_match = s.get('direction') == l['direction']
        ok = '✅' if (et_match and ep_match and dir_match) else '⚠️'
        print(f"    [{i+1}] {ok} entry={fmt_t(s_et)} SWAP / {fmt_t(l_et)} LIVE  "
              f"dir={s.get('direction')}/{l['direction']}  ep={s.get('entry_price'):.5g}/{l['entry_price']:.5g}")

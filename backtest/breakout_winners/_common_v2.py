"""
Trendlines with Breaks (LuxAlgo) v2 Trendline-SL — common backtest with trade logging.

Exit (v2):
  - LONG  SL = min(lower_trendline_at_entry, ep - atr*MIN_SL_ATR)  (더 먼 SL 보수)
  - SHORT SL = max(upper_trendline_at_entry, ep + atr*MIN_SL_ATR)
  - TP = entry ± RR × SL_dist
  - 같은 bar SL+TP → SL 우선 (LIQ > SL > TP)
  - 진입봉 다음 (i+1) bar 부터 OHLC 체크, 진입봉 안 SL/TP 무시 (보수)
Sizing/Fees: v1 동일 (taker entry, taker SL, maker TP, MAX_LEV=90)
"""
import os
import numpy as np
import pandas as pd

INITIAL_CAPITAL = 1000.0
TAKER_FEE = 0.0005
MAKER_FEE = 0.0002
MAX_LEV = 90.0
START = '2024-01-06'
END = '2026-04-23'


def load_data(symbol, tf):
    for path in [f'../historical_data/{symbol}_{tf}_futures.csv',
                 f'historical_data/{symbol}_{tf}_futures.csv']:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=['timestamp'])
            df = df[(df['timestamp']>=START) & (df['timestamp']<=END)].reset_index(drop=True)
            return df
    raise FileNotFoundError(symbol)


def calc_atr(h, l, c, n):
    out = np.full(len(c), np.nan)
    if len(c) < n + 1:
        return out
    tr_sum = 0.0
    for i in range(1, n + 1):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        tr_sum += tr
    out[n] = tr_sum / n
    for i in range(n+1, len(c)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        out[i] = (out[i-1] * (n-1) + tr) / n
    return out


def run_backtest(symbol, tf, length, mult, min_sl_atr, rr, risk_per_trade):
    df = load_data(symbol, tf)
    o = df['open'].values.astype(np.float64)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    ts = df['timestamp']
    n = len(c)
    atr = calc_atr(h, l, c, length)

    cap = INITIAL_CAPITAL
    peak = cap; max_dd = 0.0
    L = length

    upper = 0.0; lower = 0.0
    slope_ph = 0.0; slope_pl = 0.0
    upper_init = False; lower_init = False
    upos = 0; dnos = 0

    position = 0
    ep = 0.0; sz = 0.0; sl_p = 0.0; tp_p = 0.0; liq_p = 0.0
    entry_idx = -1
    entry_time = None
    lev = 1.0
    trades = []

    def append_trade(exit_time, exit_price, reason, size, pnl_val, balance):
        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': ep,
            'exit_price': exit_price,
            'take_profit': tp_p,
            'stop_loss': sl_p,
            'leverage': round(lev, 2),
            'size': round(size, 8),
            'reason': reason,
            'pnl': round(pnl_val, 4),
            'balance': round(balance, 4),
        })

    for i in range(2*L + 1, n):
        if position != 0 and i > entry_idx:
            er = 0; ex = 0.0
            if position == 1:
                if l[i] <= liq_p: ex=liq_p; er=1
                elif l[i] <= sl_p: ex=sl_p; er=2
                elif h[i] >= tp_p: ex=tp_p; er=3
            else:
                if h[i] >= liq_p: ex=liq_p; er=1
                elif h[i] >= sl_p: ex=sl_p; er=2
                elif l[i] <= tp_p: ex=tp_p; er=3
            if er == 1:
                cap=0.0
                append_trade(ts.iloc[i], liq_p, 'LIQ', sz, -INITIAL_CAPITAL, 0.0)
                max_dd=1.0; position=0; break
            if er != 0:
                if position==1: pnl=(ex-ep)*sz
                else: pnl=(ep-ex)*sz
                ef = ep*sz*TAKER_FEE
                xf = ex*sz*MAKER_FEE if er==3 else ex*sz*TAKER_FEE
                net = pnl-ef-xf
                cap += net
                if cap<0: cap=0.0
                reason = 'SL' if er==2 else 'TP'
                append_trade(ts.iloc[i], ex, reason, sz, net, cap)
                if cap > peak: peak = cap
                dd = (peak-cap)/peak if peak>0 else 0.0
                if dd > max_dd: max_dd = dd
                if cap <= 0: break
                position = 0
                continue

        if cap <= 0: break

        pi = i - L
        is_ph = True; is_pl = True
        ph_val = h[pi]; pl_val = l[pi]
        for k in range(i - 2*L, i + 1):
            if k == pi: continue
            if h[k] >= ph_val: is_ph = False
            if l[k] <= pl_val: is_pl = False
            if not is_ph and not is_pl: break

        slope_now = atr[pi] * mult / L if not np.isnan(atr[pi]) else 0.0

        if is_ph:
            upper = ph_val; slope_ph = slope_now; upper_init = True
        elif upper_init:
            upper -= slope_ph
        if is_pl:
            lower = pl_val; slope_pl = slope_now; lower_init = True
        elif lower_init:
            lower += slope_pl

        up_th = (upper - slope_ph * L) if upper_init else (c[i] + 1e9)
        dn_th = (lower + slope_pl * L) if lower_init else -1e9

        prev_upos = upos; prev_dnos = dnos
        if is_ph: upos = 0
        elif c[i] > up_th: upos = 1
        if is_pl: dnos = 0
        elif c[i] < dn_th: dnos = 1

        up_break = upos > prev_upos
        dn_break = dnos > prev_dnos

        if position == 0 and upper_init and lower_init:
            if up_break and not dn_break:
                ep = c[i]
                atr_now = atr[i]
                if np.isnan(atr_now) or atr_now <= 0: continue
                sl_from_tl = lower
                sl_from_atr = ep - atr_now * min_sl_atr
                sl_edge = min(sl_from_tl, sl_from_atr)
                if sl_edge >= ep: continue
                sl_dist = ep - sl_edge
                tp_edge = ep + rr * sl_dist
                sl_pct = sl_dist / ep
                eff_sl = sl_pct + TAKER_FEE*2.0
                lev_ = max(1.0, min(MAX_LEV, risk_per_trade / eff_sl))
                sz_ = (cap*lev_)/ep
                liq_edge = ep * (1.0 - 1.0/lev_)
                sl_p = sl_edge; tp_p = tp_edge; liq_p = liq_edge
                sz = sz_; entry_idx = i; entry_time = ts.iloc[i]; lev = lev_
                position = 1
            elif dn_break and not up_break:
                ep = c[i]
                atr_now = atr[i]
                if np.isnan(atr_now) or atr_now <= 0: continue
                sl_from_tl = upper
                sl_from_atr = ep + atr_now * min_sl_atr
                sl_edge = max(sl_from_tl, sl_from_atr)
                if sl_edge <= ep: continue
                sl_dist = sl_edge - ep
                tp_edge = ep - rr * sl_dist
                sl_pct = sl_dist / ep
                eff_sl = sl_pct + TAKER_FEE*2.0
                lev_ = max(1.0, min(MAX_LEV, risk_per_trade / eff_sl))
                sz_ = (cap*lev_)/ep
                liq_edge = ep * (1.0 + 1.0/lev_)
                sl_p = sl_edge; tp_p = tp_edge; liq_p = liq_edge
                sz = sz_; entry_idx = i; entry_time = ts.iloc[i]; lev = lev_
                position = -1

    if position != 0:
        px = c[-1]
        if position==1: pnl=(px-ep)*sz
        else: pnl=(ep-px)*sz
        net = pnl - ep*sz*TAKER_FEE - px*sz*TAKER_FEE
        cap += net
        if cap < 0: cap = 0.0
        append_trade(ts.iloc[-1], px, 'END', sz, net, cap)
        if cap > peak: peak = cap
        dd = (peak-cap)/peak if peak>0 else 0.0
        if dd > max_dd: max_dd = dd

    return trades, cap, max_dd


def save_trades(trades, filename):
    if not trades: print("No trades"); return
    df = pd.DataFrame(trades)
    cols = ['entry_time','exit_time','direction','entry_price','exit_price',
            'take_profit','stop_loss','leverage','size','reason','pnl','balance']
    df[cols].to_csv(filename, index=False)
    print(f"Saved {filename} ({len(df)} trades)")


def print_summary(trades, cap, max_dd):
    tt = len(trades)
    wins = [t for t in trades if t['pnl']>0]
    longs = [t for t in trades if t['direction']=='LONG']
    shorts = [t for t in trades if t['direction']=='SHORT']
    sls = [t for t in trades if t['reason']=='SL']
    tps = [t for t in trades if t['reason']=='TP']
    liqs = [t for t in trades if t['reason']=='LIQ']
    wr = len(wins)/tt*100 if tt>0 else 0
    print(f"\n=== Summary ===")
    print(f"Total trades    : {tt}")
    print(f"  LONG / SHORT  : {len(longs)} / {len(shorts)}")
    print(f"Wins (pnl>0)    : {len(wins)}  WR: {wr:.2f}%")
    print(f"SL  / TP        : {len(sls)} / {len(tps)}")
    print(f"LIQ             : {len(liqs)}")
    print(f"Max Drawdown    : {max_dd*100:.2f}%")
    print(f"Initial → Final : {INITIAL_CAPITAL:,.2f} → {cap:,.2f}")
    print(f"Return          : {(cap/INITIAL_CAPITAL-1)*100:+.2f}%")


def yearly_breakdown(trades):
    if not trades: return
    df = pd.DataFrame(trades)
    df['et'] = pd.to_datetime(df['entry_time'])
    df['year'] = df['et'].dt.year
    print("\n=== Yearly breakdown ===")
    for y, g in df.groupby('year'):
        sb = g.iloc[0]['balance'] - g.iloc[0]['pnl']
        eb = g.iloc[-1]['balance']
        pct = (eb/sb-1)*100 if sb>0 else 0
        wr = (g['pnl']>0).mean()*100
        print(f"  {y}: T={len(g):4d} WR={wr:5.1f}% startbal={sb:,.0f} endbal={eb:,.0f} ret={pct:+.1f}%")

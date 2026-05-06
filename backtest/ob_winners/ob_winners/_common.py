"""
Order Block Retest 백테스트 공통 모듈.

OB Detection (LuxAlgo 방식):
  Bullish OB: impulse up → range 내 최저 low 봉 zone
  Bearish OB: impulse down → range 내 최고 high 봉 zone
  HTF 1h EMA200 필터 포함.

CSV columns:
  entry_time, exit_time, direction, entry_price, exit_price,
  take_profit, stop_loss, leverage, size, reason, pnl, balance
"""
import os
import numpy as np
import pandas as pd
from numba import njit

INITIAL_CAPITAL = 1000.0
TAKER_FEE = 0.0005
MAKER_FEE = 0.0002
MAX_LEV = 90.0
HTF_EMA_LEN = 200
MAX_OB_QUEUE = 16
START = '2020-01-06'
END = '2026-04-23'


@njit(cache=True)
def calc_ema(c, span):
    n = len(c)
    e = np.empty(n)
    e[0] = c[0]
    k = 2.0 / (span + 1.0)
    for i in range(1, n):
        e[i] = c[i] * k + e[i-1] * (1.0 - k)
    return e


def load_data(symbol: str, tf: str):
    path = f'../historical_data/{symbol}_{tf}_futures.csv'
    if not os.path.exists(path):
        path = f'historical_data/{symbol}_{tf}_futures.csv'
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df = df[(df['timestamp'] >= START) & (df['timestamp'] <= END)].reset_index(drop=True)
    return df


def build_htf_arrays(df):
    ts = df['timestamp']
    cv = df['close'].values.astype(np.float64)
    hour_starts = ts.dt.floor('1h')
    df2 = pd.DataFrame({'close': cv, 'hour': hour_starts})
    hourly = df2.groupby('hour')['close'].last()
    hourly_close = hourly.values.astype(np.float64)
    hourly_ema = calc_ema(hourly_close, HTF_EMA_LEN)
    hourly_ema[:HTF_EMA_LEN] = np.nan
    hour_to_idx = {h: idx for idx, h in enumerate(hourly.index)}
    htf_close_arr = np.full(len(ts), np.nan)
    htf_ema_arr = np.full(len(ts), np.nan)
    for i in range(len(ts)):
        idx = hour_to_idx.get(hour_starts.iloc[i], -1)
        li = idx - 1
        if li >= 0:
            htf_close_arr[i] = hourly_close[li]
            htf_ema_arr[i] = hourly_ema[li]
    return htf_close_arr, htf_ema_arr


def run_backtest(symbol, tf,
                 impulse_lookback, impulse_min_pct,
                 sl_buffer_pct, rr, max_wait, risk_per_trade):
    df = load_data(symbol, tf)
    o = df['open'].values.astype(np.float64)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    ts = df['timestamp']
    n = len(c)

    htf_close, htf_ema = build_htf_arrays(df)

    cap = INITIAL_CAPITAL
    peak = cap
    max_dd = 0.0

    long_top = []; long_bot = []; long_bar = []
    short_top = []; short_bot = []; short_bar = []

    position = 0
    entry_time = None
    entry_price = 0.0
    entry_idx = -1
    sz = 0.0
    sl_p = 0.0
    tp_p = 0.0
    liq_p = 0.0
    lev = 1.0

    trades = []

    def append_trade(exit_time, exit_price, reason, size, pnl_val, balance):
        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'take_profit': tp_p,
            'stop_loss': sl_p,
            'leverage': round(lev, 2),
            'size': round(size, 8),
            'reason': reason,
            'pnl': round(pnl_val, 4),
            'balance': round(balance, 4),
        })

    for i in range(impulse_lookback + 1, n):
        # EXIT
        if position != 0 and i > entry_idx:
            # LIQ > SL > TP 순서
            if position == 1:
                if l[i] <= liq_p:
                    pnl_raw = (liq_p - entry_price) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - liq_p * sz * TAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], liq_p, 'LIQ', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
                elif l[i] <= sl_p:
                    pnl_raw = (sl_p - entry_price) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - sl_p * sz * TAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], sl_p, 'SL', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
                elif h[i] >= tp_p:
                    pnl_raw = (tp_p - entry_price) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - tp_p * sz * MAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], tp_p, 'TP', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
            else:
                if h[i] >= liq_p:
                    pnl_raw = (entry_price - liq_p) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - liq_p * sz * TAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], liq_p, 'LIQ', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
                elif h[i] >= sl_p:
                    pnl_raw = (entry_price - sl_p) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - sl_p * sz * TAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], sl_p, 'SL', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
                elif l[i] <= tp_p:
                    pnl_raw = (entry_price - tp_p) * sz
                    net = pnl_raw - entry_price * sz * MAKER_FEE - tp_p * sz * MAKER_FEE
                    cap = max(0.0, cap + net)
                    append_trade(ts.iloc[i], tp_p, 'TP', sz, net, cap)
                    peak = max(peak, cap); dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue

        if cap <= 0:
            break

        # OB DETECTION (LuxAlgo: lowest low / highest high in impulse range)
        impulse_up = (c[i] - c[i - impulse_lookback]) / c[i]
        if impulse_up >= impulse_min_pct:
            ob_idx = i - impulse_lookback
            min_l = l[ob_idx]
            for k in range(i - impulse_lookback + 1, i):
                if l[k] < min_l:
                    min_l = l[k]; ob_idx = k
            ob_top = h[ob_idx]; ob_bot = l[ob_idx]
            if ob_top > ob_bot and len(long_top) < MAX_OB_QUEUE:
                long_top.append(ob_top); long_bot.append(ob_bot); long_bar.append(i)

        impulse_down = (c[i - impulse_lookback] - c[i]) / c[i]
        if impulse_down >= impulse_min_pct:
            ob_idx = i - impulse_lookback
            max_h = h[ob_idx]
            for k in range(i - impulse_lookback + 1, i):
                if h[k] > max_h:
                    max_h = h[k]; ob_idx = k
            ob_top = h[ob_idx]; ob_bot = l[ob_idx]
            if ob_top > ob_bot and len(short_top) < MAX_OB_QUEUE:
                short_top.append(ob_top); short_bot.append(ob_bot); short_bar.append(i)

        # INVALIDATION / MAX_WAIT
        k = 0
        while k < len(long_top):
            if c[i] < long_bot[k] or (i - long_bar[k]) > max_wait:
                long_top.pop(k); long_bot.pop(k); long_bar.pop(k)
            else:
                k += 1
        k = 0
        while k < len(short_top):
            if c[i] > short_top[k] or (i - short_bar[k]) > max_wait:
                short_top.pop(k); short_bot.pop(k); short_bar.pop(k)
            else:
                k += 1

        # ENTRY
        if position == 0:
            htf_bull = (not np.isnan(htf_ema[i])) and htf_close[i] > htf_ema[i]
            htf_bear = (not np.isnan(htf_ema[i])) and htf_close[i] < htf_ema[i]

            if htf_bull and len(long_top) > 0:
                best_k = -1; best_bar = -1
                for k in range(len(long_top)):
                    if long_bar[k] < i and l[i] <= long_top[k]:
                        if long_bar[k] > best_bar:
                            best_bar = long_bar[k]; best_k = k
                if best_k >= 0:
                    ep_i = min(max(long_top[best_k], l[i]), h[i])
                    sl_edge = long_bot[best_k] * (1.0 - sl_buffer_pct)
                    sl_dist = ep_i - sl_edge
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep_i
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = min(max(risk_per_trade / eff_sl, 1.0), MAX_LEV)
                        notional = cap * lev_
                        sz_ = notional / ep_i
                        entry_price = ep_i; entry_time = ts.iloc[i]; entry_idx = i
                        sz = sz_; sl_p = sl_edge; lev = lev_
                        tp_p = ep_i + rr * sl_dist
                        liq_p = ep_i * (1.0 - 1.0 / lev_)
                        position = 1
                        long_top.clear(); long_bot.clear(); long_bar.clear()
                        continue

            if htf_bear and len(short_top) > 0:
                best_k = -1; best_bar = -1
                for k in range(len(short_top)):
                    if short_bar[k] < i and h[i] >= short_bot[k]:
                        if short_bar[k] > best_bar:
                            best_bar = short_bar[k]; best_k = k
                if best_k >= 0:
                    ep_i = min(max(short_bot[best_k], l[i]), h[i])
                    sl_edge = short_top[best_k] * (1.0 + sl_buffer_pct)
                    sl_dist = sl_edge - ep_i
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep_i
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = min(max(risk_per_trade / eff_sl, 1.0), MAX_LEV)
                        notional = cap * lev_
                        sz_ = notional / ep_i
                        entry_price = ep_i; entry_time = ts.iloc[i]; entry_idx = i
                        sz = sz_; sl_p = sl_edge; lev = lev_
                        tp_p = ep_i - rr * sl_dist
                        liq_p = ep_i * (1.0 + 1.0 / lev_)
                        position = -1
                        short_top.clear(); short_bot.clear(); short_bar.clear()
                        continue

    # Force close
    if position != 0:
        px = c[-1]
        if position == 1:
            pnl_raw = (px - entry_price) * sz
        else:
            pnl_raw = (entry_price - px) * sz
        net = pnl_raw - entry_price * sz * MAKER_FEE - px * sz * TAKER_FEE
        cap = max(0.0, cap + net)
        append_trade(ts.iloc[-1], px, 'END', sz, net, cap)
        peak = max(peak, cap)
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return trades, cap, max_dd


def save_trades(trades, filename):
    if not trades:
        print("No trades"); return
    df = pd.DataFrame(trades)
    cols = ['entry_time', 'exit_time', 'direction', 'entry_price', 'exit_price',
            'take_profit', 'stop_loss', 'leverage', 'size', 'reason', 'pnl', 'balance']
    df[cols].to_csv(filename, index=False)
    print(f"Saved {len(trades)} trades → {filename}")


def print_summary(trades, cap, max_dd):
    tt = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    liqs = [t for t in trades if t['reason'] == 'LIQ']
    sls = [t for t in trades if t['reason'] == 'SL']
    tps = [t for t in trades if t['reason'] == 'TP']
    print(f"\n=== Summary ===")
    print(f"Total trades    : {tt}")
    print(f"  LONG / SHORT  : {len(longs)} / {len(shorts)}")
    print(f"Wins (pnl>0)    : {len(wins)}  WR: {len(wins)/tt*100 if tt>0 else 0:.2f}%")
    print(f"SL  / TP        : {len(sls)} / {len(tps)}")
    print(f"LIQ             : {len(liqs)}")
    print(f"Max Drawdown    : {max_dd*100:.2f}%")
    print(f"Initial → Final : {INITIAL_CAPITAL:.2f} → {cap:.2f}")
    print(f"Return          : {(cap/INITIAL_CAPITAL-1)*100:+.2f}%")

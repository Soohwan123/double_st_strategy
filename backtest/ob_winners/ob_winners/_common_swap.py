"""
OB Retest 백테스트 SWAP variant — Python with trade logging.

SWAP fix:
  1. ENTRY before INVALIDATION (intrabar LIMIT fill 모사)
  2. 진입봉 1m intrabar resolve (NO_ENTRY / SL / TP / LIQ)

Numba 없이 Python 으로 trade-by-trade 로깅.
"""
import os
import numpy as np
import pandas as pd

INITIAL_CAPITAL = 1000.0
TAKER_FEE = 0.0005
MAKER_FEE = 0.0002
MAX_LEV = 90
MAX_OB_QUEUE = 16
HTF_EMA_LEN = 200
START = '2024-01-06'
END = '2026-04-23'


def calc_ema_py(c, span):
    n = len(c)
    e = np.empty(n); e[0] = c[0]
    k = 2.0 / (span + 1.0)
    for i in range(1, n):
        e[i] = c[i] * k + e[i-1] * (1.0 - k)
    return e


def load_data(symbol, tf):
    path = f'../historical_data/{symbol}_{tf}_futures.csv'
    if not os.path.exists(path):
        path = f'historical_data/{symbol}_{tf}_futures.csv'
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df.columns = df.columns.str.lower()
    df = df[(df['timestamp'] >= START) & (df['timestamp'] <= END)].reset_index(drop=True)
    return df


def load_1m_data(symbol):
    for path in [f'../historical_data/{symbol}_1m_futures.csv',
                 f'historical_data/{symbol}_1m_futures.csv']:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=['timestamp'])
            return df.set_index('timestamp')[['high', 'low']]
    return None


def build_htf_arrays(df):
    ts = df['timestamp']
    cv = df['close'].values.astype(np.float64)
    hour_starts = ts.dt.floor('1h')
    df2 = pd.DataFrame({'close': cv, 'hour': hour_starts})
    hourly = df2.groupby('hour')['close'].last()
    hourly_close = hourly.values.astype(np.float64)
    hourly_ema = calc_ema_py(hourly_close, HTF_EMA_LEN)
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


def resolve_entry_bar_1m(bar1m, entry_ts, ep, sl_p, tp_p, liq_p, direction, tf_minutes):
    """1m 캔들로 entry-bar 순서 판별 — 보수적 우선순위 LIQ > SL > ENTRY > TP.
    진입 1m 봉에서는 TP 체크 안 함 (entry 후 TP 까지 같은 1m 도달은 낙관적, skip).
    다음 1m 봉부터 LIQ/SL/TP 모두 체크.
    Returns (status, entry_1m_ts, exit_1m_ts)
    """
    if bar1m is None:
        return ('OK', None, None)
    entered = False
    entry_1m_ts = None
    entry_offset = -1
    for offset in range(tf_minutes):
        t1 = entry_ts + pd.Timedelta(minutes=offset)
        if t1 not in bar1m.index:
            continue
        h1 = bar1m.loc[t1, 'high']; l1 = bar1m.loc[t1, 'low']
        if not entered:
            entry_hit = (l1 <= ep) if direction == 1 else (h1 >= ep)
            if not entry_hit: continue
            entered = True
            entry_1m_ts = t1
            entry_offset = offset
        if direction == 1:
            liq_hit = l1 <= liq_p
            sl_hit  = l1 <= sl_p
            tp_hit  = h1 >= tp_p
        else:
            liq_hit = h1 >= liq_p
            sl_hit  = h1 >= sl_p
            tp_hit  = l1 <= tp_p
        if liq_hit: return ('LIQ', entry_1m_ts, t1)
        if sl_hit:  return ('SL',  entry_1m_ts, t1)
        # 진입 1m 봉에서는 TP 무시 (다음 봉부터 인정)
        if offset > entry_offset and tp_hit:
            return ('TP', entry_1m_ts, t1)
    if not entered:
        return ('NO_ENTRY', None, None)
    return ('OK', entry_1m_ts, None)


def run_backtest(symbol, tf,
                 impulse_lookback, impulse_min_pct, sl_buffer_pct,
                 rr, max_wait, risk_per_trade,
                 use_htf=True):
    """
    SWAP: entry-before-invalidation + 1m intrabar resolve.
    Returns: (trades, cap, max_dd)
    """
    tf_minutes = int(tf.replace('m', ''))
    df = load_data(symbol, tf)
    o = df['open'].values.astype(np.float64)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    ts = df['timestamp']
    n = len(c)

    if use_htf:
        htf_close, htf_ema = build_htf_arrays(df)
    else:
        htf_close = np.full(n, np.nan)
        htf_ema   = np.full(n, np.nan)

    bar1m = load_1m_data(symbol)

    cap = INITIAL_CAPITAL
    peak = cap; max_dd = 0.0

    long_top = []; long_bot = []; long_bar = []
    short_top = []; short_bot = []; short_bar = []

    position = 0
    ep = 0.0; sz = 0.0
    sl_p = 0.0; tp_p = 0.0; liq_p = 0.0
    entry_idx = -1
    entry_time = None
    entry_price_logged = 0.0
    lev = 1.0

    trades = []

    def log_trade(exit_time, exit_price, reason, size, pnl_val, balance):
        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price_logged,
            'exit_price': exit_price,
            'take_profit': tp_p,
            'stop_loss': sl_p,
            'leverage': round(lev, 2),
            'size': round(size, 8),
            'reason': reason,
            'pnl': round(pnl_val, 4),
            'balance': round(balance, 4),
        })

    def process_exit(bar_i, exit_price, reason, exit_taker, exit_time_override=None):
        """반대편으로 청산 처리. exit_time_override: 진입봉 1m resolve 시 실제 1m 타임스탬프."""
        nonlocal cap, peak, max_dd, position
        if position == 1:
            pnl = (exit_price - ep) * sz
        else:
            pnl = (ep - exit_price) * sz
        ef = ep * sz * MAKER_FEE
        xf = exit_price * sz * (TAKER_FEE if exit_taker else MAKER_FEE)
        net = pnl - ef - xf
        cap += net
        if cap < 0: cap = 0.0
        et = exit_time_override if exit_time_override is not None else ts.iloc[bar_i]
        log_trade(et, exit_price, reason, sz, net, cap)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd
        position = 0

    for i in range(impulse_lookback + 1, n):
        # EXIT (진입봉 다음 bar 부터)
        if position != 0 and i > entry_idx:
            if position == 1:
                if   l[i] <= liq_p: process_exit(i, liq_p, 'LIQ', True);  continue
                elif l[i] <= sl_p:  process_exit(i, sl_p,  'SL',  True);  continue
                elif h[i] >= tp_p:  process_exit(i, tp_p,  'TP',  False); continue
            else:
                if   h[i] >= liq_p: process_exit(i, liq_p, 'LIQ', True);  continue
                elif h[i] >= sl_p:  process_exit(i, sl_p,  'SL',  True);  continue
                elif l[i] <= tp_p:  process_exit(i, tp_p,  'TP',  False); continue

        if cap <= 0: break

        # OB DETECTION
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

        # [SWAP] ENTRY 먼저
        if position == 0:
            htf_bull = (not np.isnan(htf_ema[i])) and htf_close[i] > htf_ema[i] if use_htf else True
            htf_bear = (not np.isnan(htf_ema[i])) and htf_close[i] < htf_ema[i] if use_htf else True

            # LONG
            best_k = -1; best_bar_idx = -1
            if htf_bull:
                for k in range(len(long_top)):
                    if long_bar[k] < i and l[i] <= long_top[k]:
                        if long_bar[k] > best_bar_idx:
                            best_bar_idx = long_bar[k]; best_k = k
            if best_k >= 0:
                ep_i = long_top[best_k]
                ep_i = min(max(ep_i, l[i]), h[i])
                sl_edge = long_bot[best_k] * (1.0 - sl_buffer_pct)
                sl_dist = ep_i - sl_edge
                if sl_dist > 0:
                    tp_edge = ep_i + rr * sl_dist
                    sl_pct = sl_dist / ep_i
                    eff_sl = sl_pct + TAKER_FEE * 2.0
                    lev_ = max(1.0, min(MAX_LEV, risk_per_trade / eff_sl))
                    notional = cap * lev_
                    sz_ = notional / ep_i
                    liq_edge = ep_i * (1.0 - 1.0 / lev_)

                    result, entry_1m_ts, exit_1m_ts = resolve_entry_bar_1m(
                        bar1m, ts.iloc[i], ep_i, sl_edge, tp_edge, liq_edge, 1, tf_minutes)
                    if result == 'NO_ENTRY':
                        pass  # OB 유지, 거래 skip
                    else:
                        ep = ep_i; sz = sz_
                        sl_p = sl_edge; tp_p = tp_edge; liq_p = liq_edge
                        entry_idx = i
                        entry_time = entry_1m_ts if entry_1m_ts is not None else ts.iloc[i]
                        entry_price_logged = ep_i; lev = lev_
                        position = 1
                        long_top.clear(); long_bot.clear(); long_bar.clear()
                        if result == 'LIQ':
                            cap = 0.0
                            et = exit_1m_ts if exit_1m_ts is not None else ts.iloc[i]
                            log_trade(et, liq_edge, 'LIQ', sz_, -cap, 0.0)
                            max_dd = 1.0; position = 0; break
                        elif result == 'SL':
                            process_exit(i, sl_p, 'SL', True, exit_time_override=exit_1m_ts)
                            if cap <= 0: break
                            continue
                        elif result == 'TP':
                            process_exit(i, tp_p, 'TP', False, exit_time_override=exit_1m_ts)
                            if cap <= 0: break
                            continue
                        # OK: 정상 진입
                        continue

            # SHORT
            best_k = -1; best_bar_idx = -1
            if htf_bear:
                for k in range(len(short_top)):
                    if short_bar[k] < i and h[i] >= short_bot[k]:
                        if short_bar[k] > best_bar_idx:
                            best_bar_idx = short_bar[k]; best_k = k
            if best_k >= 0:
                ep_i = short_bot[best_k]
                ep_i = min(max(ep_i, l[i]), h[i])
                sl_edge = short_top[best_k] * (1.0 + sl_buffer_pct)
                sl_dist = sl_edge - ep_i
                if sl_dist > 0:
                    tp_edge = ep_i - rr * sl_dist
                    sl_pct = sl_dist / ep_i
                    eff_sl = sl_pct + TAKER_FEE * 2.0
                    lev_ = max(1.0, min(MAX_LEV, risk_per_trade / eff_sl))
                    notional = cap * lev_
                    sz_ = notional / ep_i
                    liq_edge = ep_i * (1.0 + 1.0 / lev_)

                    result, entry_1m_ts, exit_1m_ts = resolve_entry_bar_1m(
                        bar1m, ts.iloc[i], ep_i, sl_edge, tp_edge, liq_edge, -1, tf_minutes)
                    if result == 'NO_ENTRY':
                        pass
                    else:
                        ep = ep_i; sz = sz_
                        sl_p = sl_edge; tp_p = tp_edge; liq_p = liq_edge
                        entry_idx = i
                        entry_time = entry_1m_ts if entry_1m_ts is not None else ts.iloc[i]
                        entry_price_logged = ep_i; lev = lev_
                        position = -1
                        short_top.clear(); short_bot.clear(); short_bar.clear()
                        if result == 'LIQ':
                            cap = 0.0
                            et = exit_1m_ts if exit_1m_ts is not None else ts.iloc[i]
                            log_trade(et, liq_edge, 'LIQ', sz_, -cap, 0.0)
                            max_dd = 1.0; position = 0; break
                        elif result == 'SL':
                            process_exit(i, sl_p, 'SL', True, exit_time_override=exit_1m_ts)
                            if cap <= 0: break
                            continue
                        elif result == 'TP':
                            process_exit(i, tp_p, 'TP', False, exit_time_override=exit_1m_ts)
                            if cap <= 0: break
                            continue
                        continue

        # [SWAP] INVALIDATION / MAX_WAIT (entry 뒤로)
        k = 0
        while k < len(long_top):
            if c[i] < long_bot[k] or (i - long_bar[k]) > max_wait:
                long_top.pop(k); long_bot.pop(k); long_bar.pop(k)
            else: k += 1
        k = 0
        while k < len(short_top):
            if c[i] > short_top[k] or (i - short_bar[k]) > max_wait:
                short_top.pop(k); short_bot.pop(k); short_bar.pop(k)
            else: k += 1

    # Force close
    if position != 0:
        px = c[-1]
        if position == 1: pnl = (px - ep) * sz
        else:             pnl = (ep - px) * sz
        ef = ep * sz * MAKER_FEE
        xf = px * sz * TAKER_FEE
        net = pnl - ef - xf
        cap += net
        if cap < 0: cap = 0.0
        log_trade(ts.iloc[-1], px, 'END', sz, net, cap)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd

    return trades, cap, max_dd


def save_trades(trades, filename):
    if not trades: print("No trades"); return
    df = pd.DataFrame(trades)
    cols = ['entry_time', 'exit_time', 'direction', 'entry_price', 'exit_price',
            'take_profit', 'stop_loss', 'leverage', 'size', 'reason', 'pnl', 'balance']
    df[cols].to_csv(filename, index=False)


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

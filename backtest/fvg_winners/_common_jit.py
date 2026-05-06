"""
FVG Retest 백테스트 — JIT 가속 버전.

원본 `_common.py` 의 sim 루프를 단일 `@njit` 함수로 재작성.
- numpy 배열 + 정수 카운터 사용 (Python list 제거)
- 모든 closure helper 인라인
- pandas Timestamp 접근 제거
- 1m intrabar resolve 단순화: entry bar 에서 SL/TP 동시 touch 시 보수적으로 SL hit (1m 해상도 안 씀)

Mode:
- 0 = SWAP (limit 진입, l[i] <= top, entry-bar SL/TP 체크 포함)
- 1 = MARKET (close 기반 진입, bot ≤ c[i] ≤ top, entry 가 봉 close 시점이므로 entry-bar exit 없음)

Look-ahead 제거: invalidation 은 entry 다음에 실행 (entry 가 c[i] 정보 사용 안 함).
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
MAX_FVG_QUEUE = 16
START = '2020-01-06'
END = '2026-04-26'


@njit(cache=True)
def calc_ema(c, span):
    n = len(c)
    e = np.empty(n)
    e[0] = c[0]
    k = 2.0 / (span + 1.0)
    for i in range(1, n):
        e[i] = c[i] * k + e[i-1] * (1.0 - k)
    return e


@njit(cache=True)
def resolve_entry_bar_jit(h1m, l1m, valid, bar_idx, tf_minutes, ep, sl, tp, direction):
    """
    1m intrabar resolve.

    h1m, l1m: shape (n_15m, tf_minutes) precomputed 1m high/low arrays
    valid:    shape (n_15m, tf_minutes) bool — whether 1m bar exists
    bar_idx:  현재 15m bar index
    direction: 1=LONG, -1=SHORT

    Returns:
      0 = OK (entry 도달, entry-bar SL/TP 없음 → 다음 봉 처리)
      1 = SL (entry 도달 후 SL 먼저)
      2 = TP (entry 도달 후 TP 먼저)
      3 = NO_ENTRY (entry 가격 1m 상에서 미도달)
    """
    entered = False
    for offset in range(tf_minutes):
        if not valid[bar_idx, offset]:
            continue
        h1 = h1m[bar_idx, offset]
        l1 = l1m[bar_idx, offset]
        if not entered:
            if direction == 1:
                if l1 <= ep:
                    entered = True
                else:
                    continue
            else:
                if h1 >= ep:
                    entered = True
                else:
                    continue
        # entered: check SL/TP in this 1m bar
        if direction == 1:
            sl_hit = l1 <= sl
            tp_hit = h1 >= tp
        else:
            sl_hit = h1 >= sl
            tp_hit = l1 <= tp
        if sl_hit and tp_hit:
            return 1  # 같은 1m 봉 → 보수적 SL
        if sl_hit:
            return 1
        if tp_hit:
            return 2
    if not entered:
        return 3
    return 0


def build_1m_arrays(df_15m, symbol, tf_minutes):
    """1m 데이터를 (n_15m, tf_minutes) shape 배열로 정렬해서 JIT 함수에 넘길 준비."""
    path = f'../historical_data/{symbol}_1m_futures.csv'
    if not os.path.exists(path):
        path = f'historical_data/{symbol}_1m_futures.csv'
    if not os.path.exists(path):
        return None, None, None
    df1 = pd.read_csv(path, parse_dates=['timestamp'])
    df1 = df1.set_index('timestamp')
    h1_idx = df1['high'].to_dict()
    l1_idx = df1['low'].to_dict()
    n = len(df_15m)
    h1m = np.zeros((n, tf_minutes), dtype=np.float64)
    l1m = np.zeros((n, tf_minutes), dtype=np.float64)
    valid = np.zeros((n, tf_minutes), dtype=np.bool_)
    ts15 = df_15m['timestamp'].values
    for i in range(n):
        base = pd.Timestamp(ts15[i])
        for off in range(tf_minutes):
            t1 = base + pd.Timedelta(minutes=off)
            if t1 in h1_idx:
                h1m[i, off] = h1_idx[t1]
                l1m[i, off] = l1_idx[t1]
                valid[i, off] = True
    return h1m, l1m, valid


def load_data(symbol: str, tf: str):
    path = f'../historical_data/{symbol}_{tf}_futures.csv'
    if not os.path.exists(path):
        path = f'historical_data/{symbol}_{tf}_futures.csv'
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df = df[(df['timestamp'] >= START) & (df['timestamp'] <= END)].reset_index(drop=True)
    return df


def build_htf_arrays(df):
    """5m/15m -> 1h 집계 후 EMA200. 각 bar 에 직전 '닫힌' 1h 값을 매핑.
    원본 _common.py 와 동일 (dict lookup, O(n))."""
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


@njit(cache=True)
def _sim(h, l, c, htf_close, htf_ema, use_htf, n,
         h1m, l1m, valid_1m, tf_minutes,
         sl_buffer_pct, rr, max_wait, risk_per_trade, min_fvg_pct,
         taker_fee, maker_fee, max_lev, max_fvg_queue,
         initial_capital, mode,
         is_partial, rr1, rr2, be_after_tp1):
    """
    JIT'd sim loop.

    mode: 0 = SWAP, 1 = MARKET
    is_partial: 0 = single TP (rr 사용), 1 = partial TP (rr1, rr2 사용)
    be_after_tp1: 1 = TP1 후 SL 을 entry 로 이동 (breakeven)

    Returns: (out_entry, out_exit, out_dir, out_ep, out_xp, out_sl, out_tp,
              out_lev, out_size, out_reason, out_pnl, out_bal, n_trades, cap, max_dd)

    out_reason: 0=END, 1=SL, 2=TP (or TP2), 3=LIQ, 4=TP1
    out_dir: 1=LONG, -1=SHORT
    """
    # FVG queue (fixed size + counter)
    long_top = np.empty(max_fvg_queue, dtype=np.float64)
    long_bot = np.empty(max_fvg_queue, dtype=np.float64)
    long_bar = np.empty(max_fvg_queue, dtype=np.int64)
    long_n = 0
    short_top = np.empty(max_fvg_queue, dtype=np.float64)
    short_bot = np.empty(max_fvg_queue, dtype=np.float64)
    short_bar = np.empty(max_fvg_queue, dtype=np.int64)
    short_n = 0

    # Trade output (over-allocate to n)
    out_entry = np.empty(n, dtype=np.int64)
    out_exit = np.empty(n, dtype=np.int64)
    out_dir = np.empty(n, dtype=np.int8)
    out_ep = np.empty(n, dtype=np.float64)
    out_xp = np.empty(n, dtype=np.float64)
    out_sl = np.empty(n, dtype=np.float64)
    out_tp = np.empty(n, dtype=np.float64)
    out_lev = np.empty(n, dtype=np.float64)
    out_size = np.empty(n, dtype=np.float64)
    out_reason = np.empty(n, dtype=np.int8)
    out_pnl = np.empty(n, dtype=np.float64)
    out_bal = np.empty(n, dtype=np.float64)
    n_trades = 0

    cap = initial_capital
    peak = cap
    max_dd = 0.0

    position = 0
    entry_price = 0.0
    entry_idx = -1
    sz = 0.0
    sz_total = 0.0  # 진입 시 원래 사이즈 (partial 의 sz_half 계산용)
    sl_p = 0.0
    tp_p = 0.0  # single TP edge (is_partial=0)
    tp1_p = 0.0  # partial TP1 edge
    tp2_p = 0.0  # partial TP2 edge
    tp1_hit = False
    liq_p = 0.0
    lev = 1.0

    # entry fee rate by mode (0=swap=limit=maker, 1=market=taker)
    entry_fee_rate = taker_fee if mode == 1 else maker_fee

    for i in range(2, n):
        # ============ EXIT (진입봉 다음 봉부터) ============
        if position != 0 and i > entry_idx:
            # LIQ
            liq_hit = (position == 1 and l[i] <= liq_p) or (position == -1 and h[i] >= liq_p)
            if liq_hit:
                if position == 1:
                    pnl_raw = (liq_p - entry_price) * sz
                else:
                    pnl_raw = (entry_price - liq_p) * sz
                ef = entry_price * sz * entry_fee_rate
                xf = liq_p * sz * taker_fee
                net = pnl_raw - ef - xf
                cap += net
                if cap < 0: cap = 0.0
                out_entry[n_trades] = entry_idx
                out_exit[n_trades] = i
                out_dir[n_trades] = position
                out_ep[n_trades] = entry_price
                out_xp[n_trades] = liq_p
                out_sl[n_trades] = sl_p
                out_tp[n_trades] = tp_p
                out_lev[n_trades] = lev
                out_size[n_trades] = sz
                out_reason[n_trades] = 3
                out_pnl[n_trades] = net
                out_bal[n_trades] = cap
                n_trades += 1
                if cap > peak: peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd: max_dd = dd
                position = 0
                if cap <= 0: break
                continue

            # SL
            sl_hit = (position == 1 and l[i] <= sl_p) or (position == -1 and h[i] >= sl_p)
            if sl_hit:
                if position == 1:
                    pnl_raw = (sl_p - entry_price) * sz
                else:
                    pnl_raw = (entry_price - sl_p) * sz
                ef = entry_price * sz * entry_fee_rate
                xf = sl_p * sz * taker_fee
                net = pnl_raw - ef - xf
                cap += net
                if cap < 0: cap = 0.0
                out_entry[n_trades] = entry_idx
                out_exit[n_trades] = i
                out_dir[n_trades] = position
                out_ep[n_trades] = entry_price
                out_xp[n_trades] = sl_p
                out_sl[n_trades] = sl_p
                out_tp[n_trades] = tp_p
                out_lev[n_trades] = lev
                out_size[n_trades] = sz
                out_reason[n_trades] = 1
                out_pnl[n_trades] = net
                out_bal[n_trades] = cap
                n_trades += 1
                if cap > peak: peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd: max_dd = dd
                position = 0
                if cap <= 0: break
                continue

            # TP (single 또는 partial)
            if is_partial == 0:
                # Single TP
                tp_hit = (position == 1 and h[i] >= tp_p) or (position == -1 and l[i] <= tp_p)
                if tp_hit:
                    if position == 1:
                        pnl_raw = (tp_p - entry_price) * sz
                    else:
                        pnl_raw = (entry_price - tp_p) * sz
                    ef = entry_price * sz * entry_fee_rate
                    xf = tp_p * sz * maker_fee
                    net = pnl_raw - ef - xf
                    cap += net
                    if cap < 0: cap = 0.0
                    out_entry[n_trades] = entry_idx
                    out_exit[n_trades] = i
                    out_dir[n_trades] = position
                    out_ep[n_trades] = entry_price
                    out_xp[n_trades] = tp_p
                    out_sl[n_trades] = sl_p
                    out_tp[n_trades] = tp_p
                    out_lev[n_trades] = lev
                    out_size[n_trades] = sz
                    out_reason[n_trades] = 2
                    out_pnl[n_trades] = net
                    out_bal[n_trades] = cap
                    n_trades += 1
                    if cap > peak: peak = cap
                    dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    position = 0
                    if cap <= 0: break
                    continue
            else:
                # Partial TP: TP1 (50%) + TP2 (50%)
                if not tp1_hit:
                    tp1_touch = (position == 1 and h[i] >= tp1_p) or (position == -1 and l[i] <= tp1_p)
                    if tp1_touch:
                        sz_half = sz_total * 0.5
                        if position == 1:
                            pnl_raw = (tp1_p - entry_price) * sz_half
                        else:
                            pnl_raw = (entry_price - tp1_p) * sz_half
                        ef = entry_price * sz_half * entry_fee_rate
                        xf = tp1_p * sz_half * maker_fee
                        net = pnl_raw - ef - xf
                        cap += net
                        if cap < 0: cap = 0.0
                        out_entry[n_trades] = entry_idx
                        out_exit[n_trades] = i
                        out_dir[n_trades] = position
                        out_ep[n_trades] = entry_price
                        out_xp[n_trades] = tp1_p
                        out_sl[n_trades] = sl_p
                        out_tp[n_trades] = tp1_p
                        out_lev[n_trades] = lev
                        out_size[n_trades] = sz_half
                        out_reason[n_trades] = 4  # TP1
                        out_pnl[n_trades] = net
                        out_bal[n_trades] = cap
                        n_trades += 1
                        tp1_hit = True
                        sz = sz_total - sz_half  # remaining
                        if be_after_tp1 == 1:
                            sl_p = entry_price  # breakeven
                        if cap > peak: peak = cap

                if tp1_hit:
                    tp2_touch = (position == 1 and h[i] >= tp2_p) or (position == -1 and l[i] <= tp2_p)
                    if tp2_touch:
                        if position == 1:
                            pnl_raw = (tp2_p - entry_price) * sz
                        else:
                            pnl_raw = (entry_price - tp2_p) * sz
                        ef = entry_price * sz * entry_fee_rate
                        xf = tp2_p * sz * maker_fee
                        net = pnl_raw - ef - xf
                        cap += net
                        if cap < 0: cap = 0.0
                        out_entry[n_trades] = entry_idx
                        out_exit[n_trades] = i
                        out_dir[n_trades] = position
                        out_ep[n_trades] = entry_price
                        out_xp[n_trades] = tp2_p
                        out_sl[n_trades] = sl_p
                        out_tp[n_trades] = tp2_p
                        out_lev[n_trades] = lev
                        out_size[n_trades] = sz
                        out_reason[n_trades] = 2  # TP2
                        out_pnl[n_trades] = net
                        out_bal[n_trades] = cap
                        n_trades += 1
                        if cap > peak: peak = cap
                        dd = (peak - cap) / peak if peak > 0 else 0.0
                        if dd > max_dd: max_dd = dd
                        position = 0
                        tp1_hit = False
                        if cap <= 0: break
                        continue

        if cap <= 0: break

        # ============ FVG detection (3봉 패턴) ============
        if l[i] > h[i-2]:
            gap_top = l[i]
            gap_bot = h[i-2]
            if c[i] > 0 and (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if long_n < max_fvg_queue:
                    long_top[long_n] = gap_top
                    long_bot[long_n] = gap_bot
                    long_bar[long_n] = i
                    long_n += 1
        if h[i] < l[i-2]:
            gap_top = l[i-2]
            gap_bot = h[i]
            if c[i] > 0 and (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if short_n < max_fvg_queue:
                    short_top[short_n] = gap_top
                    short_bot[short_n] = gap_bot
                    short_bar[short_n] = i
                    short_n += 1

        # ============ ENTRY (look-ahead 제거: entry 가 invalidation 보다 먼저) ============
        if position == 0:
            htf_bull = True
            htf_bear = True
            if use_htf:
                if np.isnan(htf_ema[i]):
                    htf_bull = False
                    htf_bear = False
                else:
                    htf_bull = htf_close[i] > htf_ema[i]
                    htf_bear = htf_close[i] < htf_ema[i]

            entered = False

            # LONG
            if htf_bull and long_n > 0:
                best_k = -1
                best_bar = -1
                for k in range(long_n):
                    if mode == 0:
                        cond = long_bar[k] < i and l[i] <= long_top[k]
                    else:
                        cond = long_bar[k] < i and long_bot[k] <= c[i] <= long_top[k]
                    if cond and long_bar[k] > best_bar:
                        best_bar = long_bar[k]
                        best_k = k
                if best_k >= 0:
                    if mode == 0:
                        ep_i = long_top[best_k]
                        if ep_i > h[i]: ep_i = h[i]
                        if ep_i < l[i]: ep_i = l[i]
                    else:
                        ep_i = c[i]
                    sl_edge = long_bot[best_k] * (1.0 - sl_buffer_pct)
                    sl_dist = ep_i - sl_edge
                    if sl_dist > 0:
                        sl_pct_v = sl_dist / ep_i
                        eff_sl = sl_pct_v + taker_fee * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > max_lev: lev_ = max_lev
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size_v = notional / ep_i
                        liq_edge = ep_i * (1.0 - 1.0 / lev_)
                        tp_edge = ep_i + rr * sl_dist
                        tp1_edge = ep_i + rr1 * sl_dist
                        tp2_edge = ep_i + rr2 * sl_dist

                        # 1m resolve (swap mode + non-partial 일 때만)
                        result_int = 0  # 0=OK, 1=SL, 2=TP, 3=NO_ENTRY
                        if mode == 0 and is_partial == 0:
                            need_resolve = (l[i] <= sl_edge) or (h[i] >= tp_edge)
                            if need_resolve:
                                result_int = resolve_entry_bar_jit(
                                    h1m, l1m, valid_1m, i, tf_minutes,
                                    ep_i, sl_edge, tp_edge, 1)

                        if result_int == 3:
                            # NO_ENTRY → OB 유지, 진입 skip, SHORT 도 skip
                            entered = True
                        elif result_int == 1:
                            # SL on entry bar
                            pnl_raw = (sl_edge - ep_i) * size_v
                            ef = ep_i * size_v * maker_fee
                            xf = sl_edge * size_v * taker_fee
                            net = pnl_raw - ef - xf
                            cap += net
                            if cap < 0: cap = 0.0
                            out_entry[n_trades] = i
                            out_exit[n_trades] = i
                            out_dir[n_trades] = 1
                            out_ep[n_trades] = ep_i
                            out_xp[n_trades] = sl_edge
                            out_sl[n_trades] = sl_edge
                            out_tp[n_trades] = tp_edge
                            out_lev[n_trades] = lev_
                            out_size[n_trades] = size_v
                            out_reason[n_trades] = 1
                            out_pnl[n_trades] = net
                            out_bal[n_trades] = cap
                            n_trades += 1
                            if cap > peak: peak = cap
                            dd = (peak - cap) / peak if peak > 0 else 0.0
                            if dd > max_dd: max_dd = dd
                            long_n = 0
                            entered = True
                            if cap <= 0: break
                        elif result_int == 2:
                            # TP on entry bar
                            pnl_raw = (tp_edge - ep_i) * size_v
                            ef = ep_i * size_v * maker_fee
                            xf = tp_edge * size_v * maker_fee
                            net = pnl_raw - ef - xf
                            cap += net
                            if cap < 0: cap = 0.0
                            out_entry[n_trades] = i
                            out_exit[n_trades] = i
                            out_dir[n_trades] = 1
                            out_ep[n_trades] = ep_i
                            out_xp[n_trades] = tp_edge
                            out_sl[n_trades] = sl_edge
                            out_tp[n_trades] = tp_edge
                            out_lev[n_trades] = lev_
                            out_size[n_trades] = size_v
                            out_reason[n_trades] = 2
                            out_pnl[n_trades] = net
                            out_bal[n_trades] = cap
                            n_trades += 1
                            if cap > peak: peak = cap
                            dd = (peak - cap) / peak if peak > 0 else 0.0
                            if dd > max_dd: max_dd = dd
                            long_n = 0
                            entered = True
                            if cap <= 0: break
                        else:
                            # OK: 정상 진입, exit 는 다음 봉부터
                            position = 1
                            entry_price = ep_i
                            entry_idx = i
                            sz = size_v
                            sz_total = size_v
                            sl_p = sl_edge
                            tp_p = tp_edge
                            tp1_p = tp1_edge
                            tp2_p = tp2_edge
                            tp1_hit = False
                            liq_p = liq_edge
                            lev = lev_
                            long_n = 0
                            entered = True

            # SHORT
            if not entered and htf_bear and short_n > 0:
                best_k = -1
                best_bar = -1
                for k in range(short_n):
                    if mode == 0:
                        cond = short_bar[k] < i and h[i] >= short_bot[k]
                    else:
                        cond = short_bar[k] < i and short_bot[k] <= c[i] <= short_top[k]
                    if cond and short_bar[k] > best_bar:
                        best_bar = short_bar[k]
                        best_k = k
                if best_k >= 0:
                    if mode == 0:
                        ep_i = short_bot[best_k]
                        if ep_i > h[i]: ep_i = h[i]
                        if ep_i < l[i]: ep_i = l[i]
                    else:
                        ep_i = c[i]
                    sl_edge = short_top[best_k] * (1.0 + sl_buffer_pct)
                    sl_dist = sl_edge - ep_i
                    if sl_dist > 0:
                        sl_pct_v = sl_dist / ep_i
                        eff_sl = sl_pct_v + taker_fee * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > max_lev: lev_ = max_lev
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size_v = notional / ep_i
                        liq_edge = ep_i * (1.0 + 1.0 / lev_)
                        tp_edge = ep_i - rr * sl_dist
                        tp1_edge = ep_i - rr1 * sl_dist
                        tp2_edge = ep_i - rr2 * sl_dist

                        # 1m resolve (swap mode + non-partial 만)
                        result_int = 0
                        if mode == 0 and is_partial == 0:
                            need_resolve = (h[i] >= sl_edge) or (l[i] <= tp_edge)
                            if need_resolve:
                                result_int = resolve_entry_bar_jit(
                                    h1m, l1m, valid_1m, i, tf_minutes,
                                    ep_i, sl_edge, tp_edge, -1)

                        if result_int == 3:
                            entered = True
                        elif result_int == 1:
                            pnl_raw = (ep_i - sl_edge) * size_v
                            ef = ep_i * size_v * maker_fee
                            xf = sl_edge * size_v * taker_fee
                            net = pnl_raw - ef - xf
                            cap += net
                            if cap < 0: cap = 0.0
                            out_entry[n_trades] = i
                            out_exit[n_trades] = i
                            out_dir[n_trades] = -1
                            out_ep[n_trades] = ep_i
                            out_xp[n_trades] = sl_edge
                            out_sl[n_trades] = sl_edge
                            out_tp[n_trades] = tp_edge
                            out_lev[n_trades] = lev_
                            out_size[n_trades] = size_v
                            out_reason[n_trades] = 1
                            out_pnl[n_trades] = net
                            out_bal[n_trades] = cap
                            n_trades += 1
                            if cap > peak: peak = cap
                            dd = (peak - cap) / peak if peak > 0 else 0.0
                            if dd > max_dd: max_dd = dd
                            short_n = 0
                            entered = True
                            if cap <= 0: break
                        elif result_int == 2:
                            pnl_raw = (ep_i - tp_edge) * size_v
                            ef = ep_i * size_v * maker_fee
                            xf = tp_edge * size_v * maker_fee
                            net = pnl_raw - ef - xf
                            cap += net
                            if cap < 0: cap = 0.0
                            out_entry[n_trades] = i
                            out_exit[n_trades] = i
                            out_dir[n_trades] = -1
                            out_ep[n_trades] = ep_i
                            out_xp[n_trades] = tp_edge
                            out_sl[n_trades] = sl_edge
                            out_tp[n_trades] = tp_edge
                            out_lev[n_trades] = lev_
                            out_size[n_trades] = size_v
                            out_reason[n_trades] = 2
                            out_pnl[n_trades] = net
                            out_bal[n_trades] = cap
                            n_trades += 1
                            if cap > peak: peak = cap
                            dd = (peak - cap) / peak if peak > 0 else 0.0
                            if dd > max_dd: max_dd = dd
                            short_n = 0
                            entered = True
                            if cap <= 0: break
                        else:
                            position = -1
                            entry_price = ep_i
                            entry_idx = i
                            sz = size_v
                            sz_total = size_v
                            sl_p = sl_edge
                            tp_p = tp_edge
                            tp1_p = tp1_edge
                            tp2_p = tp2_edge
                            tp1_hit = False
                            liq_p = liq_edge
                            lev = lev_
                            short_n = 0
                            entered = True

        # ============ Invalidation / max_wait ============
        # 진입했으면 큐가 이미 비어있어서 noop
        k = 0
        while k < long_n:
            if c[i] < long_bot[k] or (i - long_bar[k]) > max_wait:
                # remove element k by shifting
                for kk in range(k, long_n - 1):
                    long_top[kk] = long_top[kk + 1]
                    long_bot[kk] = long_bot[kk + 1]
                    long_bar[kk] = long_bar[kk + 1]
                long_n -= 1
            else:
                k += 1
        k = 0
        while k < short_n:
            if c[i] > short_top[k] or (i - short_bar[k]) > max_wait:
                for kk in range(k, short_n - 1):
                    short_top[kk] = short_top[kk + 1]
                    short_bot[kk] = short_bot[kk + 1]
                    short_bar[kk] = short_bar[kk + 1]
                short_n -= 1
            else:
                k += 1

    # Force close remainder
    if position != 0:
        px = c[n - 1]
        if position == 1:
            pnl_raw = (px - entry_price) * sz
        else:
            pnl_raw = (entry_price - px) * sz
        ef = entry_price * sz * entry_fee_rate
        xf = px * sz * taker_fee
        net = pnl_raw - ef - xf
        cap += net
        if cap < 0: cap = 0.0
        out_entry[n_trades] = entry_idx
        out_exit[n_trades] = n - 1
        out_dir[n_trades] = position
        out_ep[n_trades] = entry_price
        out_xp[n_trades] = px
        out_sl[n_trades] = sl_p
        out_tp[n_trades] = tp_p
        out_lev[n_trades] = lev
        out_size[n_trades] = sz
        out_reason[n_trades] = 0  # END
        out_pnl[n_trades] = net
        out_bal[n_trades] = cap
        n_trades += 1
        if cap > peak: peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd

    return (out_entry[:n_trades], out_exit[:n_trades], out_dir[:n_trades],
            out_ep[:n_trades], out_xp[:n_trades], out_sl[:n_trades], out_tp[:n_trades],
            out_lev[:n_trades], out_size[:n_trades], out_reason[:n_trades],
            out_pnl[:n_trades], out_bal[:n_trades], cap, max_dd)


_DATA_CACHE = {}  # (symbol, tf, START, END) -> (h, l, c, htf_close, htf_ema, h1m, l1m, valid_1m, tf_minutes, ts)


def _get_data(symbol, tf, version, use_htf):
    """데이터 로드 + 1m 정렬을 캐시. 같은 worker 가 여러 combo 돌릴 때 재사용."""
    key = (symbol, tf, START, END, use_htf)
    if key in _DATA_CACHE:
        return _DATA_CACHE[key]

    df = load_data(symbol, tf)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    n = len(df)

    if use_htf:
        htf_close, htf_ema = build_htf_arrays(df)
    else:
        htf_close = np.full(n, np.nan)
        htf_ema = np.full(n, np.nan)

    tf_minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60}.get(tf, 15)
    h1m, l1m, valid_1m = build_1m_arrays(df, symbol, tf_minutes)
    if h1m is None:
        # fallback: 빈 배열 (resolve 호출 시 NO_ENTRY 반환되겠지만 need_resolve=False 면 영향 없음)
        h1m = np.zeros((n, tf_minutes), dtype=np.float64)
        l1m = np.zeros((n, tf_minutes), dtype=np.float64)
        valid_1m = np.zeros((n, tf_minutes), dtype=np.bool_)

    bundle = (h, l, c, htf_close, htf_ema, h1m, l1m, valid_1m, tf_minutes, df['timestamp'])
    _DATA_CACHE[key] = bundle
    return bundle


def run_backtest(symbol, tf, version,
                 sl_buffer_pct, rr, max_wait, risk_per_trade, min_fvg_pct,
                 mode='swap', use_htf=None,
                 is_partial=False, rr1=1.0, rr2=2.0, be_after_tp1=False):
    """
    JIT 가속 백테스트.

    mode: 'swap' or 'market'
    version: 'v6_1', 'v6_2', 'v6_htf' 는 use_htf=True (자동), 'v3'/'v4'/'v5' 는 False
    is_partial: True 면 partial TP (50% TP1 + 50% TP2). rr 무시, rr1/rr2 사용.
    be_after_tp1: True 면 TP1 hit 후 SL 을 entry 로 이동 (breakeven)
    """
    if use_htf is None:
        use_htf = version in ('v6_htf', 'v6_1', 'v6_2')

    h, l, c, htf_close, htf_ema, h1m, l1m, valid_1m, tf_minutes, ts = _get_data(symbol, tf, version, use_htf)
    n = len(h)

    mode_int = 0 if mode == 'swap' else 1
    is_partial_int = 1 if is_partial else 0
    be_int = 1 if be_after_tp1 else 0

    result = _sim(h, l, c, htf_close, htf_ema, use_htf, n,
                  h1m, l1m, valid_1m, tf_minutes,
                  sl_buffer_pct, rr, max_wait, risk_per_trade, min_fvg_pct,
                  TAKER_FEE, MAKER_FEE, MAX_LEV, MAX_FVG_QUEUE,
                  INITIAL_CAPITAL, mode_int,
                  is_partial_int, rr1, rr2, be_int)

    (e_idx, x_idx, d, ep, xp, sl, tp, lev, size, reason, pnl, bal, cap, max_dd) = result

    # convert to list of dicts
    reason_str = ['END', 'SL', 'TP', 'LIQ', 'TP1']
    trades = []
    for i in range(len(e_idx)):
        trades.append({
            'entry_time': ts.iloc[int(e_idx[i])],
            'exit_time': ts.iloc[int(x_idx[i])],
            'direction': 'LONG' if d[i] == 1 else 'SHORT',
            'entry_price': float(ep[i]),
            'exit_price': float(xp[i]),
            'take_profit': float(tp[i]),
            'stop_loss': float(sl[i]),
            'leverage': round(float(lev[i]), 2),
            'size': round(float(size[i]), 8),
            'reason': reason_str[int(reason[i])],
            'pnl': round(float(pnl[i]), 4),
            'balance': round(float(bal[i]), 4),
        })

    return trades, float(cap), float(max_dd)

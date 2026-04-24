"""
FVG Retest 백테스트 공통 모듈.

모든 16개 winning 조합이 이 모듈의 run_backtest()를 호출하여 trade-by-trade
CSV (backtest_hyper_scalper_v2_ema20.py 와 동일 포맷) 를 생성합니다.

CSV columns:
  entry_time, exit_time, direction, entry_price, exit_price,
  take_profit, stop_loss, leverage, size, reason, pnl, balance

Partial TP (v7) 는 TP1 과 final close (TP2/SL/LIQ) 를 각각 별도 row 로 기록.

[v2] 진입봉 1m 판별 추가:
  - 진입봉에서 SL/TP 조건이 함께 성립하면 1m 캔들로 실제 순서 판별
  - 진입가 미도달 → 거래 skip (OB 유지)
  - 진입 후 SL/TP → 즉시 해당 결과로 처리
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
END = '2026-03-02'


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


def load_1m_data(symbol: str):
    """1m OHLCV 로드. 없으면 None 반환."""
    for path in [f'../historical_data/{symbol}_1m_futures.csv',
                 f'historical_data/{symbol}_1m_futures.csv']:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=['timestamp'])
            return df.set_index('timestamp')[['high', 'low']]
    return None


def resolve_entry_bar_1m(bar1m, entry_ts, ep, sl_p, tp_p, direction, tf_minutes):
    """
    1m 캔들로 진입봉 내 순서 판별.

    Returns:
        'OK'       - 진입 확인, entry bar 내 SL/TP 없음 → 다음 bar 처리
        'NO_ENTRY' - 1m상 진입가 미도달 → 거래 skip
        'SL'       - 진입 후 SL 먼저 hit (또는 진입봉에서 즉시 SL)
        'TP'       - 진입 후 TP 먼저 hit
    """
    if bar1m is None:
        return 'OK'

    entered = False
    for offset in range(tf_minutes):
        t1 = entry_ts + pd.Timedelta(minutes=offset)
        if t1 not in bar1m.index:
            continue
        h1 = bar1m.loc[t1, 'high']
        l1 = bar1m.loc[t1, 'low']

        if not entered:
            entry_hit = (l1 <= ep) if direction == 1 else (h1 >= ep)
            if not entry_hit:
                continue
            entered = True

        # 진입된 1m 봉부터 SL/TP 체크
        if direction == 1:
            sl_hit = l1 <= sl_p
            tp_hit = h1 >= tp_p
        else:
            sl_hit = h1 >= sl_p
            tp_hit = l1 <= tp_p

        if sl_hit and tp_hit:
            return 'SL'   # 같은 봉 → 보수적
        elif sl_hit:
            return 'SL'
        elif tp_hit:
            return 'TP'

    if not entered:
        return 'NO_ENTRY'

    return 'OK'


def build_htf_arrays(df):
    """5m/15m -> 1h 집계 후 EMA200. 각 bar 에 직전 '닫힌' 1h 값을 매핑."""
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


def run_backtest(symbol, tf, version,
                 sl_buffer_pct,
                 rr=None, rr1=None, rr2=None, be_after_tp1=0,
                 max_wait=20,
                 risk_per_trade=0.02,
                 min_fvg_pct=0.0,
                 use_htf=None):
    """
    version: 'v2'/'v3'/'v4'/'v5' (no HTF, single TP)
             'v6_htf'/'v6_1'/'v6_2' (HTF, single TP)
             'v7_partial' (HTF, partial TP)
    """
    if use_htf is None:
        use_htf = version in ('v6_htf', 'v6_1', 'v6_2', 'v7_partial')
    is_partial = (version == 'v7_partial')

    tf_minutes = int(tf.replace('m', ''))

    df = load_data(symbol, tf)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    ts = df['timestamp']
    n = len(c)

    if use_htf:
        htf_close, htf_ema = build_htf_arrays(df)
    else:
        htf_close = np.full(n, np.nan)
        htf_ema = np.full(n, np.nan)

    # 1m 데이터 로드 (없으면 None → 기존 방식 fallback)
    bar1m = load_1m_data(symbol)

    cap = INITIAL_CAPITAL
    peak = cap
    max_dd = 0.0

    # pending FVGs
    long_top = []
    long_bot = []
    long_bar = []
    short_top = []
    short_bot = []
    short_bar = []

    # position state
    position = 0
    entry_time = None
    entry_price = 0.0
    entry_idx = -1
    sz_total = 0.0
    sz_remain = 0.0
    sl_p = 0.0
    tp1_p = 0.0
    tp2_p = 0.0
    tp_p = 0.0
    liq_p = 0.0
    lev = 1.0
    tp1_hit = False

    trades = []

    def append_trade(exit_time, exit_price, reason, size, pnl_val, balance):
        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'LONG' if position == 1 else 'SHORT',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'take_profit': tp2_p if is_partial else tp_p,
            'stop_loss': sl_p,
            'leverage': round(lev, 2),
            'size': round(size, 8),
            'reason': reason,
            'pnl': round(pnl_val, 4),
            'balance': round(balance, 4),
        })

    def reset_position():
        nonlocal position, tp1_hit, sz_total, sz_remain
        position = 0
        tp1_hit = False
        sz_total = 0.0
        sz_remain = 0.0

    def process_sl_exit(bar_i, exit_price):
        """SL 체결 처리 (진입봉 포함). cap/peak/max_dd 갱신."""
        nonlocal cap, peak, max_dd
        if position == 1:
            pnl_raw = (exit_price - entry_price) * sz_remain
        else:
            pnl_raw = (entry_price - exit_price) * sz_remain
        entry_fee = entry_price * sz_remain * MAKER_FEE
        exit_fee  = exit_price * sz_remain * TAKER_FEE
        net = pnl_raw - entry_fee - exit_fee
        cap += net
        if cap < 0:
            cap = 0.0
        append_trade(ts.iloc[bar_i], exit_price, 'SL', sz_remain, net, cap)
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        reset_position()

    def process_tp_exit(bar_i, exit_price):
        """TP 체결 처리 (진입봉 포함)."""
        nonlocal cap, peak, max_dd
        if position == 1:
            pnl_raw = (exit_price - entry_price) * sz_remain
        else:
            pnl_raw = (entry_price - exit_price) * sz_remain
        entry_fee = entry_price * sz_remain * MAKER_FEE
        exit_fee  = exit_price * sz_remain * MAKER_FEE
        net = pnl_raw - entry_fee - exit_fee
        cap += net
        if cap < 0:
            cap = 0.0
        append_trade(ts.iloc[bar_i], exit_price, 'TP', sz_remain, net, cap)
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        reset_position()

    for i in range(2, n):
        # EXIT (진입봉 다음 bar 부터)
        if position != 0 and i > entry_idx:
            # LIQ
            liq_hit = False
            if position == 1 and l[i] <= liq_p:
                liq_hit = True
            elif position == -1 and h[i] >= liq_p:
                liq_hit = True
            if liq_hit:
                if position == 1:
                    pnl_raw = (liq_p - entry_price) * sz_remain
                else:
                    pnl_raw = (entry_price - liq_p) * sz_remain
                entry_fee = entry_price * sz_remain * MAKER_FEE
                exit_fee = liq_p * sz_remain * TAKER_FEE
                net = pnl_raw - entry_fee - exit_fee
                cap += net
                if cap < 0:
                    cap = 0.0
                append_trade(ts.iloc[i], liq_p, 'LIQ', sz_remain, net, cap)
                if cap > peak:
                    peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
                reset_position()
                if cap <= 0:
                    break
                continue

            # SL
            sl_hit = False
            if position == 1 and l[i] <= sl_p:
                sl_hit = True
            elif position == -1 and h[i] >= sl_p:
                sl_hit = True
            if sl_hit:
                if position == 1:
                    pnl_raw = (sl_p - entry_price) * sz_remain
                else:
                    pnl_raw = (entry_price - sl_p) * sz_remain
                entry_fee = entry_price * sz_remain * MAKER_FEE
                exit_fee = sl_p * sz_remain * TAKER_FEE
                net = pnl_raw - entry_fee - exit_fee
                cap += net
                if cap < 0:
                    cap = 0.0
                append_trade(ts.iloc[i], sl_p, 'SL', sz_remain, net, cap)
                if cap > peak:
                    peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
                reset_position()
                if cap <= 0:
                    break
                continue

            if is_partial:
                # TP1
                if not tp1_hit:
                    tp1_touch = False
                    if position == 1 and h[i] >= tp1_p:
                        tp1_touch = True
                    elif position == -1 and l[i] <= tp1_p:
                        tp1_touch = True
                    if tp1_touch:
                        sz_half = sz_total * 0.5
                        if position == 1:
                            pnl_raw = (tp1_p - entry_price) * sz_half
                        else:
                            pnl_raw = (entry_price - tp1_p) * sz_half
                        entry_fee = entry_price * sz_half * MAKER_FEE
                        exit_fee = tp1_p * sz_half * MAKER_FEE
                        net = pnl_raw - entry_fee - exit_fee
                        cap += net
                        append_trade(ts.iloc[i], tp1_p, 'TP1', sz_half, net, cap)
                        tp1_hit = True
                        sz_remain = sz_total - sz_half
                        if be_after_tp1 == 1:
                            sl_p = entry_price
                        if cap > peak:
                            peak = cap

                # TP2
                if tp1_hit:
                    tp2_touch = False
                    if position == 1 and h[i] >= tp2_p:
                        tp2_touch = True
                    elif position == -1 and l[i] <= tp2_p:
                        tp2_touch = True
                    if tp2_touch:
                        if position == 1:
                            pnl_raw = (tp2_p - entry_price) * sz_remain
                        else:
                            pnl_raw = (entry_price - tp2_p) * sz_remain
                        entry_fee = entry_price * sz_remain * MAKER_FEE
                        exit_fee = tp2_p * sz_remain * MAKER_FEE
                        net = pnl_raw - entry_fee - exit_fee
                        cap += net
                        if cap < 0:
                            cap = 0.0
                        append_trade(ts.iloc[i], tp2_p, 'TP2', sz_remain, net, cap)
                        if cap > peak:
                            peak = cap
                        dd = (peak - cap) / peak if peak > 0 else 0.0
                        if dd > max_dd:
                            max_dd = dd
                        reset_position()
                        if cap <= 0:
                            break
                        continue
            else:
                # single TP
                tp_touch = False
                if position == 1 and h[i] >= tp_p:
                    tp_touch = True
                elif position == -1 and l[i] <= tp_p:
                    tp_touch = True
                if tp_touch:
                    if position == 1:
                        pnl_raw = (tp_p - entry_price) * sz_remain
                    else:
                        pnl_raw = (entry_price - tp_p) * sz_remain
                    entry_fee = entry_price * sz_remain * MAKER_FEE
                    exit_fee = tp_p * sz_remain * MAKER_FEE
                    net = pnl_raw - entry_fee - exit_fee
                    cap += net
                    if cap < 0:
                        cap = 0.0
                    append_trade(ts.iloc[i], tp_p, 'TP', sz_remain, net, cap)
                    if cap > peak:
                        peak = cap
                    dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd:
                        max_dd = dd
                    reset_position()
                    if cap <= 0:
                        break
                    continue

        if cap <= 0:
            break

        # FVG detection
        if l[i] > h[i-2]:
            gap_top = l[i]
            gap_bot = h[i-2]
            if (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if len(long_top) < MAX_FVG_QUEUE:
                    long_top.append(gap_top)
                    long_bot.append(gap_bot)
                    long_bar.append(i)
        if h[i] < l[i-2]:
            gap_top = l[i-2]
            gap_bot = h[i]
            if (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if len(short_top) < MAX_FVG_QUEUE:
                    short_top.append(gap_top)
                    short_bot.append(gap_bot)
                    short_bar.append(i)

        # Invalidation / max wait
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

        # ENTRY (only if no position)
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

            # LONG
            if htf_bull and len(long_top) > 0:
                best_k = -1
                best_bar = -1
                for k in range(len(long_top)):
                    if long_bar[k] < i and l[i] <= long_top[k]:
                        if long_bar[k] > best_bar:
                            best_bar = long_bar[k]; best_k = k
                if best_k >= 0:
                    ep_i = long_top[best_k]
                    if ep_i > h[i]: ep_i = h[i]
                    if ep_i < l[i]: ep_i = l[i]
                    sl_edge = long_bot[best_k] * (1.0 - sl_buffer_pct)
                    sl_dist = ep_i - sl_edge
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep_i
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > MAX_LEV: lev_ = MAX_LEV
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size = notional / ep_i
                        liq_edge = ep_i * (1.0 - 1.0 / lev_)
                        tp_edge = ep_i + rr * sl_dist if not is_partial else 0.0
                        tp1_edge = ep_i + rr1 * sl_dist if is_partial else 0.0
                        tp2_edge = ep_i + rr2 * sl_dist if is_partial else 0.0

                        # 진입봉 SL/TP 동시 조건 체크
                        check_tp = tp2_edge if is_partial else tp_edge
                        need_resolve = (l[i] <= sl_edge) or (h[i] >= check_tp)

                        if need_resolve and not is_partial:
                            result = resolve_entry_bar_1m(
                                bar1m, ts.iloc[i], ep_i, sl_edge, tp_edge, 1, tf_minutes)
                        else:
                            result = 'OK'

                        if result == 'NO_ENTRY':
                            continue  # OB 유지, 거래 skip

                        # 포지션 셋업
                        entry_price = ep_i
                        entry_time = ts.iloc[i]
                        entry_idx = i
                        sz_total = size
                        sz_remain = size
                        sl_p = sl_edge
                        liq_p = liq_edge
                        lev = lev_
                        tp_p = tp_edge
                        tp1_p = tp1_edge
                        tp2_p = tp2_edge
                        tp1_hit = False
                        position = 1

                        if result == 'SL':
                            process_sl_exit(i, sl_p)
                            # OB는 진입 후 처리했으므로 clear
                            long_top.clear(); long_bot.clear(); long_bar.clear()
                            if cap <= 0: break
                            continue
                        elif result == 'TP':
                            process_tp_exit(i, tp_p)
                            long_top.clear(); long_bot.clear(); long_bar.clear()
                            if cap <= 0: break
                            continue
                        else:
                            long_top.clear(); long_bot.clear(); long_bar.clear()
                            continue

            # SHORT
            if htf_bear and len(short_top) > 0:
                best_k = -1
                best_bar = -1
                for k in range(len(short_top)):
                    if short_bar[k] < i and h[i] >= short_bot[k]:
                        if short_bar[k] > best_bar:
                            best_bar = short_bar[k]; best_k = k
                if best_k >= 0:
                    ep_i = short_bot[best_k]
                    if ep_i > h[i]: ep_i = h[i]
                    if ep_i < l[i]: ep_i = l[i]
                    sl_edge = short_top[best_k] * (1.0 + sl_buffer_pct)
                    sl_dist = sl_edge - ep_i
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep_i
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > MAX_LEV: lev_ = MAX_LEV
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size = notional / ep_i
                        liq_edge = ep_i * (1.0 + 1.0 / lev_)
                        tp_edge = ep_i - rr * sl_dist if not is_partial else 0.0
                        tp1_edge = ep_i - rr1 * sl_dist if is_partial else 0.0
                        tp2_edge = ep_i - rr2 * sl_dist if is_partial else 0.0

                        check_tp = tp2_edge if is_partial else tp_edge
                        need_resolve = (h[i] >= sl_edge) or (l[i] <= check_tp)

                        if need_resolve and not is_partial:
                            result = resolve_entry_bar_1m(
                                bar1m, ts.iloc[i], ep_i, sl_edge, tp_edge, -1, tf_minutes)
                        else:
                            result = 'OK'

                        if result == 'NO_ENTRY':
                            continue

                        entry_price = ep_i
                        entry_time = ts.iloc[i]
                        entry_idx = i
                        sz_total = size
                        sz_remain = size
                        sl_p = sl_edge
                        liq_p = liq_edge
                        lev = lev_
                        tp_p = tp_edge
                        tp1_p = tp1_edge
                        tp2_p = tp2_edge
                        tp1_hit = False
                        position = -1

                        if result == 'SL':
                            process_sl_exit(i, sl_p)
                            short_top.clear(); short_bot.clear(); short_bar.clear()
                            if cap <= 0: break
                            continue
                        elif result == 'TP':
                            process_tp_exit(i, tp_p)
                            short_top.clear(); short_bot.clear(); short_bar.clear()
                            if cap <= 0: break
                            continue
                        else:
                            short_top.clear(); short_bot.clear(); short_bar.clear()
                            continue

    # Force close remainder
    if position != 0:
        px = c[-1]
        if position == 1:
            pnl_raw = (px - entry_price) * sz_remain
        else:
            pnl_raw = (entry_price - px) * sz_remain
        entry_fee = entry_price * sz_remain * MAKER_FEE
        exit_fee = px * sz_remain * TAKER_FEE
        net = pnl_raw - entry_fee - exit_fee
        cap += net
        if cap < 0:
            cap = 0.0
        append_trade(ts.iloc[-1], px, 'END', sz_remain, net, cap)
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return trades, cap, max_dd


def save_trades(trades, filename):
    if not trades:
        print("No trades")
        return
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
    tps = [t for t in trades if t['reason'] in ('TP', 'TP1', 'TP2')]

    print(f"\n=== Summary ===")
    print(f"Total trades    : {tt}")
    print(f"  LONG / SHORT  : {len(longs)} / {len(shorts)}")
    print(f"Wins (pnl>0)    : {len(wins)}  WR: {len(wins)/tt*100 if tt>0 else 0:.2f}%")
    print(f"SL  / TP(any)   : {len(sls)} / {len(tps)}")
    print(f"LIQ             : {len(liqs)}")
    print(f"Max Drawdown    : {max_dd*100:.2f}%")
    print(f"Initial → Final : {INITIAL_CAPITAL:.2f} → {cap:.2f}")
    print(f"Return          : {(cap/INITIAL_CAPITAL-1)*100:+.2f}%")

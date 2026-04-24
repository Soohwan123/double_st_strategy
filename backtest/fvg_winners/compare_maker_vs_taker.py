"""
진입 Maker (Limit) vs Taker (Market) 비교.

대상 설정:
  04 BTC 15m MDD60 (v6_1): SL=0.003, RR=1.3, WAIT=25, RPT=0.03
  10 ETH 15m MDD60 (v3):   SL=0.005, RR=1.5, WAIT=20, RPT=0.02
  15 XRP 15m MDD60 (v6_2): SL=0.0045, RR=1.4, WAIT=15, RPT=0.025

기간:
  - 2020-01-06 ~ 2026-03-02 (전체)
  - 2024-01-06 ~ 2026-03-02 (최근 2년)

6 runs = 3 설정 × 2 기간 × (Maker + Taker 각각) → 실제로 6 설정 × 2 버전 = 12 runs.
"""
import sys
import numpy as np
import pandas as pd
import _common as C

# 3 configs to test
CONFIGS = [
    {
        'label': '04_BTC_15m_mdd60',
        'symbol': 'BTCUSDT', 'tf': '15m', 'version': 'v6_1',
        'sl_buffer_pct': 0.003, 'rr': 1.3, 'max_wait': 25,
        'risk_per_trade': 0.03, 'min_fvg_pct': 0.0,
    },
    {
        'label': '10_ETH_15m_mdd60',
        'symbol': 'ETHUSDT', 'tf': '15m', 'version': 'v3',
        'sl_buffer_pct': 0.005, 'rr': 1.5, 'max_wait': 20,
        'risk_per_trade': 0.02, 'min_fvg_pct': 0.0,
    },
    {
        'label': '15_XRP_15m_mdd60',
        'symbol': 'XRPUSDT', 'tf': '15m', 'version': 'v6_2',
        'sl_buffer_pct': 0.0045, 'rr': 1.4, 'max_wait': 15,
        'risk_per_trade': 0.025, 'min_fvg_pct': 0.0,
    },
]

PERIODS = [
    ('2020', '2020-01-06', '2026-03-02'),
    ('2024', '2024-01-06', '2026-03-02'),
]

def run_with_entry_fee(config, start, end, entry_fee_mode):
    """entry_fee_mode: 'maker' or 'taker'"""
    # Monkey-patch _common's fee behavior for entry
    # Simplest: temporarily override MAKER_FEE to TAKER_FEE when entry_fee_mode='taker'
    saved_maker = C.MAKER_FEE
    saved_start = C.START
    saved_end = C.END
    if entry_fee_mode == 'taker':
        C.MAKER_FEE = C.TAKER_FEE  # make entry = TAKER
        # but exit TP also becomes taker. We want ONLY entry to be taker.
        # → Need a proper implementation. Revert and do different approach.
        C.MAKER_FEE = saved_maker
    C.START = start
    C.END = end

    # Use a new sim function with entry fee override
    trades, cap, mdd = run_backtest_with_fee(config, entry_fee_mode)

    C.START = saved_start
    C.END = saved_end
    return trades, cap, mdd


def run_backtest_with_fee(config, entry_fee_mode):
    """Runs custom backtest with chosen entry fee."""
    # Need access to internals. Inline a minimal copy of run_backtest logic
    # but with entry_fee = TAKER if 'taker', else MAKER (original).
    from _common import (load_data, build_htf_arrays, calc_ema, INITIAL_CAPITAL,
                         TAKER_FEE, MAKER_FEE, MAX_LEV, MAX_FVG_QUEUE, HTF_EMA_LEN)

    symbol = config['symbol']; tf = config['tf']; version = config['version']
    sl_buffer_pct = config['sl_buffer_pct']
    rr = config.get('rr'); rr1 = config.get('rr1'); rr2 = config.get('rr2')
    be_after_tp1 = config.get('be_after_tp1', 0)
    max_wait = config['max_wait']
    risk_per_trade = config['risk_per_trade']
    min_fvg_pct = config.get('min_fvg_pct', 0.0)

    use_htf = version in ('v6_htf', 'v6_1', 'v6_2', 'v7_partial')
    is_partial = (version == 'v7_partial')

    entry_fee_rate = TAKER_FEE if entry_fee_mode == 'taker' else MAKER_FEE

    df = load_data(symbol, tf)
    h = df['high'].values.astype(np.float64)
    l = df['low'].values.astype(np.float64)
    c = df['close'].values.astype(np.float64)
    n = len(c)

    if use_htf:
        htf_close, htf_ema = build_htf_arrays(df)
    else:
        htf_close = np.full(n, np.nan)
        htf_ema = np.full(n, np.nan)

    cap = INITIAL_CAPITAL
    peak = cap
    max_dd = 0.0

    long_top = []; long_bot = []; long_bar = []
    short_top = []; short_bot = []; short_bar = []

    position = 0
    entry_price = 0.0; entry_idx = -1
    sz_total = 0.0; sz_remain = 0.0
    sl_p = 0.0; tp1_p = 0.0; tp2_p = 0.0; tp_p = 0.0; liq_p = 0.0
    lev = 1.0
    tp1_hit = False
    tt = 0; wins = 0; losses = 0; liqs = 0; sls = 0; tps = 0

    def reset():
        nonlocal position, tp1_hit, sz_total, sz_remain
        position = 0; tp1_hit = False; sz_total = 0.0; sz_remain = 0.0

    for i in range(2, n):
        if position != 0 and i > entry_idx:
            # LIQ
            liq_hit = (position == 1 and l[i] <= liq_p) or (position == -1 and h[i] >= liq_p)
            if liq_hit:
                if position == 1:
                    pnl = (liq_p - entry_price) * sz_remain
                else:
                    pnl = (entry_price - liq_p) * sz_remain
                ef = entry_price * sz_remain * entry_fee_rate
                xf = liq_p * sz_remain * TAKER_FEE
                net = pnl - ef - xf
                cap += net
                if cap < 0: cap = 0.0
                tt += 1; liqs += 1
                if cap > peak: peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd: max_dd = dd
                reset()
                if cap <= 0: break
                continue
            # SL
            sl_hit = (position == 1 and l[i] <= sl_p) or (position == -1 and h[i] >= sl_p)
            if sl_hit:
                if position == 1:
                    pnl = (sl_p - entry_price) * sz_remain
                else:
                    pnl = (entry_price - sl_p) * sz_remain
                ef = entry_price * sz_remain * entry_fee_rate
                xf = sl_p * sz_remain * TAKER_FEE
                net = pnl - ef - xf
                cap += net
                if cap < 0: cap = 0.0
                tt += 1; sls += 1
                if net > 0: wins += 1
                else: losses += 1
                if cap > peak: peak = cap
                dd = (peak - cap) / peak if peak > 0 else 0.0
                if dd > max_dd: max_dd = dd
                reset()
                if cap <= 0: break
                continue
            # TP (single or partial)
            if is_partial:
                if not tp1_hit:
                    tp1_touch = (position == 1 and h[i] >= tp1_p) or (position == -1 and l[i] <= tp1_p)
                    if tp1_touch:
                        sz_half = sz_total * 0.5
                        if position == 1:
                            pnl = (tp1_p - entry_price) * sz_half
                        else:
                            pnl = (entry_price - tp1_p) * sz_half
                        ef = entry_price * sz_half * entry_fee_rate
                        xf = tp1_p * sz_half * MAKER_FEE
                        net = pnl - ef - xf
                        cap += net
                        tp1_hit = True
                        sz_remain = sz_total - sz_half
                        if be_after_tp1 == 1: sl_p = entry_price
                        if cap > peak: peak = cap
                if tp1_hit:
                    tp2_touch = (position == 1 and h[i] >= tp2_p) or (position == -1 and l[i] <= tp2_p)
                    if tp2_touch:
                        if position == 1:
                            pnl = (tp2_p - entry_price) * sz_remain
                        else:
                            pnl = (entry_price - tp2_p) * sz_remain
                        ef = entry_price * sz_remain * entry_fee_rate
                        xf = tp2_p * sz_remain * MAKER_FEE
                        net = pnl - ef - xf
                        cap += net
                        if cap < 0: cap = 0.0
                        tt += 1; tps += 1; wins += 1
                        if cap > peak: peak = cap
                        dd = (peak - cap) / peak if peak > 0 else 0.0
                        if dd > max_dd: max_dd = dd
                        reset()
                        if cap <= 0: break
                        continue
            else:
                tp_touch = (position == 1 and h[i] >= tp_p) or (position == -1 and l[i] <= tp_p)
                if tp_touch:
                    if position == 1:
                        pnl = (tp_p - entry_price) * sz_remain
                    else:
                        pnl = (entry_price - tp_p) * sz_remain
                    ef = entry_price * sz_remain * entry_fee_rate
                    xf = tp_p * sz_remain * MAKER_FEE
                    net = pnl - ef - xf
                    cap += net
                    if cap < 0: cap = 0.0
                    tt += 1; tps += 1
                    if net > 0: wins += 1
                    else: losses += 1
                    if cap > peak: peak = cap
                    dd = (peak - cap) / peak if peak > 0 else 0.0
                    if dd > max_dd: max_dd = dd
                    reset()
                    if cap <= 0: break
                    continue

        if cap <= 0: break

        # FVG detection
        if l[i] > h[i-2]:
            gap_top = l[i]; gap_bot = h[i-2]
            if (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if len(long_top) < MAX_FVG_QUEUE:
                    long_top.append(gap_top); long_bot.append(gap_bot); long_bar.append(i)
        if h[i] < l[i-2]:
            gap_top = l[i-2]; gap_bot = h[i]
            if (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                if len(short_top) < MAX_FVG_QUEUE:
                    short_top.append(gap_top); short_bot.append(gap_bot); short_bar.append(i)

        # Invalidation
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

        if position == 0:
            htf_bull = True; htf_bear = True
            if use_htf:
                if np.isnan(htf_ema[i]): htf_bull = False; htf_bear = False
                else:
                    htf_bull = htf_close[i] > htf_ema[i]
                    htf_bear = htf_close[i] < htf_ema[i]

            if htf_bull and len(long_top) > 0:
                best_k = -1; best_bar = -1
                for k in range(len(long_top)):
                    if long_bar[k] < i and l[i] <= long_top[k]:
                        if long_bar[k] > best_bar:
                            best_bar = long_bar[k]; best_k = k
                if best_k >= 0:
                    ep = long_top[best_k]
                    if ep > h[i]: ep = h[i]
                    if ep < l[i]: ep = l[i]
                    sl_edge = long_bot[best_k] * (1.0 - sl_buffer_pct)
                    sl_dist = ep - sl_edge
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > MAX_LEV: lev_ = MAX_LEV
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size = notional / ep
                        entry_price = ep; entry_idx = i
                        sz_total = size; sz_remain = size
                        sl_p = sl_edge; liq_p = ep * (1.0 - 1.0 / lev_); lev = lev_
                        if is_partial:
                            tp1_p = ep + rr1 * sl_dist; tp2_p = ep + rr2 * sl_dist
                        else:
                            tp_p = ep + rr * sl_dist
                        tp1_hit = False; position = 1
                        long_top.clear(); long_bot.clear(); long_bar.clear()
                        continue

            if htf_bear and len(short_top) > 0:
                best_k = -1; best_bar = -1
                for k in range(len(short_top)):
                    if short_bar[k] < i and h[i] >= short_bot[k]:
                        if short_bar[k] > best_bar:
                            best_bar = short_bar[k]; best_k = k
                if best_k >= 0:
                    ep = short_bot[best_k]
                    if ep > h[i]: ep = h[i]
                    if ep < l[i]: ep = l[i]
                    sl_edge = short_top[best_k] * (1.0 + sl_buffer_pct)
                    sl_dist = sl_edge - ep
                    if sl_dist > 0:
                        sl_pct = sl_dist / ep
                        eff_sl = sl_pct + TAKER_FEE * 2.0
                        lev_ = risk_per_trade / eff_sl
                        if lev_ > MAX_LEV: lev_ = MAX_LEV
                        if lev_ < 1.0: lev_ = 1.0
                        notional = cap * lev_
                        size = notional / ep
                        entry_price = ep; entry_idx = i
                        sz_total = size; sz_remain = size
                        sl_p = sl_edge; liq_p = ep * (1.0 + 1.0 / lev_); lev = lev_
                        if is_partial:
                            tp1_p = ep - rr1 * sl_dist; tp2_p = ep - rr2 * sl_dist
                        else:
                            tp_p = ep - rr * sl_dist
                        tp1_hit = False; position = -1
                        short_top.clear(); short_bot.clear(); short_bar.clear()
                        continue

    # force close
    if position != 0:
        px = c[-1]
        if position == 1:
            pnl = (px - entry_price) * sz_remain
        else:
            pnl = (entry_price - px) * sz_remain
        ef = entry_price * sz_remain * entry_fee_rate
        xf = px * sz_remain * TAKER_FEE
        net = pnl - ef - xf
        cap += net
        if cap < 0: cap = 0.0
        tt += 1
        if net > 0: wins += 1
        else: losses += 1
        if cap > peak: peak = cap
        dd = (peak - cap) / peak if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd

    return tt, wins, losses, cap, max_dd, liqs, sls, tps


def main():
    print(f"{'=' * 110}")
    print(f"{'Config':<20} {'Period':<6} {'Entry':<6} {'Trades':<7} {'WR%':<6} {'MDD%':<7} {'Return%':<14} {'Final':<14}")
    print(f"{'=' * 110}")

    for cfg in CONFIGS:
        for pname, pstart, pend in PERIODS:
            C.START = pstart
            C.END = pend
            for entry_mode in ('maker', 'taker'):
                tt, wins, _, cap, mdd, _, _, _ = run_backtest_with_fee(cfg, entry_mode)
                wr = wins / tt * 100 if tt > 0 else 0
                ret = (cap / C.INITIAL_CAPITAL - 1) * 100
                print(f"{cfg['label']:<20} {pname:<6} {entry_mode:<6} {tt:<7} {wr:<6.2f} {mdd*100:<7.2f} {ret:<+14.2f} {cap:<14,.2f}")
            print('-' * 110)

if __name__ == '__main__':
    main()

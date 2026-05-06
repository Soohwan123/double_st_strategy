# Breakout LIVE vs BT 비교 검증 방법

## 목적

LIVE breakout 전략이 BT 와 동일하게 동작하는지 검증. 신호 누락 (LIVE 진입 X but BT 진입) 이나 spurious 신호 (LIVE 진입 but BT 진입 X) 검출.

## 핵심 원칙

**BT 시뮬 시 LIVE 와 동일한 history window 사용**.

LIVE 는 시작 시 `n_bars = max(2000, 5*L)` 만 fetch 해서 trendline 시뮬. BT 가 6년치 데이터로 시뮬하면 누적 차이 발생 (4 ticks 정도). LIVE 와 BT 매칭하려면:
1. LIVE 시작 시각 (state 의 첫 entry_time 또는 process start time) 확인
2. BT 시뮬을 LIVE 시작 직전 2000 봉부터 시작
3. LIVE 시작 시각부터 NOW 까지의 trade 비교

## 검증 절차

### 1. LIVE 정보 수집

```python
# state 에서 진행 정보
state = json.load('breakout_strategy/state/state_breakout_xxx.json')
candle_manager = state['candle_manager']  # upper, lower, slope_ph, upos, dnos, last_processed_ts

# log 에서 시작 시각 + 처리 봉
grep "5m | " logs/breakout_xxx_*.log | head  # 첫 처리 봉
grep "ENTRY\|EXIT" trades/trades_breakout_xxx.csv  # LIVE trades
```

### 2. BT 데이터 fetch (LIVE 와 동일 window)

```python
LIVE_START = pd.Timestamp('YYYY-MM-DD HH:MM', tz='UTC')  # LIVE 첫 처리 봉
NOW = pd.Timestamp.now(tz='UTC').floor('5min')

# LIVE 가 fetch 한 동일 2000 bars
df = fetch_klines(symbol, '5m', LIVE_START, n_bars=2000)
# LIVE 시작 후 봉도 추가
df_more = fetch_klines(symbol, '5m', NOW, n_bars=대략_LIVE_지속시간/5min)
df = pd.concat([df, df_more]).drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
```

### 3. BT trendline iteration (`_common.py:91+` 와 동일)

```python
LENGTH = 150  # XRP 또는 180 SOL
MULT = 1.1   # XRP 또는 0.47 SOL
SL_ATR = 7.0  # XRP 또는 4.2 SOL
RR = 2.0     # XRP 또는 1.1 SOL
RPT = 0.06   # XRP 또는 0.08 SOL

L = LENGTH
atr = calc_atr(h, l, c, L)  # Wilder RMA
upper, lower, slope_ph, slope_pl = 0, 0, 0, 0
upper_init, lower_init = False, False
upos, dnos = 0, 0
trades = []

for i in range(2*L+1, n):
    # EXIT (BT 는 진입봉 다음 부터)
    if position != 0 and i > entry_idx:
        ...
    # pivot 검출 (양 쪽 L 봉 비교)
    pi = i - L
    is_ph = all(h[k] < h[pi] for k in range(i-2L, i+1) if k != pi)
    is_pl = all(l[k] > l[pi] for k in range(i-2L, i+1) if k != pi)
    slope_now = atr[pi] * MULT / L
    if is_ph: upper, slope_ph = h[pi], slope_now; upper_init = True
    elif upper_init: upper -= slope_ph
    if is_pl: lower, slope_pl = l[pi], slope_now; lower_init = True
    elif lower_init: lower += slope_pl
    # threshold + breakout
    up_th = upper - slope_ph * L
    dn_th = lower + slope_pl * L
    prev_upos, prev_dnos = upos, dnos
    if is_ph: upos = 0
    elif c[i] > up_th: upos = 1
    if is_pl: dnos = 0
    elif c[i] < dn_th: dnos = 1
    up_break = upos > prev_upos
    dn_break = dnos > prev_dnos
    # ENTRY
    if position == 0 and upper_init and lower_init:
        if up_break and not dn_break: ... LONG ...
        elif dn_break and not up_break: ... SHORT ...

    # 시점별 trendline state 기록
    if df['ts'].iloc[i] == 비교_시점:
        print(f"upper={upper}, lower={lower}, up_th={up_th}, c[i]={c[i]}")
```

### 4. LIVE trades vs BT trades 비교

| 비교 항목 | LIVE | BT |
|---|---|---|
| 진입 봉 ts | `state.entry_time` | trades[i]['entry_time'] |
| 방향 | LONG/SHORT | LONG/SHORT |
| 진입가 | `state.entry_price` (시장가 fill) | c[i] (close 기준) |
| SL | `state.stop_loss` | `ep ± atr[i] × SL_ATR_MULT` |
| TP | `state.take_profit` | `ep ± rr × sl_dist` |
| 청산 | `trades_csv` 의 SL/TP/EMERGENCY | trades[i]['reason'] |

### 5. 누락 검사

- BT 에 있는 entry 가 LIVE 에 없으면 → 누락
- LIVE 에 있는 entry 가 BT 에 없으면 → spurious

### 알려진 차이 / 한계

1. **price_feed +0s polling stale**: 봉 마감 직후 1-2 ticks 차이 가능. 신호 임계점 근처에서 LIVE 만 미감지.
   - 검증: LIVE 가 받은 close vs Binance 후속 fetch 의 close 비교 (price_feed log)
   - Fix: REST_POLL_OFFSETS 를 +0s 제거하고 +5s 부터 시작
2. **History 길이 차이**: BT 6년 vs LIVE 2000 봉 → trendline 누적 4 ticks 차이. 보통 결정적이지 않음.
3. **시장가 진입 슬리피지**: BT ep=c[i], LIVE 시장가 fill 가격. 보통 1-3 ticks 차이.
4. **진입봉 안 SL/TP/LIQ 처리 차이**: BT 는 진입봉 무시 (`i > entry_idx`), LIVE 는 거래소 자동 (1-2초 placement gap). 영향 작음.

## 사례: 2026-05-01 03:25 UTC XRP 진입 누락

- BT entry: LONG @ $1.3784 (c[i]=1.3784, up_th=1.378281, break ✓)
- LIVE: 진입 X (close 받은 값 1.3782, up_th=1.378273, break ✗)
- 원인: price_feed +0s polling 이 stale close (1.3782) 받음. 실제 final close 는 1.3784.
- 결정적 차이: 0.0002 (2 ticks). LIVE up_th 와 거리가 짧아 결정적.

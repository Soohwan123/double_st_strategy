# FVG Backtest 수정사항 (`_common_swap.py` / `_common_market.py`)

작성일: 2026-04-26

## 배경

LIVE 운영 중 거래 trade-by-trade 비교에서 **백테스트(`_common.py`) 와 LIVE 의 거래수/방향 차이** 발견.
근본 원인 분석 결과 `_common.py` 에 **look-ahead bias (미래 데이터 사용)** 이 숨어있음을 확인.
원본 winners 의 +9.25e+13% 같은 수익률은 이 bias 덕분의 가짜 수익으로 판명.

원본 `_common.py` 는 건드리지 않고, look-ahead 를 제거한 두 가지 spec 으로 새 모듈 만들어 비교 실험:
- `_common_swap.py` — limit 진입 + entry/invalidation 순서 변경
- `_common_market.py` — close-기반 시장가 진입 (limit 폐기)

---

## 핵심 발견: 원본 `_common.py` 의 look-ahead bias

### 코드 순서 (원본)

```python
for i in ...:
    # 1. EXIT 처리
    # 2. FVG 감지 (l[i], h[i], l[i-2], h[i-2] 사용)
    # 3. Invalidation: c[i] < bot 이면 큐에서 제거
    # 4. ENTRY: l[i] <= top 이면 진입 at top
```

### 물리적 시간 순서

봉 i 시작 → 가격이 high/low 거치며 움직임 → close

거래소 LIMIT 의 실제 동작:
- limit 은 봉 시작 전에 거래소에 올라가 있음
- 가격이 limit price 통과하는 **순간** 자동 체결 (봉 close 전)
- 한 번 체결되면 **취소 불가**

### 무엇이 문제인가

원본 BT 의 처리 3 (invalidation) 은 c[i] (이번 봉 close) 를 사용:
- c[i] 는 봉 끝나야 알 수 있음
- BT 는 처리 4 (entry) 전에 처리 3 (invalidation) 적용 → "봉 close 알고 있다는 가정" 으로 미래에 무효화될 limit 을 미리 제거
- 즉 **체결 후 close 가 bot 깬 거 보고 "그 체결 무효화"** 와 동일 효과
- → CLAUDE.md `1. 미래 데이터 절대 금지` 위반

### 실제 케이스 (SOL 2026-04-25 07:00 UTC)

봉 OHLC: O=86.40 H=86.41 **L=86.20** **C=86.28**

LONG FVG: top=86.36, bot=86.31

이 봉에서:
- low 86.20 ≤ top 86.36 → 체결 조건 ✓ (가격이 86.36 통과해 86.20 까지 빠짐)
- close 86.28 < bot 86.31 → 무효화 조건 ✓ (close 가 1봉 high 아래)

원본 BT: invalidation 우선 → 진입 안 함 (가짜 수익 케이스)
LIVE 거래소: limit 가 86.36 통과시 자동 체결, close 시점엔 이미 진입 끝 → 진입함

**원본 BT 는 close 를 미리 봐서 위험한 진입을 회피** = look-ahead.

### 영향: 풀 백테스트로 입증된 수익률 차이

`_common_swap.py` (look-ahead 제거) 로 SOL/XRP 풀 백테스트 (2020-2026, CAP=$1000, MAX_LEV=90):

| | 원본 (`_common.py`) | SWAP (`_common_swap.py`) |
|---|---|---|
| **bt_25 SOL v6_1** | +9.25e+13% / MDD 49% | **-100% (청산)** |
| **bt_27 XRP v6_1** | +2.37e+08% / MDD 49% | **-100% (청산)** |

연도별로도 모두 마이너스. 원본 winners 파라미터는 look-ahead 의존이라 현실에서 **절대 재현 불가**.

---

## 수정 모듈 #1: `_common_swap.py`

### 변경: ENTRY 와 INVALIDATION 순서 SWAP

```
원본 순서:                      SWAP 순서:
1. EXIT                         1. EXIT
2. FVG 감지                     2. FVG 감지
3. Invalidation (c[i] 기반)     3. ENTRY (l[i] <= top, 진입가=top)  ← 먼저
4. ENTRY (l[i] <= top)          4. Invalidation (c[i] 기반)         ← 나중
```

### 의미

- 같은 봉에서 close 가 bot 위반해도 그 전에 limit fill 가능 → 진입함
- 무효화는 c[i] 기준이지만 **다음 봉 entry 부터 적용** → look-ahead 제거
- 거래소 LIMIT 의 실제 동작과 일치

### Diff

원본 vs SWAP 의 코드 차이는 invalidation 블록의 위치 한 곳뿐:

```diff
- # 원본: ENTRY 위에 invalidation
- if c[i] < bot: invalidate
- ...
- # ENTRY
- if l[i] <= top: enter at top

+ # SWAP
+ # ENTRY
+ if l[i] <= top: enter at top
+ ...
+ # invalidation (다음 봉부터 적용)
+ if c[i] < bot: invalidate
```

---

## 수정 모듈 #2: `_common_market.py`

### 변경: Limit 진입 → Close-기반 시장가 진입

### 진입 조건 (LONG)
- 어떤 봉 i 에서 `bot ≤ c[i] ≤ top` (close 가 FVG 영역 안에 있음)
- 진입가 = c[i] (close 가격, 시장가)
- 즉 close 가 1봉 high 아래로 안 내려가고 (close ≥ bot), close 가 FVG 안에 있을 때 시장가 진입

### 진입 조건 (SHORT)
- 어떤 봉 i 에서 `bot ≤ c[i] ≤ top` (SHORT FVG 도 top > bot, close 가 FVG 영역 안)
- 진입가 = c[i]

### 의미
- 봉 close 시점에서 결정 → 실거래에서 봉 마감 직후 시장가 주문 → 다음 봉 시작 가격에 체결
- look-ahead 없음 (모든 정보는 봉 close 이후 알려진 것)
- LIMIT 진입 자체를 폐기해서 "limit 가 fill 됐는지" 라는 모호한 판정 불필요
- 진입가는 실제 시장가 (taker fee 적용) — 원본 BT 의 maker fee 보다 비쌈

### 코드 변경
- LONG/SHORT entry 블록을 `bot ≤ c[i] ≤ top` 조건 + `ep_i = c[i]` 로 교체
- 진입봉 1m intrabar resolve 제거 (봉 close 시점 진입이라 같은 봉 SL/TP 체크 무의미)
- entry_fee 계산을 `MAKER_FEE` → `TAKER_FEE` 로 변경 (시장가 진입)

---

## 검증 결과 (CAP=$200, MAX_LEV=5x, 2026-04-24 12:15 UTC ~ 04-26)

| 심볼 | 원본 BT | SWAP BT | LIVE | SWAP↔LIVE 일치 |
|---|---|---|---|---|
| XRP | 4건 | 4건 | 4건 | ✅ entry/방향/가격 100% |
| SOL | 5건 | **6건** | 6건 | ✅ 04-25 07:00 LONG 까지 잡음 |
| ETH | 3건 | 4건 | 3건 | ⚠️ 별개 hysteresis 이슈 |

ETH 는 v3 (HTF 없음) 로 양방향 valid 가능 → LIVE 의 40/60 hysteresis 와 BT 의 LONG-priority 차이 별도 존재. 본 수정 무관.

---

## 풀 백테스트 결과 — 두 모듈 비교 예정

### bt_25 SOL v6_1 (원본 파라미터: RR=1.2, SL_BUF=0.003, MAX_WAIT=10, RPT=0.03)
- 원본: +9.25e+13% / MDD 49% (look-ahead 가짜)
- SWAP: -100% / MDD 100% (청산)
- MARKET: smoke test (2026-04-01~04-27, CAP=$1000) → 52 trades, MDD 39%, cap=$628 (월 -37%)

### bt_27 XRP v6_1 (원본 파라미터: RR=1.2, SL_BUF=0.004, MAX_WAIT=20, RPT=0.02)
- 원본: +2.37e+08% / MDD 49% (look-ahead 가짜)
- SWAP: -100% / MDD 100% (청산)
- MARKET: 풀 백테스트 예정

→ 원본 winners 파라미터는 두 spec 모두에서 부적합. **재최적화 필수**.

---

## 영향 범위 — 재최적화 필요

### 그리드 서치 대상

`_common_swap.py` 와 `_common_market.py` 두 spec 으로 각각 grid search:

**파라미터 그리드 후보**:
- `sl_buffer_pct`: 0.001 ~ 0.01 (step 0.0005)
- `rr` (TP/SL ratio): 1.0 ~ 3.0 (step 0.1)
- `max_wait`: 5 ~ 50 (step 5)
- `risk_per_trade`: 0.005 ~ 0.05 (step 0.005)
- `min_fvg_pct`: 0.0 ~ 0.005 (step 0.0005)

총 combo 수 가늠: 19 × 21 × 10 × 10 × 11 ≈ 440k 조합. 둘 다 + 두 심볼 → 약 175만 백테스트.

다른 컴퓨터에서 grid 좁히고 단계적 narrowing 권장 (winners 워크플로우 9.5 절차).

### 현재 진행 상태
1. ✅ `_common_swap.py` 작성, 단기 LIVE 비교 (XRP/SOL 100% 매칭 확인)
2. ✅ `_common_market.py` 작성, smoke test 통과
3. ⏳ Grid search (두 spec, SOL/XRP) — 다른 컴퓨터에서 진행 예정
4. ⏳ 결과 정리 후 LIVE 파라미터 교체 + 재기동

### LIVE 운영 일시 중단 고려

원본 winners 파라미터는 look-ahead 의존이라 현실에서 청산 위험 있음.
재최적화 완료까지 LIVE FVG 전략 (3 심볼) **일시 중단 또는 자본 더 축소** 권장.

---

## 첨부 파일 (다른 컴퓨터 Claude 에 넘길 것)

1. `_common.py` — 원본 (look-ahead 있음, 비교용)
2. `_common_swap.py` — SWAP 버전 (limit 진입, entry/invalidation 순서 swap)
3. `_common_market.py` — MARKET 버전 (close-기반 시장가 진입)
4. `bt_25_SOL_15m_mdd50_v6_1_1m.py` — SOL 현재 파라미터 (`from _common import` → 각 모듈로 변경)
5. `bt_27_XRP_15m_mdd50_v6_1_1m.py` — XRP 현재 파라미터
6. `historical_data/SOLUSDT_{1m,15m}_futures.csv`
7. `historical_data/XRPUSDT_{1m,15m}_futures.csv`
8. 본 문서 (`FVG_BT_FIXES.md`)

### 재최적화 절차 권장

1. 두 모듈 (`_common_swap.py`, `_common_market.py`) 각각 grid search
2. 각각 Top 30 (MDD ≤ 50, no LIQ, trades ≥ 50, 풀 기간 양수) 추출
3. SWAP 결과 vs MARKET 결과 비교 → 어느 spec 이 LIVE 와 더 정합적인지 결정
4. 선정된 spec + 파라미터로 LIVE 재기동

---

## 변경하지 않은 것 (의도)

- `_common.py` 는 원본 그대로 (winners 결과 보존, look-ahead 인지 후 폐기 검토 대상)
- ETH(v3) 의 LONG/SHORT 양방향 valid 케이스는 별개 이슈 (LIVE 40/60 hysteresis vs BT LONG-priority)
- 사이즈/레버리지/SL-TP 우선순위 등 다른 모든 로직

---

# 부록: JIT 가속 버전 (`_common_jit.py`) 및 작업 중 발견한 추가 버그

작성일: 2026-04-26 (1차 정리 이후 후속 작업 기록)

## 배경

원본 `_common.py` / `_common_swap.py` / `_common_market.py` 모두 sim 루프가 순수 Python (Python list pop/append/clear, closure 함수, pandas Timestamp `iloc[i]` 호출 등) 라
6년치 (2020-2026) 풀 백테스트 1 combo 당 약 2.5초 소요. Grid search (4,200~15,000 combo) 가
~10-30분 걸려 iteration 매우 느림.

→ Numba `@njit` 으로 sim 루프 재작성한 `_common_jit.py` 추가. **combo 당 0.05-0.1초** 로 약 30-50배 가속.

## `_common_jit.py` 주요 설계

1. **단일 `@njit(cache=True)` `_sim()` 함수** 로 전체 봉 루프 처리
   - Python list → numpy 고정크기 배열 + 카운터 (FVG queue)
   - Closure 함수 (`process_sl_exit`, `reset_position` 등) → 모두 인라인
   - pandas Timestamp → `int64` index 만 사용 (timestamp 변환은 결과 후처리 단계로 분리)

2. **Mode 플래그**: `mode=0` (SWAP, limit 진입) / `mode=1` (MARKET, close 시장가 진입) — 단일 파일에서 두 spec 동시 지원.

3. **데이터 캐시** (`_DATA_CACHE`): `(symbol, tf, START, END, use_htf)` 별 OHLCV/HTF/1m 배열 캐싱.
   같은 worker 가 grid 안에서 여러 combo 돌릴 때 재사용 → 첫 call 만 ~10s, 이후 0.05-0.1s.

## 작업 중 발견한 추가 버그들

### 버그 #1: `build_htf_arrays` 의 O(n²) Python loop (재발성 흔한 함정)

**증상**: JIT 압축 후에도 풀 백테스트 1 combo 당 60초+ (오히려 느려짐).

**원인**: `_common_jit.py` 의 `build_htf_arrays` 를 작성할 때 시간 매핑을 단순한 이중 for-loop 로 짬:
```python
for i in range(len(ts)):  # n=210k for SOL 15m
    for j in range(len(hr_starts)):  # ~52k 1h bars
        if hr_starts[j] < ...:
            last_idx = j
        else:
            break
```
→ ~10G 비교 연산.

**수정**: 원본 `_common.py` 처럼 dict lookup (`hour_to_idx[hour_starts.iloc[i]]`) 사용. O(n) 으로.

**교훈**: pandas/numpy 가 아닌 일반 Python 으로 시간 매핑하면 데이터 크면 즉시 폭발. dict / np.searchsorted 둘 중 하나 필수.

### 버그 #2: 진입봉 SL/TP "fake-TP" 처리 (look-ahead 이외의 새로운 종류)

**증상**: 동일 파라미터로 `_common_jit.py` (mode=swap) 와 `_common_swap.py` 비교 시
- JIT: 6,731 trades, cap = $2.85B (+285M%)
- PY: 6,732 trades, cap = $0.06 (-99.99%)

거래 수 거의 같은데 결과가 9 자릿수 차이.

**원인**: 진입봉 SL/TP 동시 도달 케이스 처리.

원본 `_common.py` / `_common_swap.py` 는 진입 후 같은 봉에서 SL 또는 TP 가능 여부를 체크할 때:
```python
need_resolve = (l[i] <= sl_edge) or (h[i] >= check_tp)
if need_resolve:
    result = resolve_entry_bar_1m(bar1m, ...)  # 1m 봉 walk
else:
    result = 'OK'
```
즉 같은 봉의 15m 으로는 "SL/TP 가능성 만" 보고, 실제 순서는 **1m 으로 walk** 해서 판정 (`'NO_ENTRY'`/`'SL'`/`'TP'`/`'OK'`).

JIT 첫 구현 (잘못된 버전):
```python
eb_sl = l[i] <= sl_edge
eb_tp = h[i] >= tp_edge
if eb_sl: # SL 처리
elif eb_tp: # TP 처리 ← 여기가 fake !
else: # 정상 진입
```

문제: 15m bar 의 high 가 tp_edge 를 단순히 닿았다는 게 = "TP 체결" 이 아니다. 1m 순서가 중요:
- 봉 시작가가 entry 위 → 가격이 위로 올라가 tp 까지 갔다가 → 다시 내려와 entry 도달
- 거래소 LIMIT 은 가격이 entry 통과하는 순간 (=봉 끝나기 직전) 체결
- TP 도달은 **체결 전** 일어남 → 그건 그냥 봉 high, TP 체결 아님

JIT 코드는 1m 순서를 모르고 단순히 "h[i] >= tp" 로 보고 TP 로 기록 → 실제론 다음 봉 SL 맞을 거래를 미리 +수익으로 처리 → 통계적 가짜 우위.

**검증**: 거래수는 같은데 (양쪽 모두 같은 entry 결정) outcome 만 다른 건 exit 처리 차이 → 진입봉 처리 결함.

**수정 1차**: 진입봉 SL/TP 분기 제거, 모든 진입을 'OK' (정상 진입) 로 처리. `_common_swap.py` 의 "1m 데이터 없을 때" 동작과 일치. 이걸로 이미 결과 -100% 근처로 거의 일치.

**수정 2차 (최종)**: 1m resolve 도 JIT 으로 구현 (`resolve_entry_bar_jit`). 1m h/l 배열을 (n_15m, tf_minutes) shape 로 사전계산 (`build_1m_arrays`) 후 JIT 함수에 넘김. 결과: `_common_swap.py` 와 **474/474 거래 100% 일치**.

### 버그 #3: 거래소 한 번 체결되면 취소 못 함 → "BT 가 미래 close 로 진입 무효화" 자체가 look-ahead

(이미 본 문서 위쪽에 정리됨. 여기선 구현 측면만)

`_common.py` 의 처리 순서:
```
1. EXIT
2. FVG 감지
3. Invalidation (c[i] 기반)  ← 같은 봉 close 가 bot 깨면 FVG 큐에서 제거
4. ENTRY (l[i] <= top 등)    ← 그 후에 fill 체크
```

**문제**: 거래소 LIMIT 은 fill 이 **봉 close 전** 일어남. 그러나 BT 는 close 가 알려져야 invalidation 결정 가능 → "체결 후 close 보고 무효화" = 미래 데이터 사용.

**수정 (`_common_swap.py`, `_common_jit.py` swap mode)**: 처리 순서를 ENTRY 먼저, INVALIDATION 나중으로 변경.
```
1. EXIT
2. FVG 감지
3. ENTRY              ← Invalidation 보다 먼저
4. Invalidation       ← 다음 봉부터 적용
```

이렇게 하면 같은 봉에서 close 가 bot 위반해도 그 전에 limit fill 되어 진입은 성립 (실제 거래소 동작과 일치).

대안 spec (`_common_market.py`): limit 자체를 폐기하고 "close 가 FVG 영역 안에 있을 때 시장가 진입" 으로 변경. 이 경우 close 가 알려진 후 의사결정 → look-ahead 자체가 없음.

## JIT 검증 (절차)

JIT 결과 검증할 때 **반드시 거래 단위로 1:1 비교**:

```python
import _common_jit as J
import _common_swap as S

# 같은 파라미터, 같은 기간으로 둘 다 실행
trades_j, _, _ = J.run_backtest(symbol='SOLUSDT', tf='15m', version='v6_1', mode='swap', ...)
trades_s, _, _ = S.run_backtest(symbol='SOLUSDT', tf='15m', version='v6_1', ...)

assert len(trades_j) == len(trades_s), '거래수 불일치'
for j, s in zip(trades_j, trades_s):
    assert j['entry_time'] == s['entry_time'], 'entry_time 불일치'
    assert j['reason'] == s['reason'], 'exit reason 불일치'  # SL/TP/LIQ/END
    assert abs(j['pnl'] - s['pnl']) < 0.01, 'pnl 불일치'
```

거래수만 같다고 일치 아님 — outcome (reason/pnl) 도 봐야 함 (위 fake-TP 버그처럼 거래수 같고 outcome 만 다른 케이스 존재).

## 부록: 1m resolve JIT 구현 핵심 코드

```python
def build_1m_arrays(df_15m, symbol, tf_minutes):
    """1m 데이터를 (n_15m, tf_minutes) shape 배열로 정렬."""
    df1 = pd.read_csv(f'{symbol}_1m_futures.csv', parse_dates=['timestamp'])
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


@njit(cache=True)
def resolve_entry_bar_jit(h1m, l1m, valid, bar_idx, tf_minutes, ep, sl, tp, direction):
    """
    Returns: 0=OK, 1=SL on entry bar, 2=TP on entry bar, 3=NO_ENTRY (1m 상 entry 미도달)
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
        # entered 상태에서 SL/TP 체크
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
```

## 부록: 후속 grid search 결과 요약 (참고용)

`_common_jit.py` 로 (수정 완료 후) SOL/XRP/ETH × swap/market 6 grid 돌린 결과:

| spec/sym | trades>=500, MDD<=60% 균형 후보 | 균형 best |
|---|---|---|
| swap SOL | 0 | NONE |
| swap XRP | 0 | NONE |
| swap ETH | 0 | NONE |
| market SOL | 105 | +3,751% MDD 58% trades 608 |
| market XRP | 0 | NONE |
| market ETH | 5 | +812% MDD 59% trades 562 |

대체로 MARKET spec 이 SWAP 보다 안정적인 winner 영역 더 많음.
하지만 사용자 목표 (≥1,200 trades + MDD ≤ 60% + ≥100,000% return) 충족 후보 = **0개**.

→ 추가 단계 (partial TP, ADX/거래량 필터, 다른 진입 spec) 필요 — 본 문서에선 다루지 않음.

---

## 다른 Claude 에 물어볼 때 핵심 체크리스트

1. **"이 BT 코드에 look-ahead 있어?"** — close[i] 를 같은 봉 i 의 fill/entry/exit 결정에 쓰는지 확인.
   특히 invalidation 이 entry 보다 먼저 처리되면서 c[i] 사용하면 거의 확정 look-ahead.
2. **"진입봉 SL/TP 결정에 1m resolve 있어?"** — `(l[i] <= sl) or (h[i] >= tp)` 로 단순 체크 후 SL/TP 기록하면 fake-TP 버그.
3. **"BT vs LIVE trade-by-trade 비교한 적 있어?"** — entry_time / direction / entry_price / exit_price / SL / TP / reason / pnl 8가지 모두 일치해야 함. 거래수만 같고 reason 다르면 의심.
4. **"JIT 버전 만들 때 build_htf_arrays 같은 helper 도 JIT 했는지 또는 dict lookup 썼는지?"** — 순수 Python loop 면 N² 폭발.
5. **"백테스트 풀 결과가 +1억% 같이 비현실적이면 look-ahead 거의 확정"** — 거래소에서 절대 재현 불가능한 spec.

## 수정 완료된 파일 목록

- `_common.py` — 원본 (변경 안 함, 비교용)
- `_common_swap.py` — entry/invalidation 순서 swap (look-ahead 제거 v1, limit 진입)
- `_common_market.py` — close-기반 시장가 진입 (look-ahead 제거 v2, limit 폐기)
- `_common_jit.py` — JIT 가속 + mode 플래그 + 1m resolve JIT 화 (최종)

`_common_jit.py` 가 가장 빠르고 정확. 권장 사용:

```python
import _common_jit as J
J.START = '2020-01-06'; J.END = '2026-04-26'
trades, cap, mdd = J.run_backtest(
    symbol='SOLUSDT', tf='15m', version='v6_1',
    sl_buffer_pct=0.02, rr=3.0, max_wait=50, risk_per_trade=0.02, min_fvg_pct=0.01,
    mode='market',  # or 'swap'
)
```

# Trailing SL Look-Ahead 버그 (`_common_v4.py`)

## 발견 일자
2026-04-29

## 영향 범위
- `_common_v4.py` 의 `run_backtest` (line 99-117)
- 영향 받는 BT 파일: `bt_11_*` ~ `bt_17_*` 전체 (v4 trailing 사용 7종)

---

## 버그 요약

`_common_v4.py` 의 trailing SL 로직이 **같은 봉 안에서**:
1. 봉의 high 를 사용해 trail SL 을 끌어올린 후
2. 같은 봉의 low 와 갱신된 SL 을 비교

이렇게 하면 BT 가 **"high 가 먼저 찍힌 다음 low 가 나왔다"** 라고 implicit 가정. 실거래에선 이 가격 시간 순서를 알 수 없을 뿐만 아니라, **trail SL 을 봉 close 위로 무한정 올리는 것 자체가 거래소에서 불가능**.

---

## 구체적 예시

### 시나리오
- LONG 진입가 100, 초기 SL 90 (atr × SL_ATR_MULT = 10)
- TRAIL_ATR_MULT = 0.6 (bt_15, bt_17 기준)
- 다음 봉 OHLC: **O=100 H=130 L=95 C=120**

### BT 동작 (현재 코드)
```python
# _common_v4.py:99-117
if position != 0 and i > entry_idx:
    # 1. high_since 갱신
    high_since = max(high_since, h[i])  # 100 → 130
    # 2. trail SL 갱신
    new_sl = 130 - 10 × 0.6 = 124
    sl_p = max(90, 124) = 124           # ← SL 갱신됨
    # 3. SL hit 체크 (같은 봉의 low 와)
    if l[i] <= sl_p:                    # 95 ≤ 124 → 트리거!
        exit @ 124                      # BT: "+24 수익 청산" 으로 기록
```

### 실거래 (LIVE) — 시나리오 A: 봉 close 시 STOP_MARKET 갱신
- 봉 close 시점: current price = 120
- STOP_MARKET SELL @ stopPrice 124 placement 시도
- LONG SL trigger 조건: `last_price ≤ stopPrice` → 120 ≤ 124 이미 충족
- **즉시 trigger → MARKET SELL fill ≈ 120**
- 또는 Binance error `-2021 "Order would immediately trigger"` 반환
- 결과: BT 의 124 청산 vs LIVE 의 120 청산 → **4 단위 차이** (lev 곱하면 누적 큼)

### 실거래 — 시나리오 B: tick 기반 실시간 trail
- 봉 안 가격 순서가 `100 → 130 → 95 → 120` 이면:
  - 130 도달 순간 trail 을 124 로 cancel/replace
  - 95 까지 빠지면서 124 trigger → 124 청산 ✓ (BT 와 일치)
- 봉 안 가격 순서가 `100 → 95 → 130 → 120` 이면:
  - 95 시점엔 SL 가 아직 90 (trail 안 올라감) → 90 안 뚫음 → 청산 X
  - 그 후 130 도달 시 trail 124 placement → 청산 X (가격 회복 중)
  - close 120 → 포지션 유지
- **봉 안 가격 시간순서에 따라 다른 결과** — BT 는 한 가지 (자기 유리한) 순서만 가정

### 실거래 — 시나리오 C: 봉 close 마다만 trail
- BT 모델 그대로 → 시나리오 A 와 동일 → 즉시 trigger 120 청산

---

## BT 의 핵심 결함

`_common_v4.py:104-106`:

```python
new_sl = high_since - atr_now * trail_atr_mult
if new_sl > sl_p: sl_p = new_sl
```

**`new_sl > c[i]` 인 케이스에 대한 cap 이 없음**. trail 을 봉 close 위로 무한정 올리고, 같은 봉의 low 와 비교 → look-ahead.

## 정상적인 trail 로직

```python
# 봉 close 시점에 trail 갱신
new_sl = high_since - atr_now * trail_atr_mult

# 핵심 1: close 위로는 못 올림 (placement 즉시 trigger 방지)
new_sl = min(new_sl, c[i] - tick_size)

# 핵심 2: 같은 봉의 low 와 비교는 OLD sl_p 사용 (이번 봉 시작 때의 SL)
# 갱신된 new sl_p 는 NEXT bar 부터 적용
old_sl = sl_p
sl_p = max(sl_p, new_sl)

# SL hit 체크는 old_sl 사용
if l[i] <= old_sl:
    exit @ old_sl  # 이 봉 동안 활성 SL 가격
```

또는 더 보수적:

```python
# trail 은 항상 다음 봉부터 적용
# 1. 이번 봉 EXIT 체크 (이번 봉 시작 시점의 sl_p 사용)
# 2. 봉 close 후 trail 갱신
# 3. 다음 봉 EXIT 체크는 새 sl_p 사용
```

---

## 영향 추정

### 영향 받기 쉬운 봉 패턴
- **반전 wick 봉**: high 찍고 close 가 high 에서 멀리 떨어진 봉
  - 예: 도지/리버설/페이크아웃 봉
- **TRAIL_ATR_MULT 가 작을수록 영향 큼** (트레일이 high 에 가깝게 붙어 close 위로 올라가기 쉬움)
  - bt_15, bt_17: TRAIL=0.6 (가장 영향 큼)
  - bt_16: TRAIL=0.7
  - bt_14: TRAIL=0.8
  - bt_11, 12, 13: TRAIL=1.0 (영향 상대적 작음)

### 왜 이 버그가 천문학 수익을 만드는가
- BT: 큰 wick 봉마다 "trail high 까지 끌어올리고 low 가 그 trail hit" 로 처리 → 비현실적 큰 수익
- 모든 trade 의 청산가가 **봉 close 가 아닌 trail level (close 보다 위)** 으로 기록
- 누적 효과로 **+수만~수억 % 차이** 발생 가능

### 비교
- v17 OB 의 "같은 1m 안 ENTRY+TP 같은 봉 처리" 버그와 **같은 패턴**
- v17 OB 는 fix 후 +42M% → -99% 로 뒤집힘
- v4 trail 도 fix 후 결과 **대폭 하락 (5~10배 또는 -99%)** 가능성

---

## 결론

**bt_11 ~ bt_17 의 모든 결과 (천문학 수익률) 는 이 버그 영향을 받음**. 현재 상태로 LIVE 운영 시 BT 와 큰 차이 (LIVE 가 훨씬 낮은 수익 또는 손실) 발생.

## 수정 필요 사항

1. `_common_v4.py:104-106` 의 trail 갱신 로직을 다음 중 하나로 수정:
   - **옵션 A**: `new_sl = min(new_sl, c[i] - tick)` cap 추가 + 같은 봉 low 체크는 old_sl 사용
   - **옵션 B**: Trail 갱신을 NEXT bar 부터 적용 (이번 봉 EXIT 는 prev sl_p 로 처리)

2. 수정 후 bt_11~17 전체 재실행 → 진짜 edge 가 있는지 확인.

3. 진짜 edge 있는 후보가 남는다면 LIVE 운영 검토.

---

## 참고

- 동일 패턴 버그가 이전에 v17 OB 에서 발견됨 (1m intrabar resolve 의 ENTRY+TP 동시 처리)
- 사용자가 직접 발견 (2026-04-29 대화 중 시나리오 검증)
- BT 코드 변경 시 CLAUDE.md 의 백테스트 절대 원칙 0 (현실성), 1 (look-ahead 금지) 둘 다 준수 필요

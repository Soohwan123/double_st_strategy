# FVG Retest 실제 매매 프로그램 설계서

이 문서는 FVG Retest 전략 (v6 HTF 필터 + v7 Partial TP) 을 **Binance USDⓈ-M Futures** 에서 실제 운용하기 위한 설계서입니다. 백테스트 코드는 `new_fvg_retest_5m_v7_partial.py` 참고.

## 1. 전략 요약

### 1.1 핵심 아이디어
**Fair Value Gap (FVG)** 이 형성된 후 가격이 그 zone 으로 되돌아올 때 (retest) 방향대로 진입.

### 1.2 FVG 정의 (3봉 패턴, 모두 **완성된 봉** 기준)
- **Bullish FVG at bar i**: `low[i] > high[i-2]` → zone = (top=`low[i]`, bot=`high[i-2]`)
- **Bearish FVG at bar i**: `high[i] < low[i-2]` → zone = (top=`low[i-2]`, bot=`high[i]`)

### 1.3 진입/청산 시퀀스
1. Bar i 가 **close** 되면 FVG 감지
2. 큐에 추가 (최대 16개 per 방향)
3. Bar i+1 부터 가격이 zone 에 touch 하면 진입 (Limit)
4. 청산 조건: TP1 (부분), TP2 (나머지), SL, LIQ, 시간초과 (MAX_WAIT bars retest 없으면 취소), 반대편 무효화 (close 가 FVG 반대 edge 돌파)

### 1.4 HTF (1h EMA200) 방향 필터
- 5m 봉 에서 **직전 닫힌 1h 봉** 의 close 와 EMA200 비교
- 1h close > EMA200 → **LONG 만 허용**
- 1h close < EMA200 → **SHORT 만 허용**

### 1.5 사이징 (Risk-based)
```
sl_pct = |entry - sl_price| / entry
eff_sl = sl_pct + taker_fee * 2     # 수수료 protection
lev = RISK_PER_TRADE / eff_sl
lev = min(lev, MAX_LEV=90)
lev = max(lev, 1.0)
notional = balance * lev
size = notional / entry_price
```
SL hit 시 손실이 정확히 `balance * RISK_PER_TRADE` 가 되도록 사이즈 역산.

---

## 2. 백테스트 파라미터 (실제 운용에 쓸 값)

추천 세팅 (BTCUSDT 5m, MDD < 60% 기준):

```yaml
BB:
  SL_BUFFER_PCT: 0.006      # SL 을 FVG 반대편에서 0.6% 더 밖으로
  RR1: 0.8                  # 첫 부분 TP (50% 청산)
  RR2: 1.5                  # 나머지 TP
  BE_AFTER_TP1: false       # TP1 hit 후 SL 을 break-even 으로 이동 안함 (false 가 우월)
  MAX_WAIT: 20              # 20 봉 (= 100분) 내 retest 없으면 setup 취소
  RISK_PER_TRADE: 0.02      # 트레이드당 잔고 2% 손실까지 허용
  MAX_LEV: 90
  HTF_EMA_LEN: 200          # 1h 차트에 EMA200
  MAX_FVG_QUEUE: 16         # 한쪽에 최대 16개 FVG 까지 대기
```

---

## 3. 시스템 아키텍처

### 3.1 컴포넌트 구성
```
┌─────────────────────────────────────────────────────────────┐
│  Main Process (asyncio event loop)                          │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ WS Handler   │→ │ Strategy     │→ │ Order Mgr    │      │
│  │ (Kline, User)│  │ Engine       │  │ (REST)       │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ↓                 ↕                  ↕              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Bar Buffer   │  │ State Store  │  │ Position     │      │
│  │ (5m, 1h)     │  │ (FVG queue,  │  │ Tracker      │      │
│  │              │  │  pending ords)│  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                           ↕                                 │
│                    ┌──────────────┐                         │
│                    │ Risk Guard   │                         │
│                    │ (emergency)  │                         │
│                    └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
         ↕ Persistence
  ┌──────────────┐  ┌──────────────┐
  │ SQLite DB    │  │ Logs         │
  │ (state, trades)  │ (structured) │
  └──────────────┘  └──────────────┘
```

### 3.2 데이터 소스
- **WebSocket**: `kline_5m`, `kline_1h` (방향 필터용), `userData` stream (포지션/주문 업데이트)
- **REST fallback**: WS 끊기면 recent klines 로 gap fill

### 3.3 상태 저장 (crash-safe)
모든 것을 SQLite 에 persist:
- `pending_fvgs` (side, top, bot, created_bar_time)
- `orders` (order_id, type, status, fvg_ref)
- `positions` (entry_price, size, sl, tp1, tp2, tp1_hit, liq_price)
- `balance_snapshots` (주기적)

재시작 시 DB 로부터 상태 복원.

---

## 4. 🚨 실수하기 쉬운 지점 (중요)

### 4.1 봉 완성 타이밍 (Off-by-one)

**문제**: WebSocket kline 데이터는 봉이 진행 중일 때도 계속 업데이트되며, `k.x == true` (kline closed) 플래그가 있어야 "확정된 봉".

**실수 예**:
```python
# ❌ 잘못됨 — 진행 중 봉 사용
async def on_kline(msg):
    bars.append(msg['k'])  # 아직 안 닫힌 봉도 포함
    detect_fvg()
```

**올바른 방식**:
```python
async def on_kline(msg):
    k = msg['k']
    if not k['x']:    # closed 플래그 체크
        return
    bars.append(k)
    detect_fvg()
```

**백테스트와의 대응**: 백테스트는 항상 completed bar 사용. 실전에서 미완성 봉으로 FVG 감지하면 **미래 데이터 사용** (봉이 바뀌면 FVG 사라질 수 있음).

### 4.2 HTF 1h 봉의 "닫힘" 감지

**문제**: 1h 봉은 12 개 5m 봉이 모여서 1h 완성. 5m 봉 close 시점이 매 5분, 1h 봉 close 시점은 매 1시간 정각.

**실수 예**:
```python
# ❌ 항상 현재 5m bar 의 hour 를 기준으로 htf_close 조회
current_hour = current_5m_bar.open_time.floor('1h')
htf_close = get_1h_bar(current_hour).close    # 진행 중 1h bar
```

**올바른 방식**:
```python
# ✅ 직전에 "닫힌" 1h 봉 사용
current_hour_start = current_5m_bar.open_time.floor('1h')
prev_closed_hour = current_hour_start - timedelta(hours=1)
htf_close = get_1h_bar(prev_closed_hour).close
htf_ema = ema200_series[prev_closed_hour]
```

**결과**: 5m bar 내 HTF 기준이 바뀌지 않아야 함. 1시간 동안 같은 HTF trend 유지.

### 4.3 Limit 주문 체결 vs 백테스트 가정

**백테스트 가정**: 바의 low 가 FVG_top 이하로 내려가면 FVG_top 에서 체결 + Maker fee.

**실전 gap 요소**:
1. **주문 placement 지연**: bar close 감지 → 주문 배치까지 100ms~수초
2. **Gap 시나리오**: bar 가 FVG 아래로 갭다운하면 limit 체결 불가 (market 가격이 limit 아래로 지나감)
3. **Partial fill**: 큰 사이즈면 체결 안될수도
4. **주문 거절**: 플랫폼 문제, API rate limit

**권장 구현**:
```python
# FVG 감지 즉시 limit 주문 배치
order = await client.futures_create_order(
    symbol='BTCUSDT',
    side='BUY',
    type='LIMIT',
    timeInForce='GTC',      # 유지
    price=fvg_top,
    quantity=calculated_size,
    reduceOnly=False,
    newClientOrderId=f"fvg_{fvg_id}",  # 추적용
)
```

**추가**: `Post-Only` 플래그 (`timeInForce='GTX'` on Binance) 사용해서 **Taker 체결 절대 방지**. 단, gap 시 아예 체결 안되는 쪽이 Taker fee 먹는것보다 나음.

### 4.4 단일 포지션 vs 여러 FVG Limit 동시 배치

**백테스트 가정**: 한 번에 하나의 포지션, 진입 시 모든 대기 FVG 큐 비움 → 한 번에 하나의 FVG 에만 Limit 주문 유지.

**실수 예**: "FVG 감지할 때마다 limit 주문 걸어두기" 하면 여러 주문 동시 활성 → 가격 급락시 여러 체결 → 백테스트와 다른 동작.

**올바른 구현**:
```python
# 새 FVG 감지 시
async def on_new_fvg(fvg):
    if active_position is not None:
        return  # 포지션 있으면 대기
    if active_pending_order is not None:
        await cancel_order(active_pending_order)   # 기존 주문 취소
    active_pending_order = await place_limit(fvg)  # 새 FVG 에 주문
```

**또는 "최근 FVG 만 active 유지" 방식**:
- FVG 큐에 저장 (MAX_FVG_QUEUE=16)
- 매 bar close 시 가장 최근 유효한 FVG 선택
- 해당 FVG_top 에 limit 유지 (다른 가격이면 취소 후 재배치)

### 4.5 SL / TP 주문 관리

**백테스트**: SL 가격에 touch 하면 즉시 체결 가정.

**실전**: 진입 체결 순간 SL / TP 주문 **반드시 함께 배치**.

**방식 A: OCO (One-Cancels-Other)** — Binance Futures 는 OCO 직접 지원 안함. 별도 주문으로 관리.

**방식 B: Reduce-Only STOP_MARKET + LIMIT**:
```python
# SL: STOP_MARKET
await create_order(
    type='STOP_MARKET', side='SELL', stopPrice=sl_price,
    closePosition=True,    # 포지션 전량 청산
    reduceOnly=True,
)

# TP1: LIMIT (50%)
await create_order(
    type='LIMIT', side='SELL', price=tp1_price,
    quantity=size*0.5,
    reduceOnly=True,
    timeInForce='GTC',
)

# TP2: LIMIT (나머지 50%)
await create_order(
    type='LIMIT', side='SELL', price=tp2_price,
    quantity=size*0.5,
    reduceOnly=True,
    timeInForce='GTC',
)
```

**TP1 체결 감지 후 조치**:
- BE_AFTER_TP1=true 면: 기존 SL 취소 → 새 SL 을 entry_price 에 배치
- SL 주문의 `quantity` 를 남은 50% 로 조정 (`closePosition=True` 쓰면 자동 처리)

### 4.6 Partial TP 후 사이즈 재계산 (v7 로직)

**백테스트** 는 sz_remain 을 정확히 추적. **실전** 은:
- 실제 체결 수량 ≠ 요청 수량 일 수 있음 (partial fill)
- SL 주문의 수량을 **실제 남은 포지션** 기준으로 재계산

**권장**:
```python
async def on_order_filled(order):
    if order.reduce_only and order.status == 'FILLED':
        actual_position = await get_position()   # 현재 실제 포지션 조회
        # SL 주문 수량을 actual_position.size 로 재설정
        await replace_sl_order(actual_position.size, new_sl_price)
```

### 4.7 청산 (LIQ) 처리

**백테스트**: LIQ 가격을 `entry * (1 - 1/lev)` 로 가정하고 touch 시 cap=0, break.

**실전**:
- **Isolated Margin 모드 필수** (cross 면 전체 잔고 날아감)
- 레버리지 설정 API 로 사전 세팅
- LIQ 는 거래소가 자동 처리 → 별도 코드 불필요
- **단 maintenance margin, fee, funding 으로 실제 LIQ 가격은 계산값과 다름**

**보수적 설계**:
```python
# LIQ 훨씬 전에 자체 "강제 청산" SL 설치
forced_sl = entry * (1 - 0.9 / lev)    # LIQ 보다 10% 앞
# 실제 SL 과 비교해서 더 가까운 쪽 사용
```

### 4.8 FVG 무효화 타이밍

**백테스트**: close of bar i 가 FVG 반대편 돌파 시 무효화.

**실수 예**: tick 단위로 체크하면 진행 중 봉에서 잠깐 지나갔다가 돌아와도 무효화됨.

**올바른 구현**: bar close 시에만 close 기준으로 체크.

### 4.9 시간청산 (MAX_WAIT)

**백테스트**: `(i - fvg_bar) > max_wait` 이면 폐기.

**실전**: Limit 주문에 `timeInForce='GTT'` (Good Till Time) 지원 안하므로 직접 관리:
```python
async def periodic_cleanup():
    now = datetime.utcnow()
    for order in active_orders:
        age_bars = (now - order.created_time).total_seconds() / 300  # 5m bar
        if age_bars > MAX_WAIT:
            await cancel_order(order)
```

### 4.10 수수료 정확성

**백테스트 가정**:
- Limit (Maker): 0.02%
- Market/Stop (Taker): 0.05%

**실전 주의사항**:
- VIP 등급, BNB 할인, referral 에 따라 다름
- Maker 주문도 aggressive fill 되면 Taker 로 바뀜
- Post-Only 로 Maker 강제 but gap 놓침 트레이드오프

**실제 fee 를 주기적으로 API 로 확인 (`accountInformation`)** 후 사이징에 반영.

### 4.11 심볼별 tick size / lot size

**실수 예**: 계산된 가격 / 수량을 그대로 주문 → API 에서 거부.

**필수 처리**:
```python
# Symbol filters 조회 (앱 시작시 한번)
info = await client.futures_exchange_info()
for s in info['symbols']:
    if s['symbol'] == 'BTCUSDT':
        tick = float(get_filter(s, 'PRICE_FILTER')['tickSize'])
        step = float(get_filter(s, 'LOT_SIZE')['stepSize'])

# 주문 전 rounding
price = round_to(price, tick)
qty = round_to(qty, step)
```

### 4.12 `reduceOnly` 플래그 필수

SL / TP 주문은 반드시 `reduceOnly=True`. 안 그러면 반대 방향 신규 포지션 생김 (특히 Hedge 모드에서).

### 4.13 시간 동기화

Binance 는 request timestamp 가 서버 시간과 **1000ms 이내** 여야 함. NTP 동기화 필수.

---

## 5. Risk Guard (비상 정지)

### 5.1 일일 손실 제한
```python
daily_loss = (start_of_day_balance - current_balance) / start_of_day_balance
if daily_loss > 0.10:    # 일 10% 손실
    await close_all_positions()
    await cancel_all_orders()
    halt_trading(duration='until_next_day')
```

### 5.2 연속 손실 제한
- 연속 5회 SL → 30분 cool-down
- 연속 10회 SL → 당일 종료

### 5.3 잔고 하한
```python
if balance < INITIAL_CAPITAL * 0.3:
    halt_forever()  # 수동 개입 필요
```

### 5.4 연결 끊김 대응
- WebSocket disconnect 감지 → 즉시 재연결 시도
- 30초 이상 데이터 없음 → 포지션 **시장가 청산** (보수적)

---

## 6. 테스트 / 배포 절차

### 6.1 단계별 Rollout
1. **Paper Trading (1~2주)**: Binance Testnet 에서 실제 시그널 / 주문 흐름 검증
2. **Live 1x leverage (1개월)**: 소액 ($100~$500), 레버리지 1 로 로직만 확인
3. **Live 목표 leverage (1개월)**: RISK_PER_TRADE 절반으로 시작
4. **Full deployment**: 목표 설정

### 6.2 모니터링 지표
- Fill rate: 백테스트 vs 실전 (목표 80%+)
- Avg slippage: FVG_top vs 실제 체결가
- Fee ratio: 실제 fee 지출 / gross PnL
- MDD tracking: 실시간

### 6.3 Walk-forward 검증
- 백테스트 최적 파라미터가 최근 3개월 데이터에서도 수익인지 확인
- 과적합 detect: IS / OOS 성능 차이 50%+ 면 파라미터 재조정

---

## 7. 구체적 설계 TODO 리스트

### 7.1 Core
- [ ] `BarBuffer` 클래스 (5m, 1h 봉 저장, WebSocket 업데이트, RESTful gap fill)
- [ ] `FVGDetector` (3봉 close 시 감지, 큐 관리, 무효화, 시간청산)
- [ ] `HTFFilter` (1h EMA200 계산, 현재 시점의 방향 반환)
- [ ] `PositionSizer` (risk-based, symbol filter 적용)
- [ ] `OrderManager` (Limit/SL/TP 생성, 취소, replace)
- [ ] `PositionTracker` (현재 포지션, TP1 hit 상태, sz_remain)

### 7.2 Infra
- [ ] SQLite schema + migration
- [ ] Structured logging (JSON, timestamp, trace_id)
- [ ] Prometheus metrics (for Grafana dashboard)
- [ ] Config: YAML/TOML + env override
- [ ] Secrets: API key 는 env var 또는 KMS

### 7.3 Reliability
- [ ] WebSocket reconnect (exponential backoff)
- [ ] Rate limiter (Binance 제한 준수)
- [ ] Retry logic (429/5xx 응답)
- [ ] Idempotency (client_order_id 로 중복 방지)

### 7.4 Testing
- [ ] Unit tests (FVG 감지, sizing, SL 계산)
- [ ] Integration test (Testnet)
- [ ] Replay test (과거 데이터로 live 모드 실행)

---

## 8. 참고

### 8.1 백테스트 코드
- 메인: `new_fvg_retest_5m_v7_partial.py`
- HTF 만: `new_fvg_retest_5m_v6_htf.py`

### 8.2 권장 최종 파라미터 (실전)
MDD ≤ 60% 기준, BTCUSDT 5m:
```
SL_BUFFER_PCT = 0.006
RR1 = 0.8, RR2 = 1.5
BE_AFTER_TP1 = False
MAX_WAIT = 20
RISK_PER_TRADE = 0.015 ~ 0.02   # 실전은 더 보수적
MAX_LEV = 90                     # 실제로는 훨씬 낮게 나옴 (RPT/sl 로 계산)
```

### 8.3 CLAUDE.md 핵심 원칙 재확인
- 미래 데이터 금지
- 수수료 양방향 부과
- 고정 SL 전략은 risk-based 사이징
- 청산 한번이라도 발생 = 전략 실패
- 결과 의심스러우면 코드 재검수

### 8.4 백테스트 vs 실전 gap 예상
- 백테스트 +100,000% 수익 → 실전 대응 수익 **50~70% 할인** 예상
- MDD 는 **오히려 더 커질** 가능성 (슬리피지, 연결 끊김, gap)
- Paper trading 으로 반드시 fill rate 검증 후 deploy

# 프로젝트 환경 설정

## Python 실행 환경
- Python 실행 시 반드시 `venv/bin/python` 사용
- 예: `venv/bin/python backtest_rsi_200.py`

---

# Grid Martingale V3.2 Not Even 전략 (backtest_grid_martingale_3_2_not_even.py)

## 전략 개요

**불균등 간격 그리드 마틴게일** 전략으로, 물량 덜어내기 + 그리드 재설정 기능을 포함.
- 기준가격(grid_center)에서 불균등 간격으로 4단계 지정가 주문
- 한 봉에 여러 레벨이 터치되면 모두 지정가로 체결 (거미줄 방식)
- Level 1만 체결 시: 익절(+0.5%)
- Level 2 이상 체결 시: 본절(+0.1%)에서 Level 1 물량 제외 덜어내기 → 그리드 재설정
- Level 5 가격 터치 시: 손절 (전량)

---

## 파라미터 (현재 설정)

```python
# 자본 및 레버리지
INITIAL_CAPITAL = 1000.0  # USDT
LEVERAGE_LONG = 15
LEVERAGE_SHORT = 5

# 거래 방향
TRADE_DIRECTION = 'LONG'  # 'BOTH', 'LONG', 'SHORT'

# 그리드 설정
GRID_RANGE_PCT = 0.050  # ±5% 범위 (그리드 재설정 기준)
MAX_ENTRY_LEVEL = 4     # 최대 진입 레벨

# 레벨별 진입 거리 (기준가 대비 %, 불균등)
LEVEL_DISTANCES = [0.005, 0.010, 0.04, 0.045]  # 0.5%, 1%, 4%, 4.5%
SL_DISTANCE = 0.05  # 손절: 5%

# 진입 비율 (자본 대비)
ENTRY_RATIOS = [0.05, 0.20, 0.25, 0.50]  # 5%, 20%, 25%, 50%

# 익절/본절 설정
TP_PCT = 0.005   # Level 1: 평단가 +0.5% 익절
BE_PCT = 0.001   # Level 2+: 평단가 +0.1% 본절 (덜어내기)

# 수수료
MAKER_FEE = 0.0       # 지정가 수수료 없음
TAKER_FEE = 0.000275  # 시장가 수수료 0.0275%
```

---

## 핵심 로직 분석

### 1. 레벨별 가격 계산 (`get_level_price`)

```python
def get_level_price(self, level: int, direction: str) -> float:
    if level < MAX_ENTRY_LEVEL:
        distance = LEVEL_DISTANCES[level]  # 불균등 간격
    else:
        distance = SL_DISTANCE  # 손절 거리 (5%)

    if direction == 'LONG':
        return self.grid_center * (1 - distance)
    else:  # SHORT
        return self.grid_center * (1 + distance)
```

**예시 (grid_center = 100,000, LONG):**
| Level | 거리 | 진입가 |
|-------|------|--------|
| 1 | -0.5% | 99,500 |
| 2 | -1.0% | 99,000 |
| 3 | -4.0% | 96,000 |
| 4 | -4.5% | 95,500 |
| SL | -5.0% | 95,000 |

---

### 2. 봉 처리 순서 (`process_bar`)

#### Step 0: 첫 봉 처리
```python
if self.grid_center is None:
    self.setup_grid(close_price)  # close 가격으로 그리드 초기화
    return
```

#### Step 1: 포지션 없음 - 첫 진입 (거미줄 방식)
```python
if self.position is None:
    long_limit = self.get_level_price(0, 'LONG')   # -0.5%
    short_limit = self.get_level_price(0, 'SHORT')  # +0.5%

    if TRADE_DIRECTION in ['BOTH', 'LONG'] and low_price <= long_limit:
        self.position = 'LONG'
        self.start_grid_center = self.grid_center  # 시작 시점 기록
        # 한 봉에서 터치한 모든 레벨 체결
        for level in range(MAX_ENTRY_LEVEL):
            level_price = self.get_level_price(level, 'LONG')
            if low_price <= level_price:
                self.execute_entry(level_price, ENTRY_RATIOS[level], 'LONG')
            else:
                break
```

**중요:** 한 봉에 low가 여러 레벨을 관통해도, 각 레벨의 **지정가**로 체결됨 (시장가 아님)

#### Step 2: 포지션 있음 - 추가 진입
```python
elif self.position is not None and self.current_level < MAX_ENTRY_LEVEL:
    for level in range(self.current_level, MAX_ENTRY_LEVEL):
        level_price = self.get_level_price(level, self.position)
        if low_price <= level_price:  # LONG
            self.execute_entry(level_price, ENTRY_RATIOS[level], 'LONG')
        else:
            break
```

#### Step 3: 손절 체크 (Level 4 체결 후)
```python
if self.position is not None and self.current_level >= MAX_ENTRY_LEVEL:
    sl_price = self.get_level_price(MAX_ENTRY_LEVEL, self.position)  # -5%

    if self.position == 'LONG' and low_price <= sl_price:
        self.close_position(sl_price, 'SL', timestamp, is_market=False)
        self.setup_grid(sl_price)  # 손절가로 새 그리드 설정
        return
```

**중요:** 손절도 **지정가**로 체결 (sl_price), close 가격이 아님

#### Step 4: 익절 체크

**Level 1 (전량 익절):**
```python
if self.current_level == 1:
    tp_price = self.avg_price * (1 + TP_PCT)  # +0.5%
    if high_price >= tp_price:
        self.close_position(tp_price, 'TP', timestamp)
        self.setup_grid(tp_price)
        return
```

**Level 2+ (덜어내기 + 그리드 재설정):**
```python
elif self.current_level >= 2:
    be_price = self.avg_price * (1 + BE_PCT)  # +0.1%
    if high_price >= be_price:
        self.partial_close_and_reset_grid(be_price, timestamp)
        return
```

#### Step 5: 그리드 재설정 (포지션 없을 때)
```python
if self.position is None:
    half_range = GRID_RANGE_PCT / 2  # 2.5%
    upper_bound = self.grid_center * (1 + half_range)
    lower_bound = self.grid_center * (1 - half_range)

    # LONG만 볼 때: 위로 벗어나면 재설정
    if TRADE_DIRECTION == 'LONG' and close_price > upper_bound:
        self.grid_center = close_price

    # SHORT만 볼 때: 아래로 벗어나면 재설정
    elif TRADE_DIRECTION == 'SHORT' and close_price < lower_bound:
        self.grid_center = close_price
```

---

### 3. 진입 실행 (`execute_entry`)

```python
def execute_entry(self, price: float, ratio: float, direction: str, is_market: bool = False):
    leverage = self.get_leverage(direction)  # LONG=15, SHORT=5
    entry_value = self.capital * ratio * leverage

    btc_amount = entry_value / price

    # 수수료 (지정가는 0%)
    if is_market:
        fee = entry_value * TAKER_FEE
    else:
        fee = entry_value * MAKER_FEE  # 0

    self.entries.append((price, btc_amount))
    self.total_size += btc_amount
    self.avg_price = self.calculate_avg_price()
    self.entry_fees += fee

    # Level 1 물량 기록 (덜어내기용)
    if self.current_level == 0:
        self.level1_btc_amount = btc_amount

    self.current_level += 1
```

---

### 4. 덜어내기 + 그리드 재설정 (`partial_close_and_reset_grid`)

Level 2 이상에서 평단가 +0.1% 도달 시:

```python
def partial_close_and_reset_grid(self, exit_price: float, timestamp):
    # 덜어낼 물량 = 전체 - Level 1 물량
    close_amount = self.total_size - self.level1_btc_amount

    # PnL 계산 (덜어낸 물량만)
    if self.position == 'LONG':
        pnl = (exit_price - self.avg_price) * close_amount

    # 본절이므로 수수료 없음
    net_pnl = pnl
    self.capital += net_pnl

    # ========================================
    # 그리드 재설정: Level 1 물량만 남김
    # ========================================

    # 현재 평단가 = 새 Level 1 진입가
    new_level1_price = self.avg_price
    self.entries = [(new_level1_price, self.level1_btc_amount)]
    self.total_size = self.level1_btc_amount
    self.current_level = 1  # Level 1로 리셋

    # 그리드 기준가 역산
    # LONG: level1_price = grid_center * (1 - 0.5%)
    #       → grid_center = level1_price / 0.995
    if self.position == 'LONG':
        self.grid_center = new_level1_price / (1 - LEVEL_DISTANCES[0])
```

---

### 5. 전량 청산 (`close_position`)

```python
def close_position(self, exit_price: float, reason: str, timestamp, is_market: bool = False):
    # PnL 계산 (레버리지는 total_size에 이미 반영됨)
    if self.position == 'LONG':
        pnl = (exit_price - self.avg_price) * self.total_size

    # 수수료
    exit_value = exit_price * self.total_size
    if is_market:
        exit_fee = exit_value * TAKER_FEE
    else:
        exit_fee = exit_value * MAKER_FEE  # 0

    total_fee = self.entry_fees + exit_fee
    net_pnl = pnl - total_fee
    self.capital += net_pnl
```

---

## 시뮬레이션 예시 (LONG)

**설정:** grid_center = 100,000, 자본 = 1,000 USDT, 레버리지 = 15배

### 예시 1: Level 1만 체결 → 익절

```
봉 1: O=100,500, H=100,800, L=99,400, C=99,600
      → low(99,400) <= Level1(99,500) → LONG 진입 @ 99,500
      → low(99,400) > Level2(99,000) → Level 2 미체결

      진입금액: 1,000 × 5% × 15 = 750 USDT
      BTC 수량: 750 / 99,500 = 0.00754 BTC
      평단가: 99,500

봉 2: O=99,700, H=100,100, L=99,600, C=100,000
      → high(100,100) >= TP(99,500 × 1.005 = 99,998) → 익절!

      PnL = (99,998 - 99,500) × 0.00754 = 3.75 USDT
      수수료 = 0 (지정가)
      자본: 1,000 + 3.75 = 1,003.75 USDT
```

### 예시 2: Level 3까지 체결 → 덜어내기

```
봉 1: O=100,500, H=100,600, L=95,800, C=96,200
      → 한 봉에 Level 1~3 체결 (거미줄 방식)

      | Level | 진입가 | 비율 | 진입금액 | BTC |
      |-------|--------|------|---------|-----|
      | 1 | 99,500 | 5% | 750 | 0.00754 |
      | 2 | 99,000 | 20% | 3,000 | 0.03030 |
      | 3 | 96,000 | 25% | 3,750 | 0.03906 |

      총 BTC: 0.07690
      평단가 = (750 + 3,000 + 3,750) / 0.07690 = 97,529

봉 2: O=96,500, H=97,700, L=96,300, C=97,500
      → high(97,700) >= BE(97,529 × 1.001 = 97,627) → 덜어내기!

      덜어낸 물량: 0.07690 - 0.00754 = 0.06936 BTC
      PnL = (97,627 - 97,529) × 0.06936 = 6.80 USDT

      그리드 재설정:
      - 남은 물량: Level 1의 0.00754 BTC
      - 새 Level 1 가격: 97,529 (기존 평단가)
      - 새 grid_center: 97,529 / 0.995 = 98,019

      새 Level 2 가격: 98,019 × 0.99 = 97,039
      새 Level 3 가격: 98,019 × 0.96 = 94,098
```

### 예시 3: Level 4까지 체결 → 손절

```
봉 1: O=100,000, H=100,100, L=95,300, C=95,400
      → 한 봉에 Level 1~4 모두 체결

      | Level | 진입가 | 비율 | 진입금액 | BTC |
      |-------|--------|------|---------|-----|
      | 1 | 99,500 | 5% | 750 | 0.00754 |
      | 2 | 99,000 | 20% | 3,000 | 0.03030 |
      | 3 | 96,000 | 25% | 3,750 | 0.03906 |
      | 4 | 95,500 | 50% | 7,500 | 0.07853 |

      총 BTC: 0.15543
      총 진입금액: 15,000 USDT (15배 레버리지)
      평단가 = 96,520

봉 2: O=95,500, H=95,600, L=94,800, C=94,900
      → low(94,800) <= SL(100,000 × 0.95 = 95,000) → 손절!

      PnL = (95,000 - 96,520) × 0.15543 = -236.15 USDT
      수수료 = 0 (지정가 손절)
      자본: 1,000 - 236.15 = 763.85 USDT
```

---

## 평단가 및 손절 거리 계산

### 4레벨 전부 진입 시 평단가

```
ENTRY_RATIOS = [0.05, 0.20, 0.25, 0.50]  # 5%, 20%, 25%, 50%
LEVEL_DISTANCES = [0.005, 0.010, 0.04, 0.045]

grid_center = 100,000 기준:
Level 1: 99,500 × 5% = 4,975 (가중치)
Level 2: 99,000 × 20% = 19,800
Level 3: 96,000 × 25% = 24,000
Level 4: 95,500 × 50% = 47,750

평단가 = (4,975 + 19,800 + 24,000 + 47,750) / (5+20+25+50)
       = 96,525 / 100
       = 96,525

손절가 = 100,000 × 0.95 = 95,000

평단가 → 손절가 거리 = (96,525 - 95,000) / 96,525 = 1.58%
```

---

## 수수료 정책

| 상황 | 주문 유형 | 수수료 |
|------|----------|--------|
| 첫 진입/추가 진입 | 지정가 | 0% |
| 익절 (TP) | 지정가 | 0% |
| 본절/덜어내기 (BE) | 지정가 | 0% |
| 손절 (SL) | 지정가 | 0% |
| 강제 청산 (END) | 시장가 | 0.0275% |

---

## CSV 출력 컬럼

```
timestamp, direction, start_grid_center, grid_center, entry_price, exit_price,
sl_target_price, size, level, pnl, reason, balance,
level1_price, level2_price, level3_price, level4_price
```

| 컬럼 | 설명 |
|------|------|
| `start_grid_center` | 거래 시작 시점의 grid_center |
| `grid_center` | 청산 시점의 grid_center (덜어내기 후 변경될 수 있음) |
| `entry_price` | 평균 진입가 |
| `exit_price` | 청산가 |
| `sl_target_price` | Level 4 체결 시 손절 예정가 (평단가 × 0.95) |
| `size` | 청산된 BTC 수량 |
| `level` | 진입 레벨 수 (1~4) |
| `reason` | TP, PARTIAL_BE, SL, END |

---

## 주의사항

1. **레버리지는 진입 시 1회만 적용**: `btc_amount = (capital × ratio × leverage) / price`
2. **PnL에 레버리지 중복 없음**: `pnl = (exit - avg) × total_size` (total_size에 이미 레버리지 반영)
3. **거미줄 방식**: 한 봉에 여러 레벨 관통해도 각 레벨 지정가로 체결
4. **손절도 지정가**: close 가격이 아닌 SL 가격(5%)으로 체결
5. **그리드 재설정 조건**:
   - 포지션 없을 때 가격이 grid_center ±2.5% 밖으로 벗어나면
   - LONG만 볼 때: 위로 벗어나면 재설정
   - SHORT만 볼 때: 아래로 벗어나면 재설정


## TODO
### Hyper Scalper V2 전략을 live_trading에 구현하기

**참조 파일**: `backtest_hyper_scalper_v2.py`

---

# Hyper Scalper V2 전략 상세 문서

## 전략 개요

**EMA 정배열/역배열 + ADX + Retest** 기반의 추세추종 전략.
- 15분봉 BTC/USDT
- LONG & SHORT 양방향
- 동적 레버리지 (손절 거리 기반)
- 동적 익절 (ATR 기반)

---

## 파라미터 설정

```python
# 자본 및 리스크
INITIAL_CAPITAL = 1000.0
MAX_LEVERAGE = 90
RISK_PER_TRADE = 0.07  # 거래당 7% 리스크 (레버리지 계산에 사용)

# 거래 방향
TRADE_DIRECTION = 'BOTH'  # 'BOTH', 'LONG', 'SHORT'

# EMA 설정
EMA_FAST = 25
EMA_MID = 100
EMA_SLOW = 200

# ADX 설정
ADX_LENGTH = 14
ADX_THRESHOLD = 30.0  # 강한 추세 기준

# Retest 설정
RETEST_LOOKBACK = 5  # 최근 5봉 내 dip/rally 확인

# 손절 설정
SL_LOOKBACK = 29     # 최근 29봉 최저/최고가 기준
MAX_SL_DISTANCE = 0.03  # 손절 거리 최대 3% 캡

# ATR 설정 (익절용)
ATR_LENGTH = 14
TP_ATR_MULT_LONG = 4.2   # 롱 익절 = 진입가 + ATR × 4.2
TP_ATR_MULT_SHORT = 3.2  # 숏 익절 = 진입가 - ATR × 3.2

# 수수료
MAKER_FEE = 0.0       # 지정가 (익절)
TAKER_FEE = 0.000275  # 시장가 (진입, 손절) = 0.0275%
```

---

## 지표 계산

### 1. EMA (Exponential Moving Average)
```python
# TradingView 호환 EMA
ema = close.ewm(span=length, adjust=False).mean()
```

### 2. ATR (Average True Range) - RMA 기반
```python
def calculate_atr(high, low, close, length):
    prev_close = close.shift(1)
    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
    atr = calculate_rma(tr, length)  # Wilder's MA
    return atr
```

### 3. ADX (Average Directional Index)
```python
def calculate_adx(high, low, close, length):
    # +DM, -DM 계산
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
    minus_dm = down_move if (down_move > up_move and down_move > 0) else 0

    # DI 계산
    atr = calculate_rma(tr, length)
    plus_di = 100 * calculate_rma(plus_dm, length) / atr
    minus_di = 100 * calculate_rma(minus_dm, length) / atr

    # ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = calculate_rma(dx, length)
    return adx
```

---

## 진입 조건

### LONG 진입 (4가지 조건 모두 충족)

```python
# 1. 상승 추세 (EMA 정배열)
bull_trend = (close > EMA200) and (EMA25 > EMA100) and (EMA100 > EMA200)

# 2. 강한 추세
strong_trend = ADX >= 30

# 3. 최근 5봉 내 저가가 EMA25 아래였던 적 있음 (dip 확인)
had_low_below_fast = min(low - EMA25, window=5) < 0

# 4. 현재 종가가 EMA25 위 (reclaim)
reclaim_long = close > EMA25

# 최종 LONG 시그널
long_signal = bull_trend and strong_trend and had_low_below_fast and reclaim_long
```

### SHORT 진입 (4가지 조건 모두 충족)

```python
# 1. 하락 추세 (EMA 역배열)
bear_trend = (close < EMA200) and (EMA25 < EMA100) and (EMA100 < EMA200)

# 2. 강한 추세
strong_trend = ADX >= 30

# 3. 최근 5봉 내 고가가 EMA25 위였던 적 있음 (rally 확인)
had_high_above_fast = max(high - EMA25, window=5) > 0

# 4. 현재 종가가 EMA25 아래 (reclaim)
reclaim_short = close < EMA25

# 최종 SHORT 시그널
short_signal = bear_trend and strong_trend and had_high_above_fast and reclaim_short
```

---

## 진입 실행 (execute_entry)

### 1. 진입가
```python
entry_price = 신호봉의 close 가격
```

### 2. 손절가 (SL) 설정
```python
# 최근 29봉 기준
if LONG:
    stop_loss = min(low, window=SL_LOOKBACK)  # 최저가
else:  # SHORT
    stop_loss = max(high, window=SL_LOOKBACK)  # 최고가

# 손절 거리 3% 캡 적용
sl_distance = abs(entry_price - stop_loss) / entry_price
if sl_distance > MAX_SL_DISTANCE:  # 0.03 = 3%
    if LONG:
        stop_loss = entry_price * (1 - MAX_SL_DISTANCE)
    else:
        stop_loss = entry_price * (1 + MAX_SL_DISTANCE)
```

### 3. 레버리지 계산 (핵심!)
```python
def calculate_leverage(entry_price, stop_loss):
    sl_distance_pct = abs(entry_price - stop_loss) / entry_price

    # 진입 수수료 + 손절 수수료 포함
    effective_sl = sl_distance_pct + TAKER_FEE * 2  # 0.055% 추가

    leverage = RISK_PER_TRADE / effective_sl  # 0.07 / effective_sl
    leverage = min(leverage, MAX_LEVERAGE)    # 최대 90배
    leverage = max(leverage, 1)               # 최소 1배

    return round(leverage, 2)
```

**예시**:
- 손절 거리 2% → effective_sl = 2.055% → leverage = 7% / 2.055% = 3.4배
- 손절 거리 1% → effective_sl = 1.055% → leverage = 7% / 1.055% = 6.6배

### 4. 익절가 (TP) 설정 - 수수료 보전 포함!
```python
# 진입 수수료를 익절에서 보전하기 위한 offset
fee_offset = entry_price * TAKER_FEE * 2  # 약 0.055%

if LONG:
    take_profit = entry_price + ATR * TP_ATR_MULT_LONG + fee_offset
else:
    take_profit = entry_price - ATR * TP_ATR_MULT_SHORT - fee_offset
```

**왜 fee_offset을 추가하는가?**
- 진입 시 TAKER 수수료 발생 (0.0275%)
- 익절은 MAKER (수수료 0%)이지만, 진입 수수료를 회수해야 함
- fee_offset × 2로 설정하여 보수적으로 보전

### 5. 포지션 크기
```python
position_value = capital * leverage
entry_size = position_value / entry_price  # BTC 수량
```

---

## 청산 조건 (check_exit)

**우선순위**: 청산(LIQ) > 손절(SL) > 익절(TP)

```python
def check_exit(idx):
    # 청산가 계산 (레버리지 기반)
    liq_distance = 1.0 / leverage  # 예: 10배 → 10%

    if LONG:
        liq_price = entry_price * (1 - liq_distance)

        # 1. 청산 체크 (최우선)
        if low <= liq_price:
            return liq_price, 'LIQ'
        # 2. 손절
        if low <= stop_loss:
            return stop_loss, 'SL'
        # 3. 익절
        if high >= take_profit:
            return take_profit, 'TP'

    else:  # SHORT
        liq_price = entry_price * (1 + liq_distance)

        if high >= liq_price:
            return liq_price, 'LIQ'
        if high >= stop_loss:
            return stop_loss, 'SL'
        if low <= take_profit:
            return take_profit, 'TP'
```

**중요**: 진입봉에서는 청산 체크 안함 (`if idx <= entry_idx: continue`)

---

## 청산 실행 (execute_exit)

```python
def execute_exit(exit_price, reason):
    # PnL 계산
    if LONG:
        pnl = (exit_price - entry_price) * entry_size
    else:
        pnl = (entry_price - exit_price) * entry_size

    # 수수료 계산
    entry_fee = entry_price * entry_size * TAKER_FEE  # 항상 TAKER

    if reason in ['SL', 'LIQ']:
        exit_fee = exit_price * entry_size * TAKER_FEE  # 시장가
    else:  # TP, END
        exit_fee = exit_price * entry_size * MAKER_FEE  # 지정가 = 0

    total_fee = entry_fee + exit_fee
    net_pnl = pnl - total_fee

    capital += net_pnl
```

---

## 수수료 정리

| 상황 | 진입 | 청산 | 총 수수료 |
|------|------|------|-----------|
| 익절 (TP) | TAKER (0.0275%) | MAKER (0%) | 0.0275% |
| 손절 (SL) | TAKER (0.0275%) | TAKER (0.0275%) | 0.055% |
| 청산 (LIQ) | TAKER (0.0275%) | TAKER (0.0275%) | 0.055% |
| 종료 (END) | TAKER (0.0275%) | MAKER (0%) | 0.0275% |

---

## Live Trading 구현 시 주의사항

### 1. 진입 주문
- **시장가 주문** (TAKER)
- 신호 발생 시 즉시 진입
- 진입 후 TP/SL 주문 동시 설정

### 2. 익절 주문 (TP)
- **지정가 주문** (MAKER)
- 가격 = `entry_price + ATR × TP_ATR_MULT + fee_offset`
- **fee_offset 필수**: `entry_price × TAKER_FEE × 2`

### 3. 손절 주문 (SL)
- **스탑 마켓 또는 지정가**
- 가격 = `최근 29봉 최저/최고가` (최대 3% 캡 적용)

### 4. 레버리지 설정 ( 혹은 레버리지를 이용한 size 즉 수량 설정)
- 거래소 API로 동적 레버리지 설정
- `leverage = RISK_PER_TRADE / (sl_distance + 0.00055)`
- 최대 90배, 최소 1배

### 5. 지표 계산
- EMA 25/100/200, ADX 14, ATR 14
- **RMA 사용** (TradingView 호환)
- 최소 200봉 이상 히스토리 필요
- 처음 프로그램을 켰을때 모든 지표들이 미리 계산이 되어있어야 함으로 300봉 전까지의 15분봉 데이터를 모두 받은후
전부 계산을 한다. 하지만 api 로 이전 데이터를 다운받을시 데이터의 맨마지막데이터는 현재 15분봉의데이터이고 그 봉은 아직 마감이 되기전이다.
즉 live 로 다음 15분봉 데이터가 들어올때 historical 데이터로 받은 df 맨 마지막의 데이터 (가장 최근 데이터) 를 삭제후 live 로 처음 받은 15분봉
데이터를 이용해서 df 맨마지막 데이터와 지표값들과 replace 한다.
이후부터는 df 맨 마지막으로 추가하면서 가장 오래된 데이터 하나를 삭제하면서 데이터들을 뒤로 민다. ( 마치 큐처럼 ) 그래서 총 300사이즈의 df 를 유지하고
지표들 계산들도 유지한다.

### 6. 신호 체크 타이밍
- 봉 마감 시점에 신호 체크
- 15분봉 마감 = xx:00, xx:15, xx:30, xx:45

### 7. 포지션 관리
- 한 번에 1개 포지션만
- 포지션 있으면 신규 진입 불가
- TP/SL 둘 중 하나 체결 시 나머지 취소

---

## 전략 흐름 요약

```
1. 봉 마감 시 지표 업데이트 (EMA, ADX, ATR)

2. 포지션 없음?
   → LONG 신호? (정배열 + ADX≥30 + dip + reclaim) → LONG 진입
   → SHORT 신호? (역배열 + ADX≥30 + rally + reclaim) → SHORT 진입

3. 포지션 있음?
   → 청산가 터치? → 강제 청산 (LIQ)
   → 손절가 터치? → 손절 (SL)
   → 익절가 터치? → 익절 (TP)

4. 진입 시:
   - SL = 최근 29봉 최저/최고 (최대 3%)
   - 레버리지 = 7% / (SL거리 + 수수료)
   - TP = 진입가 ± ATR × 배수 + fee_offset
   - 포지션 크기 = 자본 × 레버리지 / 진입가

5. 청산 시:
   - TP: 진입수수료만 차감 (MAKER 0%)
   - SL/LIQ: 진입+청산 수수료 차감
```

---

## 백테스트 결과 (2020.11 ~ 2025.12)

```
파라미터: SL_LOOKBACK=29, MAX_SL_DISTANCE=3%, RISK_PER_TRADE=7%
수익률: ~20,000%+
MDD: ~75-80%
승률: ~55%
거래수: ~1,300건
```

---

## 구현 체크리스트

- [ ] EMA 25/100/200 계산 (adjust=False)
- [ ] ADX 계산 (RMA 기반)
- [ ] ATR 계산 (RMA 기반)
- [ ] LONG 신호 로직
- [ ] SHORT 신호 로직
- [ ] 동적 레버리지 계산 (수수료 포함)
- [ ] 동적 TP 계산 (fee_offset 포함)
- [ ] 동적 SL 계산 (최대 3% 캡)
- [ ] 청산 체크 (LIQ > SL > TP 우선순위)
- [ ] 수수료 처리 (진입 TAKER, TP MAKER, SL TAKER)
- [ ] 포지션 상태 관리
- [ ] 주문 관리 (TP/SL OCO)
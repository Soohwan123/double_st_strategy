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

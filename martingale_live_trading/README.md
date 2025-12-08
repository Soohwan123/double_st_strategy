# Grid Martingale Live Trading

BTCUSDC / ETHUSDC 그리드 마틴게일 실시간 자동매매 시스템

---

## 전략 개요

**불균등 간격 그리드 마틴게일** 전략으로, 물량 덜어내기 + 그리드 재설정 기능을 포함.

- 기준가격(grid_center)에서 불균등 간격으로 4단계 지정가 주문
- Level 1만 체결 시: 익절(+0.5%)
- Level 2 이상 체결 시: 본절(+0.1%)에서 Level 1 물량 제외 덜어내기 → 그리드 재설정
- Level 4 체결 후 손절가 터치 시: 손절 (전량)

---

## 디렉토리 구조

```
martingale_live_trading/
├── trade_btc.py          # BTC 트레이딩 메인 (실행 파일)
├── trade_eth.py          # ETH 트레이딩 메인 (실행 파일)
├── grid_strategy.py      # 핵심 전략 로직 (공통)
├── binance_library.py    # 바이낸스 API 래퍼
├── state_manager.py      # 상태 관리 (포지션, 주문)
├── config.py             # 설정 로더
├── config_btc.txt        # BTC 동적 설정 파일
├── config_eth.txt        # ETH 동적 설정 파일
├── .env                  # API 키 (gitignore)
├── scripts/
│   ├── start_btc.sh      # BTC 시작
│   ├── start_eth.sh      # ETH 시작
│   ├── start_all.sh      # 전체 시작
│   ├── stop_btc.sh       # BTC 중지
│   ├── stop_eth.sh       # ETH 중지
│   ├── stop_all.sh       # 전체 중지
│   ├── status.sh         # 상태 확인
│   └── logs.sh           # 실시간 로그
├── state/
│   ├── state_btc.json    # BTC 상태 스냅샷
│   └── state_eth.json    # ETH 상태 스냅샷
├── logs/
│   ├── grid_martingale_btc_YYYY-MM-DD.log
│   └── grid_martingale_eth_YYYY-MM-DD.log
└── trades/
    ├── trades_btc.csv    # BTC 거래 기록
    └── trades_eth.csv    # ETH 거래 기록
```

---

## 실행 방법

```bash
cd martingale_live_trading/scripts

# 시작
./start_btc.sh          # BTC만
./start_eth.sh          # ETH만
./start_all.sh          # 둘 다

# 상태 확인
./status.sh

# 로그 확인
./logs.sh btc           # BTC만
./logs.sh eth           # ETH만
./logs.sh               # 둘 다

# 중지
./stop_btc.sh
./stop_eth.sh
./stop_all.sh
```

또는 직접 실행:
```bash
python trade_btc.py
python trade_eth.py
```

---

## 파라미터 설정

### BTC (config_btc.txt)
```
INITIAL_CAPITAL=1000.0
LEVERAGE_LONG=20
LEVERAGE_SHORT=5
TRADE_DIRECTION=LONG
GRID_RANGE_PCT=0.040      # ±2% 범위
MAX_ENTRY_LEVEL=4
ENTRY_RATIOS=0.05,0.20,0.25,0.50
LEVEL_DISTANCES=0.005,0.010,0.040,0.045
SL_DISTANCE=0.05
TP_PCT=0.005
BE_PCT=0.001
```

### ETH (config_eth.txt)
```
GRID_RANGE_PCT=0.020      # ±1% 범위 (ETH만 다름)
# 나머지 동일
```

**동적 설정**: 프로그램 실행 중에도 config 파일을 수정하면 60초마다 자동 반영

---

## 전체 로직 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                     프로그램 시작                                │
├─────────────────────────────────────────────────────────────────┤
│ 1. 자본 설정: 바이낸스 잔고의 33% (BTC/ETH/여유분 3분할)         │
│ 2. 상태 복구 (state_btc.json / state_eth.json)                  │
│ 3. 첫 1분봉 완성 → grid_center 설정 → 거미줄 주문 4개            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    거미줄 주문 (LONG 기준)                       │
├─────────────────────────────────────────────────────────────────┤
│ Level 1: grid_center × 0.995 (−0.5%), 5% 자본                   │
│ Level 2: grid_center × 0.990 (−1.0%), 20% 자본                  │
│ Level 3: grid_center × 0.960 (−4.0%), 25% 자본                  │
│ Level 4: grid_center × 0.955 (−4.5%), 50% 자본                  │
│ SL:      grid_center × 0.950 (−5.0%)                            │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Level 1 체결   │ │  Level 2+ 체결   │ │   Level 4 체결   │
├──────────────────┤ ├──────────────────┤ ├──────────────────┤
│ → TP 주문 설정   │ │ → BE 주문 설정   │ │ → BE + SL 설정   │
│   (+0.5% 전량)   │ │ (+0.1% 덜어냄)   │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│    TP 체결       │ │    BE 체결       │ │    SL 체결       │
├──────────────────┤ ├──────────────────┤ ├──────────────────┤
│ → 전량 청산      │ │ → Level1만 남김  │ │ → 전량 손절      │
│ → 그리드 재설정  │ │ → TP 주문 설정   │ │ → 그리드 재설정  │
│ → 새 거미줄 4개  │ │ → 거미줄 3개     │ │ → 새 거미줄 4개  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

---

## 핵심 로직 상세

### 1. 진입 (거미줄 방식)

```python
# grid_center = 100,000 (LONG 기준)
Level 1: 99,500 (-0.5%)  →  5% × 20배 = 100% 자본
Level 2: 99,000 (-1.0%)  → 20% × 20배 = 400% 자본
Level 3: 96,000 (-4.0%)  → 25% × 20배 = 500% 자본
Level 4: 95,500 (-4.5%)  → 50% × 20배 = 1000% 자본
```

### 2. 청산 주문

| 상황 | 청산 타입 | 가격 | 수량 |
|------|----------|------|------|
| Level 1만 체결 | TP | 평단가 +0.5% | 전량 |
| Level 2+ 체결 | BE | 평단가 +0.1% | Level 1 제외 |
| Level 4 체결 | BE + SL | BE: +0.1%, SL: -5% | BE: 덜어내기, SL: 전량 |

### 3. BE 체결 후 처리

1. Level 1 물량만 남김
2. 바이낸스 실제 포지션 동기화
3. `level1_btc_amount` 업데이트
4. 새 grid_center 역산: `평단가 / 0.995`
5. Level 2~4 진입 주문 재설정
6. TP 주문 설정 (+0.5%)

### 4. 그리드 범위 이탈

- 포지션 없을 때만 체크
- LONG: 가격이 grid_center +2% 초과 시 재설정
- SHORT: 가격이 grid_center -2% 미만 시 재설정

---

## 주요 컴포넌트

### trade_btc.py / trade_eth.py

메인 실행 파일. 3개의 비동기 태스크 실행:

1. **websocket_handler**: 실시간 가격 수신 및 체결 감지
2. **position_sync_task**: 30초마다 바이낸스 포지션 동기화
3. **config_reload_task**: 60초마다 설정 파일 변경 감지

### grid_strategy.py

핵심 전략 클래스 `GridMartingaleStrategy`:

| 메서드 | 설명 |
|--------|------|
| `setup_grid_orders()` | 거미줄 주문 설정 |
| `on_entry_filled()` | 진입 체결 처리 |
| `on_tp_filled()` | TP 체결 처리 |
| `on_be_filled()` | BE 체결 처리 (덜어내기) |
| `on_sl_filled()` | SL 체결 처리 |
| `_set_tp_order()` | TP 주문 설정 (바이낸스 포지션 조회 후) |
| `_set_be_order()` | BE 주문 설정 (Level 1 제외 덜어내기) |
| `reset_grid_after_partial_close()` | BE 후 그리드 재설정 |
| `reset_grid_after_full_close()` | TP/SL 후 그리드 재설정 |

### binance_library.py

바이낸스 API 래퍼 `BinanceFuturesClient`:

| 메서드 | 설명 |
|--------|------|
| `place_limit_entry()` | 지정가 진입 주문 |
| `place_limit_entry_with_retry()` | 증거금 부족 시 0.1%씩 줄이며 재시도 |
| `place_limit_close()` | 지정가 청산 주문 (ReduceOnly 실패 시 0.1%씩 재시도) |
| `get_position_info_with_retry()` | 포지션 조회 (실패 시 재시도) |
| `set_stop_loss()` | 손절 주문 설정 |

### state_manager.py

상태 관리:

- `PositionState`: 포지션 정보 (방향, 평단가, 수량, 레벨)
- `OrderState`: 주문 정보 (진입, TP, BE, SL)
- `StateManager`: JSON 파일로 상태 저장/복구

---

## 증거금 부족 처리

### 진입 주문 (Level 4)
```
증거금 부족 발생 → 0.1%씩 줄이며 재시도 → 최소 30%까지
```

### 청산 주문 (TP/BE)
```
1. 바이낸스 실제 포지션 조회 (실패 시 최대 10회 재시도)
2. 조회된 수량으로 주문
3. ReduceOnly 거부 시 0.1%씩 줄이며 재시도 → 최소 50%까지
```

---

## 상태 복구

프로그램 재시작 시 `state/state_btc.json` 또는 `state/state_eth.json`에서 복구:

- grid_center
- capital (운용 자본)
- position (포지션 정보)
- orders (대기 주문)

바이낸스 실제 상태와 동기화하여 불일치 해결.

---

## 로그 예시

### 정상 진입 → BE 체결 → TP 설정
```
2025-12-08 06:24:22 - INFO - 첫 진입: LONG
2025-12-08 06:24:22 - INFO - 포지션 동기화: 평단가 $90950.56 → $90995.70, 수량 0.002343 → 0.004000
2025-12-08 06:24:22 - INFO - Level 1 체결: $90950.56, 평단가: $90995.70, 총 수량: 0.004000
2025-12-08 06:24:22 - INFO - TP 주문 준비: 바이낸스 포지션 0.004000, 평단가 $90995.70
2025-12-08 06:24:22 - INFO - TP 주문 설정: $91450.68, 수량: 0.004000

2025-12-08 06:42:19 - INFO - Level 2 체결: $90493.52, 평단가: $90625.59, 총 수량: 0.021000
2025-12-08 06:42:19 - INFO - BE 주문 준비: 바이낸스 포지션 0.021000, Level1 0.004000, 덜어내기 0.017000
2025-12-08 06:42:19 - INFO - BE 주문 설정: $90716.21, 덜어내기 수량: 0.017000 (Level1 0.004000 유지)

2025-12-08 07:15:33 - INFO - BE 체결: $90716.21, 예상 PnL: $1.54
2025-12-08 07:15:33 - INFO - BE 후 기존 주문 전부 취소 완료
2025-12-08 07:15:33 - INFO - 포지션 동기화: 평단가 $90625.59 → $90625.59, 수량 0.004000 → 0.004000
2025-12-08 07:15:33 - INFO - Level 1 물량 업데이트: 0.004000
2025-12-08 07:15:33 - INFO - 바이낸스 대기 주문 수: 0개
2025-12-08 07:15:33 - INFO - BE 후 포지션 상태: Level 1, 평단가 $90625.59, 수량 0.004000
2025-12-08 07:15:33 - INFO - BE 후 그리드 재설정: new_center=$91080.99
2025-12-08 07:15:33 - INFO - Level 2 주문 재설정: $90170.18
2025-12-08 07:15:33 - INFO - Level 3 주문 재설정: $87437.75
2025-12-08 07:15:33 - INFO - Level 4 주문 재설정: $86982.34
2025-12-08 07:15:33 - INFO - TP 주문 준비: 바이낸스 포지션 0.004000, 평단가 $90625.59
2025-12-08 07:15:33 - INFO - TP 주문 설정: $91078.72, 수량: 0.004000
```

---

## 2025-12-08 수정 사항

### 1. BE 주문 물량 수정
- **이전**: `quantity = total_size` (전체 물량)
- **수정**: `quantity = total_size - level1_btc_amount` (Level 1 제외)

### 2. TP/BE 주문 전 포지션 조회
- 바이낸스 실제 포지션 조회 후 수량 결정
- 조회 실패 시 최대 10회 재시도

### 3. ReduceOnly 실패 시 재시도
- 0.1%씩 수량 줄이며 재시도
- 최소 50%까지 시도

### 4. 진입 주문 재시도 비율 변경
- **이전**: 1%씩 감소
- **수정**: 0.1%씩 감소

### 5. 가용자산 비율 변경
- **이전**: 50% (BTC/ETH 반반)
- **수정**: 33% (BTC/ETH/여유분 3분할)

### 6. BE 후 level1_btc_amount 업데이트
- `reset_grid_after_partial_close()`에서 바이낸스 동기화 후 `level1_btc_amount` 업데이트

### 7. BE 후 상태 로깅 강화
- 주문 취소 완료
- 포지션 동기화
- 대기 주문 수 확인
- 현재 포지션 상태

---

## 주의사항

1. **API 키**: `.env` 파일에 API 키 설정 필수
2. **증거금**: 레버리지 20배 사용으로 증거금 부족 발생 가능 → 재시도 로직으로 처리
3. **동시 실행**: BTC와 ETH는 별도 프로세스로 실행 (자본 33%씩 사용)
4. **상태 파일**: 프로그램 강제 종료 시에도 state 파일로 복구 가능
5. **손절**: Level 4 체결 후에만 SL 주문 설정됨

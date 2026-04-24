# FVG Strategy DRY_RUN Test Log

## DRY_RUN 시작 시각

**시작 시각 (UTC)**: `2026-04-22 06:46:34 UTC`
**시작 시각 (KST)**: `2026-04-22 15:46:34 KST` (UTC+9)

(이전 04:25 시작 세션은 `_try_entry` 개선 반영 위해 재시작됨. state/trades/* 초기화 후 새로 시작.)

## 시작 시점 상태 (시뮬레이션 결과)

라이브 시작 시 과거 500개 15m + 500개 1h봉으로 큐 + 가상 포지션 시뮬레이션을 돌리고, 그 결과를 이어받아 시작합니다.

### BTC (fvg_btc)
- 가상 포지션: **LONG @ $77,970.0**
- TP: $78,811.2 / SL: $77,322.9 / LIQ: $53,802.1
- long_queue: 0개, short_queue: 0개
- HTF: bull=True, bear=False

### ETH (fvg_eth)
- 가상 포지션: **없음**
- long_queue: 4개, short_queue: 0개
- HTF: bull=True, bear=True (HTF 미사용)

### XRP (fvg_xrp)
- 가상 포지션: **LONG @ $1.4546**
- TP: $1.4749 / SL: $1.4401 / LIQ: $0.8160
- long_queue: 0개, short_queue: 1개
- HTF: bull=True, bear=False

### SOL (fvg_sol) — 2026-04-23 02:04:00 UTC (11:04:00 KST) 에 추가 시작
- bt_18 **v6_1** 파라미터: RR=1.7, SL_BUF=0.004, RISK=2.5%, WAIT=7, USE_HTF=true
- (v6_2로 먼저 시작했다가 yearly_breakdown 재확인 결과 v6_1이 전 구간 앞서서 교체. 완전 초기화 후 재시작)
- 가상 포지션: **없음**
- long_queue: 0개, short_queue: 1개
- HTF: bull=True, bear=False
- 백테스트 비교 시:
  - `bt_18_SOL_15m_mdd40_v6_1.py`로 비교
  - START는 SOL 시작 시각 기준 14일 전 = `2026-04-09`
  - trades_oos_SOLUSDT_15m.csv 중 exit_time ≥ `2026-04-23 02:04:00`

공통: 초기 자본 $1,800

---

## 백테스트 비교 방법

### ⚠️ 중요: 백테스트 START 시점

DRY는 시작 시점에 **이미 500개 과거 봉으로 시뮬레이션된 큐 + 가상 포지션**을 갖고 있음.
백테스트를 DRY 시작 시각인 `2026-04-22 06:46:34` 부터 돌리면 **빈 큐로 시작해서 상태 불일치** → 비교 불가.

**올바른 방법**: 백테스트 START를 충분히 과거로 (최소 14일 전).

```python
# _common.py 수정
START = '2026-04-08'   # DRY 시작 - 14일 (500개 15m봉 + 200개 1h봉 충분히 커버)
END   = '2026-XX-XX'   # 비교 종료 시점
```

이러면 백테스트는 2026-04-08부터 봉 단위로 큐 관리하면서 진행 → 2026-04-22 06:46:34 시점의 백테스트 큐 상태가 우리 DRY 시뮬레이션 결과와 동일.

### 비교 절차

1. **백테스트 풀 실행** (START='2026-04-08' 등 충분히 과거)
   - bt_04_BTC_15m_mdd60.py (BTC)
   - bt_10_ETH_15m_mdd60.py (ETH)
   - bt_15_XRP_15m_mdd60.py (XRP)

2. **각 trades_*.csv에서 DRY 첫 LIVE 봉 이후 거래만 추출 (entry_time 기준)**

   `_common.py:134-135` 기준, entry_time/exit_time은 **bar open 시각**(15m 봉의 timestamp).
   DRY는 시작 시각까지의 "마지막 닫힌 봉"까지 시뮬하고, 그 다음 봉부터 실거래. 그래서 **첫 LIVE 봉의 open 시각** 이상만 필터:

   | 심볼 | DRY 시작 (UTC) | 마지막 시뮬 봉 | 첫 LIVE 봉 = entry_time 필터 값 |
   |---|---|---|---|
   | BTC/ETH/XRP | 2026-04-22 06:46:34 | 06:30 (close 06:45) | **`2026-04-22 06:45:00`** |
   | SOL | 2026-04-23 02:04:00 | 01:45 (close 02:00) | **`2026-04-23 02:00:00`** |

   ```python
   import pandas as pd
   # 예: BTC
   df = pd.read_csv('trades_bt_04_BTCUSDT_15m_mdd60.csv')
   df['entry_time'] = pd.to_datetime(df['entry_time'])
   df_compare = df[df['entry_time'] >= '2026-04-22 06:45:00']
   # 예: SOL
   df = pd.read_csv('trades_bt_18_SOL_15m_mdd40_v6_1.csv')
   df['entry_time'] = pd.to_datetime(df['entry_time'])
   df_compare = df[df['entry_time'] >= '2026-04-23 02:00:00']
   ```

3. **가상 포지션 검증**
   - 백테스트 trades.csv에서 entry_time이 DRY 시작 직전인 거래(open) 찾기
   - 그 거래의 direction/entry_price가 DRY 시뮬레이션이 만든 가상 포지션과 일치해야 함
   - 그 거래의 exit_time = DRY에서 가상 청산이 일어나야 할 시점
   - DRY logs에서 "[가상 청산]" 메시지가 그 시점에 발생하는지 확인
   - BTC: LONG @ $77,970.0 / XRP: LONG @ $1.4546 / ETH: 없음

4. **DRY trades CSV와 비교**
   - DRY: `trades/trades_fvg_btc.csv` 등 (mode=DRY)
   - 백테스트: `trades_oos_BTCUSDT_15m.csv` 중 DRY 시작 이후
   - entry_time, direction, entry_price, exit_price, pnl 비교

### 매칭 기준
- ✅ 진입 시각 일치 (15m 봉 마감 시점 ± 다음 봉)
- ✅ 진입 가격 동일 (지정가)
- ✅ 청산 시각, 청산 가격 동일
- ⚠️ PnL은 동일해야 하나 미세 차이 가능 (DRY는 size를 nominal 0.001로 잡고 capital 변경 안 함; LIVE 전환 시에야 진짜 capital 사용)

---

## 비교 시 주의사항

- **가상 포지션 처리**: DRY는 가상 포지션 살아있는 동안 새 진입 안 함. 백테스트도 동일 시뮬레이션 결과면 같은 시점에 그 포지션을 갖고 있음.
- **시간 정확도**: DRY는 라이브 tick 기반, 백테스트는 봉 OHLC 기반 → 같은 봉 안에서 SL/TP 도달 순서가 약간 다를 수 있음 (예외적 케이스).
- **수수료**: 둘 다 MAKER 0.0002 / TAKER 0.0005 동일.
- **HTF 필터**: BTC/XRP는 직전 닫힌 1h close vs EMA200, ETH는 미사용.
- **DRY 모드 fill 감지**: DRY는 봉의 high/low로 판단, LIVE는 tick 기반 — 비교 차이 거의 없음 (15m 봉 기준).
- **pending 재배치**: 같은 FVG가 유효한 동안 15m마다 같은 가격으로 재배치하던 비효율을 제거함. 이제 FVG 후보가 바뀔 때만 cancel + place. 백테스트는 체결 판정만 하므로 이 변경과 무관.

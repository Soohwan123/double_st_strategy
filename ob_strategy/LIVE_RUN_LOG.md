# OB Strategy LIVE 운영 로그

라이브 실행 시점 / 중지·재시작 히스토리 / 백테스트 비교 계획.

---

## 🆕 OB SOL 5m bt_09 v5 MDD≤50 — 2026-04-27 시작

**LIVE 시작 시각**: **2026-04-27 13:45:49 UTC** (PID 4042757)
**비교 기준 시각 (BT cutoff)**: **`2026-04-27 13:45:00 UTC`** (LIVE 첫 신규 5m 봉 open)
**자본**: $200.00 (clean start, state/logs/trades 전부 초기화)
**계정**: hyper_v2_sub_account 와 동일 부계정 (.env 동일). 3 strategy (hyper_v2 / eth_hyper / ob_sol) 공유.

### 자본 분배 (hyper_v2 부계정 wallet 공유)

| Strategy | state.capital | 비고 |
|---|---|---|
| hyper_v2 (BTC) | $2,318.22 | 2026-04-27 ob 추가 시 -$300 (원래 $2,618.22) |
| eth_hyper (ETH) | $4,142 | 변화 없음 |
| **ob_sol (SOL)** | **$200.00** | 신규 |
| 합계 | **$6,660** | wallet 의 ~$100 buffer (margin 경합 방지) |

### 백테스트 매핑

| 항목 | 값 |
|---|---|
| 백테스트 파일 | `backtest/ob_winners/ob_winners/bt_09_SOL_5m_swap_v5_mdd50.py` |
| 모듈 | `_common_swap.py` (entry-before-invalidation + 1m intrabar resolve, HTF on) |
| 모드 | swap (LIMIT 진입) |
| 버전 | OB v5 with HTF |
| TF | 5m |
| 6년 백테스트 (2020-09-14 ~ 2026-04-23) | **+42,233,393% / MDD 42.5% / Trades 1,296 / WR 85.8% / yearly 6/6 양수** |
| Yearly 분포 | 20-21 +140% / 21-22 +6,700% / 22-23 +520% / 23-24 +961% / 24-25 +840% / **25-26 +531%** |

### 파라미터 (config_ob_sol.txt)

```
TF                = 5m
STRATEGY_MODE     = BT_LONG_FIRST   # LONG 우선 (40/60 hysteresis 없음)
IMPULSE_LOOKBACK  = 17              # 임펄스 봉 17개 lookback
IMPULSE_MIN_PCT   = 0.025           # 17봉 동안 2.5% 이상 가격 변화 → OB 형성
SL_BUFFER_PCT     = 0.0025          # SL 거리 (OB bot 아래 0.25%)
RR                = 0.35            # TP = entry + 0.35 × sl_dist (TP 가까움 → WR 높음)
MAX_WAIT          = 550             # OB 큐 timeout (550 × 5m = 1.9일)
RISK_PER_TRADE    = 0.12            # 12% (avg lev 12, max 26.82)
MAX_LEVERAGE      = 90              # Binance 상한 (BT 와 동일, 부계정 lev 90 가능)
USE_HTF           = true            # 1h EMA200 필터
HTF_EMA_LEN       = 200
MAX_OB_QUEUE      = 16
TAKER_FEE         = 0.0005
MAKER_FEE         = 0.0002
```

### LIVE ↔ BT 매칭 검증 (4중 audit 완료)

#### ✅ 매칭 항목

- **TF**: 5m (price_feed `kline_5m` 폴링)
- **HTF**: 1h EMA200 (`kline_1h` 구독, 직전 닫힌 1h close vs EMA200)
- **봉 처리 순서**: EXIT → OB DETECT → INVALIDATION → ENTRY candidate (LIVE timing 이 BT 의 swap order 와 자연 매칭)
- **OB 감지**: `c[i] - c[i-IL]` impulse 패턴, lookback 윈도우 lowest low/highest high 봉의 OHLC = OB top/bot. BT `_common_swap.py` 와 100% 동일.
- **Entry 우선순위**: STRATEGY_MODE=BT_LONG_FIRST → LONG 우선 (BT entry block 순서 매칭)
- **Sizing**: `lev = clamp(RPT / (sl_pct + 2×taker_fee), 1, 90)` 동일
- **SL/TP/LIQ**: BT `_calculate_entry` 와 동일 공식
- **수수료**: 진입 MAKER 0.0002 / TP MAKER / SL,LIQ TAKER 0.0005
- **진입봉 SL/TP**: BT 의 1m intrabar resolve = LIVE 의 거래소 자동 처리 (limit fill 후 SL/TP 즉시 placement → tick 매칭) 자연 매칭
- **Invalidation**: c[i]<bot (LONG) → 큐 제거, max_wait 초과 timeout
- **Entry 후 큐 clear**: `_on_entry_filled` (LIVE) / `_on_entry_filled_dry` (DRY) 모두 direction 별 큐 clear
- **Exit-bar 처리**: `_exit_this_bar=True` → 다음 봉 처리에서 OB detect/invalidation/entry skip (BT continue 매칭)

#### ⚠️ 알려진 미세 차이 (look-ahead 아님, 운영 영향 작음)

##### 차이점 1: 진입가 Clamp (BT 가 약간 비현실적)

**BT 코드**: `ep_i = min(max(ep_i, l[i]), h[i])` — top 이 봉 OHLC 범위 밖일 때 강제 clamp.

**문제 케이스**: top > h[i]
```
OB top = 100
봉 i: O=98, H=99, L=92, C=95
BT: entry 조건 l[92] <= top[100] true → entry 발동, ep = h[i] = 99 (clamp)
LIVE: limit @ 100 BUY → 봉 high=99 < 100 → 가격이 limit 안 닿음 → fill 안 됨
```

→ BT 는 spurious fill 가정 (실거래에서 일어나지 않을 거래). LIVE 가 더 정확.
발생 빈도: 약 2% (FVG bt_31 trades 5,086 중 105건 = 2.1%). 영향 미미.

##### 차이점 2: SL/TP placement timing

**BT**: 진입 즉시 SL/TP 가상 배치 (1m resolve walk).
**LIVE**: limit fill 감지 → SL/TP 거래소 placement (1초 간격 60회 retry, 최대 1분).
- 일반 시장: 1-2초 안에 placement 완료 → 영향 미미.
- 거래소 이상 시 emergency close 발동 (LIVE 안전장치).

##### 차이점 3: 거래소 LIMIT carry-over

**BT**: 매 봉 entry 로직 새로 실행. NO_ENTRY 면 폐기, 다음 봉 다시 시도.

**LIVE**: 봉 N close 에 limit placed → 봉 N+1 fill 시도 → 안 되면 봉 N+1 close 의 candidate 와 비교 → 같은 OB 면 유지, 다른 OB 면 cancel/replace.

**결과**: 같은 OB 면 LIVE 의 limit carry = BT 의 같은 entry 시도 반복. 매칭 ✓.
- entry_time 만 약간 다름 (BT: 봉 시작 ts, LIVE: 거래소 fill 시각). entry_price 동일.

### 1주일 비교 계획

`+7일 (2026-05-04 13:45 UTC) 도달 + 재시작 없음` 시:
- BT 재실행 (`_common_swap.py START='2026-04-13'` warmup ~2주 + END=비교시점)
- LIVE `trades_ob_sol.csv` vs BT `trades_bt_09_SOL_5m_swap_v5_mdd50.csv` 의 8가지 trade-by-trade 일치 확인:
  - entry_time, direction, entry_price, exit_price, SL, TP, reason, pnl
- capital 차이 ($200 vs $1000) 로 절대 PnL 다르지만 **% 수익률 일치해야** 매치 인정

### 운영 모니터링 포인트

```bash
# 실시간 로그
tail -f /home/double_st_strategy/ob_strategy/logs/ob_sol_$(date -u +%Y-%m-%d).log

# 거래 CSV
tail -f /home/double_st_strategy/ob_strategy/trades/trades_ob_sol.csv

# State
cat /home/double_st_strategy/ob_strategy/state/state_ob_sol.json

# 프로세스 (PID 4042757)
ps -p 4042757 && echo "RUNNING"

# Telegram 알림 (자동): WS 끊김 / 재연결 / 모니터 프로세스 죽음
```

### 알려진 운영 리스크

1. **Margin 경합**: 3 strategy (hyper_v2 / eth_hyper / ob_sol) 가 hyper_v2 부계정 wallet 공유. 동시에 lev 풀 진입 시 margin 부족 가능. 각자 isolated 가정 시 wallet × 0.9 / lev 한도. wallet $6,760 × 0.9 = $6,084 free margin → 일반 운영 OK, 극단 동시 lev 발동 시 거래소 reject 가능.

2. **avg lev 12, max lev 26.82** — BT 결과. 부계정 lev 90 가능하므로 BT 그대로 적용. SL hit 시 cap 손실 = sl_dist × lev / ep × cap = ~10% cap (lev 12 가정).

3. **WR 85.8%, RR=0.35** — TP 가까워서 hit 자주, SL 한 방으로 큰 손실 (5번 win 으로 만회). Tail risk 있음. fwd-test 시 WR 떨어지면 손실 가능.

4. **max_wait=550 (1.9일)** — OB 매우 오래 살아남음. 1.9일 후 retest 도 진입 가능 → stale 가격 진입 가능성.

5. **HTF 필터 사이드 효과**: 1h EMA200 위면 LONG only, 아래면 SHORT only. 횡보장에서 (close ≈ EMA) bull/bear 자주 뒤집히면 진입 시그널 누락 가능.

### 실행 히스토리

| # | 시각 (UTC / KST) | 유형 | 사유 / 변경 내용 | 결과 |
|---|---|---|---|---|
| 1 | 2026-04-27 13:45:49 / 22:45:49 | **🆕 OB SOL 5m bt_09 신규 LIVE 시작** | hyper_v2_sub_account 와 동일 부계정에서 OB Retest 전략 신규 시작. **변경 사항**: (1) `ob_strategy/` 디렉토리 신규 생성 (fvg_strategy mirror). (2) `data_handler.py` 의 detect_ob — BT `_common_swap.py` 와 100% 동일 spec (impulse + lookback lowest low/highest high). (3) `ob_strategy.py` (FvgStrategy 계승, OB detection + STRATEGY_MODE=BT_LONG_FIRST). (4) hyper_v2 state.capital -$300 ($2,618 → $2,318). (5) ob_sol state $200 초기화. (6) crontab 정리 (FVG ETH/XRP 라인 제거, OB 추가). | LIVE 모드 정상 기동. PID 4042757. 5m 봉 500개 + 1h 봉 500개 historical load. simulate → 가상 포지션 없음 (clean). HTF 필터 bull=True, bear=False (현재 close $87.69 > EMA $86.13). 비교 cutoff = 2026-04-27 13:45:00 UTC |

---

## 운영 체크리스트 (재시작 시)

1. 중지 전 상태 확인:
   - `ps aux \| grep trade_ob_sol`
   - `cat state/state_ob_sol.json`
2. 정지: `./scripts/stop_ob_sol.sh`
3. 코드 / config 수정
4. 시작: `./scripts/start_ob_sol.sh`
5. 로그 확인:
   - `복구된 대기주문 정상` / `포지션 복구` / 에러 없는지
   - HTF 필터 정상 로드
   - simulate 결과 (가상 포지션 takeover 또는 clean)
6. **이 파일 (LIVE_RUN_LOG.md) 에 기록**:
   - 📌 "현재 안정 운영 시작 시각" 갱신
   - 실행 히스토리 표에 한 줄 추가
7. 백테스트 비교용 entry_time cutoff 업데이트 (5m 단위로 올림)

## 전략개발 및 백테스트법

## Language
- **항상 한국어로 대답할 것.** Compact 이후에도 한국어 유지. 코드/로그는 영어 그대로 OK.

## Python
- Always use `venv/bin/python` to run Python scripts (not `python` or `python3`)
- 장시간 돌아가는 옵티마이저는 `run_in_background: true` 로 실행. 절대 foreground 로 돌리지 말 것.
- Numba `@njit(cache=True)` + multiprocessing Pool + pre-computed indicator 캐싱이 기본 패턴.

## JIT 컴파일 필수 (절대 규칙)
- **대용량 데이터 (>100k rows) 를 다루는 루프/지표 계산 함수는 무조건 `@njit(cache=True)` 적용.**
- 순수 Python 루프로 인덱서 돌리는 건 금지 (1m 6년치 = 3.2M rows, Python 루프 = 분~시간 단위로 느려짐).
- 해당되는 것: RSI, ADX, ATR, EMA, Bollinger (rolling mean/std), Keltner, Z-score, SuperTrend, Heikin-Ashi, rolling_min/max, 모든 backtest simulation 루프 (`sim()`).
- Rolling window 연산은 **running sum / running sum-of-squares** 기법으로 O(n) 구현 (naive O(n*window) 금지).
  - 예: rolling mean + std 는 `s += c[i] - c[i-period]; s2 += c[i]² - c[i-period]²` 패턴.
- Numba 제약 체크: dict/list comprehension 안에서 Numba 함수 호출 불가, numpy 일부 함수 미지원, Python object 사용 불가.
- Warmup: 메인 루프 전에 작은 샘플로 JIT 컴파일 먼저 유도 (`sim(c[:200], ...)`).
- 의심스러우면 `time.time()` 으로 wrap 해서 10초 넘으면 JIT 으로 바꿀 것.

---

## 백테스트 작성 시 절대 원칙 (지금까지 배운 것들)

### 0. 현실성 (Realism) - 실전에서 불가능한 코드 금지
- 백테스트 = 실전 시뮬레이션. **실전에서 할 수 없는 짓은 코드에도 넣지 말 것.**
- 미래 데이터 사용 금지 (아래 1번 참조).
- "정확히 저점에서 진입 / 정확히 고점에서 청산" 같은 비현실적 체결 금지. 신호는 close 확정 후, 체결가는 해당 가격 또는 다음 bar 시가.
- Intrabar 에서 여러 조건 동시 만족 시 **보수적 쪽 (불리한 쪽)** 으로 체결. 예: 같은 bar 에 SL + TP 둘 다 touch → SL 체결로 가정.
- **진입봉에서 SL/TP/LIQ 체결 가능성도 반드시 고려**. 실전은 진입 직후 SL/TP 주문이 거래소에 올라가 intrabar 로 체결됨. "진입봉은 청산 없음" 같이 가정하면 live 와 괴리 발생 (FVG 전략이 처음에 이 버그 있었음 - `i > entry_idx` 가드로 진입봉 exit 를 스킵해서, live 가 같은봉에 SL 맞고 끝내는데 백테스트는 다음 봉까지 살리는 divergence). 진입봉 exit 체크 순서: 같은 봉 내 entry_price 결정 → 같은 봉 OHLC 로 SL/TP/LIQ touch 판정 (보수적 우선순위). 체결 가정은 entry 이후 bar 의 high/low 에 해당 주문 가격 포함 여부로.
- 지정가가 bar 의 high/low 범위 밖이면 체결 불가.
- 호가/주문 수량 제약, 유동성 한계 무시는 OK (백테스트 단순화).
- **무시해도 되는 것 (단순화 허용)**: 슬리피지, 펀딩비, 부분체결, 주문 거절, 거래소 점검. 이건 현실과 괴리 있지만 모델링 비용 대비 가치 낮아서 제외.
- **무시하면 안 되는 것**: 미래 데이터, 수수료, 청산, 레버리지 한계, 체결 가능성, bar 내 순서, **진입봉 exit 체크**.

### 1. 미래 데이터 절대 금지 (Look-Ahead Bias)
- 모든 지표는 bar `i` 기준으로 `[0..i]` 까지의 데이터만 사용. `i+1` 이후 값 참조 금지.
- 신호 판정 / 진입가는 **bar close 기준**. 같은 bar 의 high/low 로 진입/청산 결정하지 말 것.
- 진입은 **다음 bar 시가(또는 close)** 로 체결하는게 안전. 같은 bar close 로 체결할거면 close 확정 후라는 점 명시.
- HTF (Higher Timeframe) 필터 사용 시 **마지막 "닫힌" HTF bar** 만 사용. 진행 중인 bar 사용 금지.
  - 예: 1m 에서 1H EMA200 필터 → 현재 시각이 속한 1H bar 가 아니라, 직전에 close 된 1H bar 의 EMA.
- `rolling().mean()` / `ewm()` 등 pandas 함수는 기본적으로 과거만 보지만, `.shift()` 여부 꼼꼼히 확인.
- 지표 계산 후 반드시 `np.isnan(indicator[i])` 체크 (warmup 구간 건너뛰기).
- State flag (`was_below`, `touched_overbought`, `cycle_open` 등) 는 **bar 처리 끝난 후** 업데이트. 진입 판정 전에 미리 업데이트하면 같은 bar 에서 진입 불가.

### 2. 수수료 정확히 계산
- **Binance Futures 기준**: Taker 0.05% (0.0005), Maker 0.02% (0.0002).
- 수수료는 **notional 기준** 부과 (margin 아님). `fee = notional × fee_rate`.
- **양방향 부과**: 진입 + 청산 모두. 1:1 RR 전략은 수수료 때문에 거의 무조건 마이너스.
- Scale-in 전략은 진입마다 수수료 누적 → 트레이드당 진입 수수료 합산 필수.
- Partial TP: 각 부분 청산마다 수수료 별도 계산.
- Limit order (TP 지정가) 는 Maker, Market order (SL/LIQ/강제청산/시간청산) 는 Taker.
- 레버리지가 높을수록 notional 커져서 수수료 비중 폭증. 1m 스캘핑은 수수료가 순이익 초과하는 경우 다반사.
- 최종 리포트에 `total_entry_fee`, `total_exit_fee`, `fee/gross_pnl 비율` 로그로 남길 것.

### 3-0. 사이징 규칙 (고정 SL 전략)
- **고정 손절 가격을 특정할 수 있는 전략 (BB edge, OB edge, FVG edge, prev swing, ATR*N 등)** 은 **항상 다음 두 파라미터를 함께 넣을 것**:
  - `RISK_PER_TRADE`: 트레이드당 감수할 cap 대비 손실 비율 (예: 0.01~0.08 = 1%~8%)
  - `MAX_LEV = 90.0`: 최대 레버리지 cap
- 공식:
  ```python
  sl_pct = abs(ep - sl_price) / ep          # SL 까지 거리 (%)
  eff_sl = sl_pct + taker_fee * 2.0         # 수수료 protection
  lev = risk_per_trade / eff_sl             # 필요 레버리지
  lev = min(lev, MAX_LEV)
  lev = max(lev, 1.0)
  notional = cap * lev
  sz = notional / ep
  ```
- 이유: SL hit 시 손실이 정확히 `cap * risk_per_trade` 가 되도록 → 리스크 관리 일관성.
- 레버리지는 결과값 (derived), 파라미터 아님. Grid 에서 LEVERAGE 대신 RISK_PER_TRADE 사용.
- `MAX_LEV=90` 은 Binance 기준 상한. 더 낮추고 싶으면 전략별로 오버라이드.
- SL 이 없거나 동적인 전략 (time exit only, trailing) 은 이 규칙 미적용, 단순 `cap * leverage` 사이징.

### 3. 레버리지 & 청산 처리
- **청산 = 전략 실패.** 한 번이라도 LIQ 발생하면 `liquidated=1` 플래그 필수, 결과 필터링 시 `liquidated==0` 으로 배제.
- 청산 시: `cap = 0`, `mdd = 1.0 (100%)`, break. 절대 음수 cap 허용 금지.
- **LONG 청산가**: `avg_entry × (1 - 1/leverage)` (Isolated 기준, 단순화).
- **SHORT 청산가**: `avg_entry × (1 + 1/leverage)`.
- Scale-in 중에는 `avg_entry = entry_notional_total / position_size` 로 재계산 후 청산가 갱신.
- 청산 체크는 **bar 의 low (LONG) / high (SHORT)** 기준. close 기준으로 하면 intrabar 청산 놓침.
- **Unrealized equity wipe 체크** 도 병행: `cap + position_size × price - entry_notional_total <= 0` 이면 청산 처리.
- 리스크 기반 레버리지: `lev = RISK / (SL_distance + 2 × TAKER_FEE)`, `MAX_LEVERAGE_CAP` (예: 90) 으로 캡.
- 우선순위: **LIQ > SL > TP > 시간청산**. 같은 bar 에서 여러 조건 해당 시 보수적 순서로 처리.

### 4. Position / Cycle 관리
- Scale-in 후 청산 시 모든 상태 초기화: `position_size, entry_notional_total, margin_total, tier, touched_overbought, was_below, entries_in_cycle` 전부.
- `cycle_open` 플래그로 **중복 진입 방지**: 한 cycle 에서 진입 후, RSI 가 oversold 를 벗어났다 다시 들어와야 재진입 가능.
- 청산/TP 직후 **같은 bar 에서 재진입 금지**: exit 블록 마지막에 `continue` 넣을 것 (Numba `sim()` 함수 포함).
- **진입봉 exit 체크 필수**: `if position != 0 and i > entry_idx` 같은 가드로 진입봉 exit 를 **스킵하면 안 됨**. 진입 시점 이후의 같은 봉 OHLC 로 SL/TP/LIQ touch 판정. 실전에선 진입 후 SL/TP 주문이 거래소에 즉시 올라가므로 intrabar 로 체결 가능. 백테스트가 `i > entry_idx` 로 진입봉을 안전 지역으로 가정하면 live 와 체계적 divergence 발생 (FVG 진입 = support/resistance 바로 밑, 진입봉에서 곧바로 SL 꽂히는 경우 흔함).
- 백테스트 종료 시 열린 포지션은 마지막 bar close 로 강제청산 (net PnL 에 반영).

### 5. 결과 해석 주의사항
- **WR (Win Rate) 높다고 수익 아님.** 70% WR 인데 -% 수익 많음. `avg_win / avg_loss` 비율이 핵심.
- `total_fees / net_pnl` 체크. 이 값이 1 넘으면 수수료가 이익보다 큰 과최적화 전략.
- **XRP 같은 2020-2024 초대형 상승 종목은 LONG 전략이 과대평가**됨. Buy&Hold 와 비교 필수.
- Top 결과는 `total_trades >= 20 (또는 50)` AND `liquidated == 0` 필터 적용 후 봐야 의미 있음.
- MDD 가 너무 낮으면 트레이드 수가 너무 적거나 전체 기간 중 일부만 돌았을 가능성.
- 파라미터 과적합 의심되면 In-Sample / Out-of-Sample 분리 또는 walk-forward 검증.

### 6. 데이터 관련
- 1m CSV 는 `historical_data/{SYMBOL}_1m_futures.csv`, 5m 은 `{SYMBOL}_5m_futures.csv`.
- 기간: 2020-01-06 ~ 2026-03-02 (BTC 기준). 다른 심볼은 상장일에 따라 다를 수 있음.
- `parse_dates=['timestamp']` 로 읽고 `reset_index(drop=True)` 필수.
- OHLCV 를 `np.float64` 로 변환해서 Numba 에 전달.

### 7. 결과 나오면 코드 재검수 (필수)
- **백테스트 결과가 나오면 좋든 나쁘든 반드시 코드를 다시 한번 훑어볼 것.**
- 수익 너무 좋으면 (예: +10,000%) → 미래 데이터 / 체결 버그 / 수수료 누락 / 청산 누락 의심.
- 수익 너무 나쁘면 → 진입 조건 / 지표 계산 / state flag 업데이트 순서 버그 의심.
- 체크리스트:
  - [ ] 지표 계산 시 `i+1` 이후 인덱스 참조 없는가?
  - [ ] 진입/청산 가격이 해당 bar 의 OHLC 범위 안에 있는가?
  - [ ] 수수료가 진입 + 청산 양쪽 모두 차감됐는가? scale-in / partial TP 도 개별 적용됐는가?
  - [ ] 청산 조건에서 `cap=0`, `mdd=1.0`, `liquidated=1`, break 다 됐는가?
  - [ ] `cycle_open`, `was_below`, `touched_overbought` 등 state 초기화 누락 없는가?
  - [ ] 같은 bar 재진입 방지 `continue` 있는가?
  - [ ] **진입봉 exit 체크가 포함돼 있는가?** (`i > entry_idx` 로 스킵하면 live 와 divergence — 진입 후 같은봉에서 SL/TP/LIQ touch 되는지 반드시 체크)
  - [ ] HTF 필터가 "닫힌" bar 만 참조하는가?
- 의심스러운 결과는 detail 백테스트 스크립트 (trade-by-trade 로그) 로 검증.
- "결과 이상 없어 보임" 이라고 보고하기 전에 위 체크리스트 한 번 더 돌리기.

### 8. 최적화 워크플로우
- Grid 는 **의미있는 범위** 로 좁힐 것. 100만 combo 넘어가면 과적합 위험 + 시간 낭비.
- Numba JIT warmup 한 번 돌리고 시작 (첫 combo 가 컴파일 비용 때문에 느림).
- Progress 는 10,000 step (큰 grid) 또는 1,000 step (작은 grid) 마다 top 3 출력.
- 결과 CSV 는 `new_results_{strategy}_{SYMBOL}.csv` 형식으로 저장.
- 최종 리포트: Top 30 전체 + Top 30 (min trades, no liq 필터) 두 가지.

---

## 9. 전략 winner 찾는 표준 프로세스 (FVG_winners 방식)

**이 섹션은 FVG Retest 전략에서 winner 조합을 발굴한 전체 과정을 정리. 다른 전략에도 동일 방식 적용.**

### 9.1 전체 파이프라인 개요
```
1. 전략 아이디어 설계 (entry/exit 명확히 정의)
   ↓
2. v1 기본 구현 (최소 기능, grid 넓게)
   ↓
3. 첫 실행 결과 분석 (양수 조합 존재? WR? MDD? 거래수?)
   ↓
4. 문제점 파악 → 점진적 개선 (v2, v3, ...)
   - 사이징 방식 (레버리지 → RPT)
   - 필터 추가 (HTF, Body, Volume 등)
   - Partial TP, Trailing SL 등 exit 개선
   ↓
5. 각 버전마다 top 결과 파라미터 분포 → 다음 grid 세분화
   (saturate 감지, boundary 확장)
   ↓
6. 양수 & MDD 개선되면 → 여러 심볼 × TF 로 robustness 검증
   ↓
7. 결과 취합 (버전 × 심볼 × TF 교차)
   - (symbol, TF) 별 MDD 버킷 (≤60/50/40) Top 10 추출
   ↓
8. Winner 후보 개별 백테스트 파일 생성 (trade-by-trade CSV)
   ↓
9. OOS 검증 (START 기간 변경, 최근 2년 구간 재실행)
   ↓
10. 실전 매매 spec 문서 작성 (LIVE_TRADING_SPEC.md)
    ↓
11. 단일 폴더에 묶고 tar.gz 배포용 압축
```

### 9.2 단계별 상세 방법론

#### [1단계] 전략 아이디어 설계
- 진입 조건을 **명확한 수학적 정의**로 (예: FVG = `low[i] > high[i-2]` 3봉 패턴)
- 청산 조건 명시 (SL, TP, 시간청산, 무효화 조건 전부)
- 수수료 구조 명시 (entry Maker/Taker, TP Maker/Taker, SL Taker, LIQ Taker)
- 사이징 방식 결정 (고정 SL → risk-based, 동적 SL → `cap*lev`)
- 실전 가능성 체크 (§ 0 현실성 원칙)

#### [2단계] v1 기본 구현
- 단일 심볼 단일 TF 부터 시작 (예: BTCUSDT 5m)
- 파라미터 grid **적당히 넓게** (1,000~10,000 combo 목표)
- Numba JIT 컴파일 필수 (§ "JIT 컴파일 필수")
- Multiprocessing Pool 로 병렬 실행
- Indicator 는 pre-compute 해서 캐싱 (파라미터 영향 없는 것)

#### [3단계] 첫 실행 결과 분석
체크리스트:
- [ ] 양수 수익 조합 수 / 전체 비율
- [ ] Top 30 의 MDD 분포 (50% 이하 / 80% 이상)
- [ ] 평균 WR, avg_win/avg_loss 비율
- [ ] LIQ 발생 조합 수
- [ ] 수수료/net PnL 비율
- [ ] Long WR vs Short WR 편향
- [ ] 파라미터가 grid 경계에서 saturate 되는가? (확장 필요 신호)

**전부 음수면 전략 구조적 문제 가능성**. 필터 추가 또는 로직 재설계.

#### [4단계] 점진적 개선 (FVG 예시)
| 버전 | 개선점 | Top Return | MDD |
|---|---|---|---|
| v1 (원본) | LEVERAGE grid (고정 lev) | -42% | 78% |
| v2 | **LEVERAGE → RISK_PER_TRADE** (§ 3-0 사이징) | -25% | 75% |
| v3 | Grid 세분화 (v2 상위 분포 기반) | 소폭 개선 | |
| v4 | Grid 더 세분화 | | |
| v5 | MIN_FVG_PCT 최적화 | +15% | 60% |
| **v6 (HTF)** | **1h EMA200 방향 필터 추가** | **+1,035K%** | **78%** |
| v6_1 | HTF 상위 조합 세분화 | +1,337K% | 85% |
| v6_2 | 더 세분화 (BUF 0.0005 step) | +2,658K% | 92% |
| **v7 (Partial TP)** | **50% @ RR1 + 50% @ RR2** | **+4,725K%** | 87% |

**원칙**:
- 한 번에 하나의 변화만 추가 (어느 개선이 효과 있는지 추적 위해)
- 각 버전의 top 결과 **파라미터 분포 분석** → 다음 grid 좁게 재설정
- Saturate 감지 (grid 경계 값이 top 에 몰림) → 범위 확장
- MDD 과도하게 커지면 개선 중단 (과적합 signals)

#### [5단계] 파라미터 세분화 루틴
각 버전 실행 후:
```python
# 상위 300개 조합의 파라미터 분포 확인
top = df.nlargest(300, 'return_pct')
for col in PARAM_COLS:
    print(top[col].value_counts().sort_index())
```
- 특정 값에 몰리면 → 그 값 주변으로 세분화 (예: BUF=0.006 peak → [0.0055, 0.006, 0.0065])
- 최대/최소 값에서 saturate → 경계 확장 (예: RPT=0.03 max 에 몰림 → 0.035, 0.04 추가)
- 거의 모든 조합 고르게 분포 → 해당 파라미터 그대로 유지 or 삭제 고려
- 단계적 grid 축소 규칙: 총 combo 수 1만 이하 유지 (빠른 iteration)

#### [6단계] 다심볼 × 다TF Robustness 검증
- **각 버전 × 각 심볼 × 각 TF** 병렬 실행 (예: 8 버전 × 3 심볼 × 2 TF = 48 runs)
- 실행 스크립트:
  ```bash
  for ver in v2 v3 v4 v5 v6_htf v6_1 v6_2 v7_partial; do
    for sym in BTCUSDT ETHUSDT XRPUSDT; do
      for tf in 5m 15m; do
        SYMBOL=$sym TF=$tf venv/bin/python -u new_{strategy}_${ver}.py > logs/${ver}_${sym}_${tf}.log
      done
    done
  done
  ```
- 결과 CSV 는 `new_results_{strategy}_{TF}_{SYMBOL}_{ver}.csv` 로 저장

#### [7단계] 결과 취합 (aggregate 스크립트)
각 `(symbol, TF)` 마다:
- 모든 버전 CSV 로드 + `version` 컬럼 태깅 + concat
- `liqs == 0` 필터, `total_trades >= 20` 필터
- **MDD 버킷 (≤60/50/40)** 별로 sort → Top 10 추출
- 총 `N심볼 × N_TF × 3 버킷 = 최종 리스트 수`
- 요약 파일 (`{strategy}_all_summary.txt`) 로 저장

예시: `aggregate_fvg_all.py` 참고.

#### [8단계] Winner 개별 파일 생성
폴더 `{strategy}_winners/` 만들고:
- `_common.py` — 공통 백테스트 로직 (trade-by-trade 로깅 지원)
  - `run_backtest(symbol, tf, version, ...params)` 함수
  - `save_trades()` 로 `backtest_hyper_scalper_v2_ema20.py` 동일 포맷 CSV 출력
  - CSV 컬럼: `entry_time, exit_time, direction, entry_price, exit_price, take_profit, stop_loss, leverage, size, reason, pnl, balance`
- `bt_{NN}_{SYMBOL}_{TF}_mdd{XX}.py` — 16개 (또는 buckets×symbols×tfs) 개별 스크립트
  - 각각 파라미터 하드코딩 + `save_trades()` 호출
- `README.md` — Top 1 결과 테이블 + 파라미터 / 사용법
- `{STRATEGY}_LIVE_TRADING_SPEC.md` — 실전 구현 spec

#### [9단계] OOS (Out-of-Sample) 검증
- `_common.py` 의 `START` 를 최적화 기간 끝 구간으로 변경 (예: `2024-01-06`)
- 16개 파일 전부 재실행
- Expected vs Actual 수익률 비교:
  - 전체 기간: +100,000% → OOS 2년 +100~1,000% 정도면 정상
  - OOS 에서도 **청산 0, 양수 수익 유지** 확인 → robustness 있음
  - OOS 에서 마이너스로 돌아서면 → 과적합 의심
- 비교 테이블 `README.md` 에 추가 (2 기간 병렬)

#### [10단계] 실전 매매 Spec 작성
`{STRATEGY}_LIVE_TRADING_SPEC.md` 에 다음 항목 포함:
1. **전략 요약** — entry/exit/sizing 수학적 정의
2. **권장 실전 파라미터** (OOS 결과 기반 보수적 세팅)
3. **시스템 아키텍처** — WS/Strategy/OrderMgr/Risk Guard 컴포넌트 구분
4. **실수하기 쉬운 지점** (최소 10개):
   - 봉 완성 타이밍 (WebSocket `x` flag)
   - HTF 닫힘 감지 (직전 hour 참조)
   - Limit 체결 gap / 주문 placement 지연
   - 단일 주문 관리 정책
   - SL/TP 동시 배치 (reduceOnly)
   - Partial TP 후 사이즈 재계산
   - LIQ 대응 (isolated + forced SL)
   - 수수료 (Maker/Taker 차이, Post-Only)
   - Tick/lot size rounding
   - 시간 동기화 (NTP)
5. **Risk Guard** — 일일 손실 제한, 연속 손실 제한, 잔고 하한
6. **단계별 Rollout** — Paper → 1x live → 목표 leverage
7. **백테스트 vs 실전 gap 경고** — 50~70% 할인 예상

#### [11단계] 배포 준비
- `tar --exclude='*.csv' --exclude='__pycache__' -czvf {strategy}_winners.tar.gz *`
- 소스 + spec md 만 포함, 대용량 CSV 제외

### 9.3 다른 전략에 적용할 때
동일 파이프라인 사용:
1. 전략 아이디어 명확히 정의
2. `new_{strategy}.py` → v1 부터 시작
3. 같은 pattern 으로 v2/v3/.. 개선 (하나씩만)
4. 결과 CSV → `aggregate_{strategy}_all.py` 로 버킷별 Top 10
5. `{strategy}_winners/` 폴더 구성 (`_common.py` + 16 개별 bt)
6. OOS + spec md + tar.gz

### 9.4 공용 유틸리티 파일
- **`_common.py`** 템플릿 (fvg_winners/_common.py 참고): trade logger 포함
- **`compare_maker_vs_taker.py`** — 진입 수수료 비교 (실전 gap 측정)
- **`aggregate_{strategy}_all.py`** — MDD 버킷별 Top 10 자동 추출

### 9.5 최종 Deliverables 체크리스트
- [ ] `new_{strategy}_v1.py` ~ `new_{strategy}_v7.py` (점진 개선 버전)
- [ ] `new_results_{strategy}_*.csv` (각 버전 × 심볼 × TF)
- [ ] `aggregate_{strategy}_all.py` (취합 스크립트)
- [ ] `{strategy}_all_summary.txt` (18개 Top 10 리스트)
- [ ] `{strategy}_winners/` 폴더:
  - [ ] `_common.py` (공통 로직)
  - [ ] `bt_{NN}_*.py` (개별 파일)
  - [ ] `trades_bt_{NN}_*.csv` (trade-by-trade)
  - [ ] `README.md` (전체/OOS 비교 테이블)
  - [ ] `{STRATEGY}_LIVE_TRADING_SPEC.md`
- [ ] `{strategy}_winners.tar.gz` (CSV 제외 압축)

---

# 프로젝트 환경 설정

## Python 실행 환경
- Python 실행 시 반드시 `venv/bin/python` 사용
- 예: `venv/bin/python backtest_rsi_200.py`

---

# 새 전략 개발 시 필수 규칙

## 1. 기존 라이브러리/함수 적극 활용 (재구현 금지)
- `binance_library.py`: 주문/포지션/잔고 관련 모든 메서드 (open_market_position, place_limit_entry, place_limit_close, set_stop_loss, cancel_all_orders, cancel_order, get_position_info, get_order_status, get_actual_trade_pnl 등)
- `state_manager.py`: 상태 영속화 (atomic write, JSON)
- `data_handler.py` 패턴: 캔들 관리, 지표 증분 계산
- `DailyRotatingLogger`: 일별 로그 회전
- 트레이딩 엔트리 패턴: `websocket_handler` + `position_sync_task` (30초) + `config_reload_task` (60초) + `status_log_task` (5분)
- **새 함수 만들기 전에 기존 코드 검색 필수**

## 2. 미래 데이터 사용 절대 금지
- 백테스트와 라이브 모두 **현재 봉 마감 시점까지의 데이터**만 사용
- HTF 필터: 직전 닫힌 1h봉 기준 (현재 진행 중인 1h봉 NO)
- 진입가 결정 시 다음 봉 가격 NO
- 백테스트 코드를 줄 단위로 검증해야 함

## 3. 현실 불가능 시나리오 검토 (슬리피지/펀딩비는 OK)
- 같은 봉에서 진입과 청산 동시 발생 가능 여부 확인
- 봉 OHLC를 알기 전 진입/청산 결정하는지 확인
- 지정가 주문이 실제 호가창에서 체결 가능한 가격인지 확인
- 마진/포지션 모드 충돌 (one-way vs hedge)
- 같은 계정에 여러 전략 운용 시 마진 경합

## 4. 백테스트 ↔ 라이브 1:1 매칭 검증 필수
- 파라미터 정확히 일치 (config 파일 vs 백테스트 상수)
- 지표 계산식 동일 (EMA span, RMA seed, etc.)
- 진입 조건 조합 동일
- 수수료 처리 동일 (MAKER/TAKER 어떤 단계에 적용)
- SL/TP 우선순위 동일 (LIQ > SL > TP)
- 출시 전 sub-agent로 line-by-line 감사 권장

## 5. 포지션 보호 절대 보장
- 진입 후 SL/TP 설정 1초 간격 60회 (1분) 재시도
- 1분 안에 실패 시 시장가 긴급 청산 (`_emergency_close`)
- 매 시도 전 포지션 존재 확인 (사라졌으면 OK 처리)
- 대기주문 취소 실패 시 새 주문 안 검 (이중주문 방지)
- 재시작 시 거래소와 강제 sync + pending 주문 검증

## 6. 자기 심볼만 처리 (다중 전략 격리)
- 모든 binance API 호출은 `symbol=self.symbol` 명시
- `cancel_all_orders`, `get_position_info`, `close_position_market` 모두 자기 심볼만
- 다른 전략의 포지션/주문 절대 건드리지 말 것

## 7. 새 전략 추가 체크리스트
- [ ] CLAUDE.md `## 계정 구분` 표 + `## 파라미터 비교` 섹션에 추가
- [ ] 새 전략 디렉토리 생성 + .env (API 키 분리 시)
- [ ] config.py에 symbol_type 등록 + price/qty precision 정확히
- [ ] config_*.txt 작성 (DRY_RUN=true 기본)
- [ ] 기존 binance_library/state_manager 복사 또는 import
- [ ] data_handler/strategy 작성 — 백테스트와 1:1 검증
- [ ] trade_*.py + scripts/ (start, stop, monitor, clean_logs)
- [ ] git 자동 복사 훅 디렉토리 목록에 추가 (settings.local.json)
- [ ] DRY_RUN으로 며칠 테스트 → 백테스트 거래 비교 검증
- [ ] DRY_RUN=false 전환
- [ ] crontab 등록 (@reboot start + monitor + 매일 09:00 clean_logs)
- [ ] CLAUDE.md `# 실행 방법` 섹션에 스크립트 경로 추가

---

# 실매매 프로그램 구조

## 계정 구분

| 디렉토리 | 계정 | 심볼 | 전략 | 타임프레임 |
|---|---|---|---|---|
| `hyper_scalper_live_trading_real/` | 메인 계정 | BTCUSDC + BTCUSDT | EMA Retest | 15m |
| `hyper_v2_sub_account/` | 서브 계정 | BTCUSDT | EMA Retest (v2 파라미터) | 15m |
| `eth_hyper_live/` | 서브 계정 | ETHUSDT | EMA Retest (ETH) | 15m |

- 메인 계정 API: `hyper_scalper_live_trading_real/.env`
- 서브 계정 API: `hyper_v2_sub_account/.env`, `eth_hyper_live/.env` (동일 키)

## 파라미터 비교 (각 전략별)

### hyper_scalper_live_trading_real — BTCUSDC (`config_hyper.txt`)
- 백테스트 뿌리: `backtest_hyper_scalper_v2.py`
- EMA 25/100/200, ADX≥35, RETEST=8, SL_LB=29, MAX_SL=3%
- ATR=10, TP_L=4.1, TP_S=4.1
- MAKER=0.0, TAKER=0.0004, FEE_PROTECTION=true

### hyper_scalper_live_trading_real — BTCUSDT (`config_hyper_usdt.txt`)
- 백테스트 뿌리: `backtest_hyper_scalper_v2_ema20.py`
- EMA 20/100/200, ADX≥45, RETEST=15, SL_LB=30, MAX_SL=3.5%
- ATR=14, TP_L=10.0, TP_S=3.0
- MAKER=0.0002, TAKER=0.0005, FEE_PROTECTION=true

### hyper_v2_sub_account — BTCUSDT (`config_hyper_v2.txt`)
- 백테스트 뿌리: `backtest_hyper_scalper_v2.py`
- EMA 25/100/200, ADX≥35, RETEST=8, SL_LB=29, MAX_SL=3.5%
- ATR=10, TP_L=4.1, TP_S=4.1
- MAKER=0.0002, TAKER=0.0005, FEE_PROTECTION=true

### eth_hyper_live — ETHUSDT (`config_eth_hyper.txt`)
- 백테스트 뿌리: `backtest_hyper_scalper_eth_15m_r1.py`
- EMA 20/100/200, ADX≥40, RETEST=15, SL_LB=50, MAX_SL=3.5%
- ATR=10, TP_L=10.0, TP_S=2.0
- MAKER=0.0002, TAKER=0.0005, FEE_PROTECTION=true

---

## fee_protection (수수료 보전)

TP 계산 시 fee_offset:
```python
if fee_protection:
    fee_offset = entry_price * (taker_fee * 2 + maker_fee)
```
- config에서 FEE_PROTECTION, TAKER_FEE, MAKER_FEE를 읽어 계산
- 각 전략의 수수료율에 따라 자동 적용

---

## 실제 PnL 조회 (`get_actual_trade_pnl`)

- `hyper_v2_sub_account`, `eth_hyper_live`에 적용됨
- 청산 시 바이낸스 API에서 실제 체결 내역 조회:
  1. 진입 orderId로 진입 수수료 합산
  2. 진입 시간 이후 realizedPnl ≠ 0 체결들로 청산 PnL + 수수료 합산
  3. net_pnl = realizedPnl - 진입fee - 청산fee
- 실패 시 로컬 근사값으로 fallback
- PositionState에 `entry_order_id`, `entry_time_ms` 저장 (JSON 영속화)

## 자본금 관리

- `hyper_scalper_live_trading_real`: 청산 후 바이낸스 잔고의 90%로 동기화
- `hyper_v2_sub_account`, `eth_hyper_live`: INITIAL_CAPITAL 고정 + 거래 PnL 누적 (계정 공유로 잔고 동기화 불가)

## 포지션 사라짐 감지 (30초 동기화)

모든 프로그램 공통:
1. TP orderId로 주문 상태 조회 → FILLED면 `on_tp_filled()` 호출
2. SL orderId로 주문 상태 조회 → FILLED면 `on_sl_filled()` 호출
3. 둘 다 확인 불가 → fallback PnL 조회

---

# Hyper Scalper 전략 로직

## 전략 개요

**EMA 정배열/역배열 + ADX + Retest** 기반의 추세추종 전략.
- 15분봉, LONG & SHORT 양방향
- 동적 레버리지 (손절 거리 기반)
- 동적 익절 (ATR 기반)

## 진입 조건

### LONG (4가지 모두 충족)
1. 정배열: close > EMA_SLOW, EMA_FAST > EMA_MID > EMA_SLOW
2. ADX >= threshold
3. 최근 N봉 내 저가가 EMA_FAST 아래였던 적 있음 (dip)
4. 현재 종가 > EMA_FAST (reclaim)

### SHORT (4가지 모두 충족)
1. 역배열: close < EMA_SLOW, EMA_FAST < EMA_MID < EMA_SLOW
2. ADX >= threshold
3. 최근 N봉 내 고가가 EMA_FAST 위였던 적 있음 (rally)
4. 현재 종가 < EMA_FAST (reclaim)

## 진입 실행
- SL = 최근 N봉 최저/최고 (MAX_SL_DISTANCE 캡)
- 레버리지 = RISK_PER_TRADE / (SL거리 + TAKER_FEE × 2)
- TP = 진입가 ± ATR × 배수 ± fee_offset
- 포지션 크기 = 자본 × 레버리지 / 진입가

## 수수료
- 진입: TAKER (시장가)
- TP: MAKER (지정가)
- SL: TAKER (시장가)

---

# 지표 계산 (TradingView 호환)

- EMA: `ewm(span, adjust=False)`
- RMA: `alpha=1/length`, 첫 값 SMA seed
- ATR: RMA 기반 TR
- ADX: RMA 기반 +DI/-DI → DX → RMA

---

# FVG Retest 전략 (fvg_strategy/)

## 전략 개요
FVG (Fair Value Gap) Retest — 3봉 패턴 갭 감지 후 되돌림 진입.
- 15분봉, LONG & SHORT, 지정가 진입 (MAKER)
- 백테스트 뿌리: `fvg_winners/` 디렉토리

## 계정: 별도 부계정 (3번째 계정)

| 심볼 | 버전 | 핵심 파라미터 |
|---|---|---|
| BTCUSDT | v6_1 (HTF) | RR=1.3, SL_BUF=0.003, RISK=3%, WAIT=25 |
| ETHUSDT | v3 (no HTF) | RR=1.5, SL_BUF=0.005, RISK=2%, WAIT=20 |
| XRPUSDT | v6_2 (HTF) | RR=1.4, SL_BUF=0.0045, RISK=2.5%, WAIT=15 |
| SOLUSDT | v6_1 (HTF) | RR=1.7, SL_BUF=0.004, RISK=2.5%, WAIT=7 |

공통: TAKER=0.0005, MAKER=0.0002, MAX_LEV=90, HTF_EMA=200, MAX_QUEUE=16

## 진입 흐름
1. 15m 봉 마감 → FVG 감지 (low[i] > high[i-2] or high[i] < low[i-2])
2. 큐 추가 + invalidation/timeout
3. HTF 필터 (직전 닫힌 1h close vs EMA200, BTC/XRP/SOL만)
4. 최적 FVG 선택 → 지정가 주문 배치 (MAKER)
5. 체결 → SL/TP 설정
6. SL = FVG 반대편 ± buffer, TP = entry ± RR × SL거리

## 수수료
- 진입: MAKER 0.02% (지정가)
- TP: MAKER 0.02% (지정가)
- SL: TAKER 0.05% (시장가)

## 📌 라이브 운영 로그 (중지/재시작/버그수정 기록)

- **파일: `fvg_strategy/LIVE_RUN_LOG.md`**
- 재시작할 때마다 "현재 안정 운영 시작 시각" 갱신 + 실행 히스토리 한 줄 추가
- 이 시각 기준 **1주일 재시작 없으면** 백테스트와 비교 (DRY 때 `verify_dry_btc_eth.py` 방식 참고)

## TODO (fvg_strategy) — **LIVE 전환 완료 (2026-04-23)**
- [x] 새 부계정 API 키 → `.env` 입력
- [x] 부계정에 5,998 USDT 이체 완료
- [x] DRY_RUN=true 테스트 (2026-04-22~23, BTC 2건 + ETH 1건 백테스트와 1:1 매치)
- [x] 백테스트와 진입/청산 비교 검증 (`backtest/fvg_winners/verify_dry_btc_eth.py`)
- [x] DRY_RUN=false 전환 (4심볼 × $1,350 = $5,400, 지갑 $5,998의 90%)
- [x] crontab 등록 (@reboot sleep 65-85 + 09:00 로그정리 + monitor)
- [x] monitor.sh 텔레그램 알림 (bot token + chat_id 기존 재사용, 시작/종료/에러 알림만)

## 라이브 주의사항 (FVG 4심볼)
- 4심볼 같은 부계정 공유 — 동시 진입 시 증거금 경합 가능. 바이낸스가 margin 부족 시 reject → `_place_pending` 10회 재시도 후 포기
- 히스테리시스 스위칭: **BTC/XRP/SOL (HTF ON)은 발동 안 됨** (bull/bear 상호배타). **ETH (HTF OFF)만** 양방향 동시 valid일 때 tick 기반 스위칭 발동
- capital은 local 누적 (hyper_scalper처럼 wallet auto-sync 없음). 출금/입금 시 `state/state_fvg_*.json` 수동 편집 필요

---

# 중앙 시세 프로세스 (price_feed) — 단일 WebSocket 멀티플렉싱

## 배경 (왜 도입했나)

2026-04-24, 개별 전략 7개가 각자 Binance WS connection 열던 구조에서 **Binance "silent throttle"** 발생 (연결은 받아주되 데이터 안 보냄).

원인 분석:
- 한 IP 에서 7개 WS + 중복 심볼 구독 (BTCUSDT x2, ETHUSDT x2)
- 30초 짧은 heartbeat timeout 이 reconnect spiral 유발 → 분당 10회+ 재접속 → Binance abuse heuristic 발동
- REST API 는 멀쩡, WS 만 **shadow throttle**

**해결**: 단일 중앙 시세 프로세스가 모든 심볼 1개 connection 으로 받고 ZMQ pub/sub 으로 각 전략에 뿌려줌.

## 아키텍처

```
┌──────────────────────────────────────────┐
│   price_feed.py                          │
│   - 단일 Binance WS (combined streams)   │
│   - 5 심볼 × 3 스트림 = 15 streams        │
│   - kline_15m + kline_1h + trade         │
│   - 90s heartbeat + exponential backoff  │
│   - Telegram 끊김/재연결 알림 (1회씩)     │
│           ↓                              │
│   ZMQ PUB 소켓 (tcp://127.0.0.1:5555)    │
└─────────────────┬────────────────────────┘
                  │
          localhost pub/sub
                  │
       ┌──────┬──┴──┬──────┬──────┬──────┐
       ▼      ▼     ▼      ▼      ▼      ▼
     fvg    fvg   fvg   hyper hyper  hyper  eth_
     eth    xrp   sol         usdt   v2     hyper
     (7 프로세스가 IPCSubscriber 로 구독)
```

**Binance 에 가는 connection 수: 7개 → 1개** (Throttle 문제 근본 해결)

## 파일 구조

```
/home/double_st_strategy/price_feed/
├── price_feed.py      # 메인: WS → ZMQ PUB
├── ipc_client.py      # 공용: IPCSubscriber (각 전략이 import)
├── scripts/
│   ├── start.sh
│   ├── stop.sh
│   ├── monitor.sh     # PID 감시 + Telegram 알림
│   └── clean_logs.sh  # 5일치 보존
├── logs/              # price_feed_YYYY-MM-DD.log
└── state/
    └── price_feed.pid
```

## 구독 심볼 / 스트림

**심볼**: BTCUSDT, BTCUSDC, ETHUSDT, XRPUSDT, SOLUSDT (5개)
**스트림**: kline_15m, kline_1h, trade (3개, 총 15 streams)

### ⚠️ `trade` vs `aggTrade` 교훈 (2026-04-24)

- **초기 설계**: `aggTrade` 사용 (일반적 권장)
- **발견**: Binance 글로벌 이슈로 **`aggTrade` 스트림 자체가 데이터 안 보내는 현상** (다른 IP 에서도 재현됨)
- **대응**: `trade` 로 교체 — 동일 필드 (`p`, `q`) 제공, 오히려 더 실시간 (초당 더 많음)
- **교훈**: 장애 시 다른 스트림 종류로 우회 시도할 것. `trade`/`aggTrade`/`markPrice` 각각 별개 인프라라 선택적 장애 가능

## ZMQ 프로토콜

**Topic 포맷**: `{SYMBOL}.{stream_type}`
- 예: `"BTCUSDT.kline_15m"`, `"ETHUSDT.trade"`, `"XRPUSDT.kline_1h"`

**Message**: multipart `[topic_bytes, payload_bytes]`
- `payload`: Binance raw JSON (kline 경우 `k` 오브젝트 내용, trade 경우 원본 객체)

**구독**: 각 전략이 필요한 topic 만 SUBSCRIBE
```python
from ipc_client import IPCSubscriber

subscriber = IPCSubscriber(
    symbol="ETHUSDT",
    on_kline_15m=strategy.on_candle_close,
    on_kline_1h=strategy.on_htf_kline,      # None 이면 구독 안 함 (HTF 안 쓰는 전략)
    on_tick=strategy.on_tick,
    logger=log_handler,
    send_alert=_send_telegram_alert,
)
await subscriber.run()  # 무한 루프 (websocket_handler 대체)
```

## 재연결 정책 (price_feed)

- **heartbeat timeout**: 90초 무수신 시 `asyncio.TimeoutError` 발생 → 강제 재연결
- **exponential backoff**: 5 → 10 → 20 → 40 → 80 → 160 → 300s (max 5분)
- **성공 연결 시 backoff 리셋**
- **Telegram 알림**: 끊김 🔴 1회 + 재연결 복구 🟢 1회 (중복 방지)

## 전략 쪽 재연결 (IPCSubscriber)

- ZMQ SUB 는 가벼워 거의 안 끊김
- **IPC 레벨 heartbeat**: 120초 무수신 → price_feed 이상 판정 → 재연결 + Telegram
- exponential backoff (2 → 4 → 8 → 16 → 32 → 60s)

## 기동 순서

**중요**: price_feed 가 먼저 떠 있어야 ZMQ SUB 가 정상 연결됨.

```bash
# 1. price_feed 먼저
/home/double_st_strategy/price_feed/scripts/start.sh

# 2. 5초 대기 (ZMQ PUB 안정화)
sleep 5

# 3. 전략들
/home/double_st_strategy/fvg_strategy/scripts/start_fvg_{eth,xrp,sol}.sh
/home/double_st_strategy/hyper_scalper_live_trading_real/scripts/start_hyper.sh
/home/double_st_strategy/hyper_scalper_live_trading_real/scripts/start_hyper_usdt.sh
/home/double_st_strategy/hyper_v2_sub_account/scripts/start_hyper_v2.sh
/home/double_st_strategy/eth_hyper_live/scripts/start_eth_hyper.sh

# 4. price_feed 모니터
/home/double_st_strategy/price_feed/scripts/monitor.sh &
```

**crontab @reboot 순서** (sleep 값으로 순서 제어):
```
@reboot sleep 25 && ./price_feed/scripts/start.sh
@reboot sleep 30 && ./hyper_scalper_live_trading_real/scripts/start_hyper.sh
@reboot sleep 35 && ./hyper_scalper_live_trading_real/scripts/start_hyper_usdt.sh
@reboot sleep 45 && ./hyper_v2_sub_account/scripts/start_hyper_v2.sh
@reboot sleep 50 && ./eth_hyper_live/scripts/start_eth_hyper.sh
@reboot sleep 70 && ./fvg_strategy/scripts/start_fvg_eth.sh
@reboot sleep 75 && ./fvg_strategy/scripts/start_fvg_xrp.sh
@reboot sleep 80 && ./fvg_strategy/scripts/start_fvg_sol.sh
@reboot sleep 90 && ./price_feed/scripts/monitor.sh &
```

## 디버깅

**price_feed 가 데이터 수신 중인지 확인:**
```python
import zmq, zmq.asyncio, asyncio
async def t():
    ctx = zmq.asyncio.Context()
    s = ctx.socket(zmq.SUB)
    s.connect("tcp://127.0.0.1:5555")
    s.setsockopt(zmq.SUBSCRIBE, b"")
    for _ in range(20):
        parts = await s.recv_multipart()
        print(parts[0].decode(), parts[1][:80])
asyncio.run(t())
```

**개별 심볼 확인**:
```python
s.setsockopt(zmq.SUBSCRIBE, b"BTCUSDT.trade")  # BTCUSDT trade 만
```

## Blast radius (단일 실패점)

**price_feed 죽으면 → 전 전략 blind**. 완화책:
1. `monitor.sh` PID 감시 + Telegram 알림
2. IPCSubscriber 자체 heartbeat (120s) 로 전략 쪽에서도 감지
3. `@reboot` 자동 기동 (서버 재부팅 시 자동 복구)

필요 시 future work: price_feed HA (2 프로세스 active-standby) — 현재는 단일

---

# Git 자동 복사 훅

`/home/double_st_strategy/.claude/settings.local.json`에 PostToolUse 훅 설정됨.

Write/Edit/MultiEdit 도구로 다음 디렉토리 안의 파일을 수정하면, 자동으로 git repo로 복사:

```
/home/double_st_strategy/{fvg_strategy,eth_hyper_live,hyper_v2_sub_account,hyper_scalper_live_trading_real}/*
  ↓
/home/hyper_scalper_git/hyper_scalper_live_trading_real/{같은 디렉토리}/*
```

## 제외 파일
- `.env` (API 키)
- `__pycache__/`
- `state/*.json`, `state/*.pid` (런타임 상태)
- `logs/*.log` (로그)
- `trades/*.csv` (거래 기록)

수정하면 stderr에 `[git-sync] {경로}` 로그 출력됨.

---

# crontab 설정

```
@reboot  price_feed 먼저 기동 (모든 전략의 시세 공급원)
@reboot  hyper_scalper USDC, USDT, monitor 시작
@reboot  hyper_v2_sub_account 시작 + monitor
@reboot  eth_hyper_live 시작 + monitor
@reboot  fvg_strategy (ETH/XRP/SOL) 시작 + monitor — BTC 는 제외 (사용자 결정)
매일 09:00  각 디렉토리 로그 정리 (최근 5일치 보존, price_feed 포함)
```

---

# 실행 방법

```bash
# hyper_scalper (메인 계정)
hyper_scalper_live_trading_real/scripts/start_hyper.sh      # BTCUSDC
hyper_scalper_live_trading_real/scripts/start_hyper_usdt.sh  # BTCUSDT

# hyper_v2 (서브 계정)
hyper_v2_sub_account/scripts/start_hyper_v2.sh
hyper_v2_sub_account/scripts/stop_hyper_v2.sh

# eth_hyper (서브 계정)
eth_hyper_live/scripts/start_eth_hyper.sh
eth_hyper_live/scripts/stop_eth_hyper.sh

# fvg_strategy (별도 부계정)
fvg_strategy/scripts/start_fvg_btc.sh   # BTCUSDT
fvg_strategy/scripts/start_fvg_eth.sh   # ETHUSDT
fvg_strategy/scripts/start_fvg_xrp.sh   # XRPUSDT
fvg_strategy/scripts/start_fvg_sol.sh   # SOLUSDT
fvg_strategy/scripts/stop_fvg_btc.sh
fvg_strategy/scripts/stop_fvg_eth.sh
fvg_strategy/scripts/stop_fvg_xrp.sh
fvg_strategy/scripts/stop_fvg_sol.sh
```

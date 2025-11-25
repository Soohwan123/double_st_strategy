
# Double Bollinger Band Strategy - 가이드
 
 바이낸스 선물 거래를 위한 Double Bollinger Band 자동매매 전략
 ---
 
 ## � 프로젝트 개요
 
 이 프로젝트는 **5분봉**에서 **BB(20,2)와 BB(4,4) 동시 터치**로 진입하는 스캘핑 전략입니다.
 
 ### 핵심 특징
 
 - **틱데이터 기반**: aggTrade 스트림으로 실시간 BB 터치 감지 (밀리초 단위)
 - **동시 터치 조건**: BB(20,2)와 BB(4,4) 두 밴드 모두 터치 시 진입
 - **진입가**: bb_lower_4_4 (LONG) / bb_upper_4_4 (SHORT) 값에 진입
 - **익절**: 진입가의 0.3% 지정가 주문
 - **본절 스탑로스**: 진입 봉 마감 후 다음 봉부터 진입가에 활성화
 - **레버리지**: 10배 고정
 - **TradingView 표준**: Population std (ddof=0) 사용
 
 ---
 
 ## � 전략 로직
 
 ### 1. 진입 조건
 
 #### LONG 진입:
 ```
 현재 가격 <= bb_lower_20_2 AND 현재 가격 <= bb_lower_4_4
 → bb_lower_4_4 값에 시장가 진입
 ```
 
 #### SHORT 진입:
 ```
 현재 가격 >= bb_upper_20_2 AND 현재 가격 >= bb_upper_4_4
 → bb_upper_4_4 값에 시장가 진입
 ```
 
 **중요**: 틱데이터로 실시간 가격 체크하여 **터치 즉시 진입**
 
 ---
 ### 2. 익절 (Take Profit)
 - **비율**: 진입가의 0.3%
 - **주문 타입**: LIMIT (지정가)
 
 **예시**:
 ```
 LONG 진입가: $67,000
 익절가: $67,201 (67000 * 1.003)
 ```
 
 ---
 
 ### 3. 본절 스탑로스 (Break-Even Stop)
 
 #### 활성화 타이밍:
 - **진입 봉**: 본절 없음, 익절만 확인
 - **진입 봉 마감 후**: 다음 봉부터 진입가에 STOP_MARKET 주문 설정
 
 #### 주문 타입:
 - STOP_MARKET (closePosition=True)
 - 진입가에 도달하면 자동 청산
 
 **예시**:
 ```
 5:40 봉에서 진입 → 5:40~5:45 동안은 익절만
 5:45 봉 마감 → 5:45부터 본절 스탑로스 활성화
 ```
 
 ---
 
 ### 4. 포지션 사이징
 
 ```python
 자본의 100% * 레버리지 10배 = 포지션 가치
 포지션 크기 = 포지션 가치 / 진입가
 
 예시:
 - 자본: $1,000
 - 레버리지: 10배
 - 포지션 가치: $10,000
 - 진입가: $67,000
 - 포지션 크기: 0.149 BTC
 ```
 
 ---
 
 ## � 파일 구조
 
 ```
 bollinger_data/
 ├── CLAUDE.md                                    # 이 파일
 │
 ├── prepare_bollinger_data.py                    # 백테스트 데이터 준비
 ├── backtest_double_bb.py                        # 백테스트 엔진
 │
 ├── live_trading/
 │   ├── double_bb.py                             # 라이브 트레이딩 (메인)
 │   ├── config.py                                # 전략 설정 (API 키, 파라미터)
 │   └── test_api_ml.py                           # API 연결 테스트
 │
 ├── backtest_data/                               # 백테스트 데이터
 │   └── BTCUSDT_double_bb_2019_10_11.csv
 │
 ├── historical_data/                             # 원시 데이터
 │   └── BTCUSDT_5m_raw.csv
 │
 ├── live_data/                                   # 라이브 지표 데이터
 │   └── live_indicators.csv                      # DRY RUN 모드 출력
 │
 └── trade_results/                               # 거래 결과
     └── double_st_trades.csv
 ```
 
 ---
 
 ## � 백테스트 실행
 
 ### 1. 데이터 준비
 
 ```bash
 cd bollinger_data
 python prepare_bollinger_data.py
 ```
 
 **설정 수정** (`prepare_bollinger_data.py` 상단):
 ```python
 START_DATE = '2025-04-01'  # 시작 날짜
 END_DATE = '2025-11-30'    # 종료 날짜
 SYMBOL = 'BTCUSDT'
 ```
 
 ### 2. 백테스트 실행
 
 ```bash
 python backtest_double_bb.py
 ```
 
 **설정 수정** (`backtest_double_bb.py` 상단):
 ```python
 START_DATE = '2020-12-01'       # 백테스트 시작
 END_DATE = '2022-11-30'         # 백테스트 종료
 INITIAL_CAPITAL = 1000.0        # 초기 자본 (USDT)
 LEVERAGE = 10                   # 레버리지
 TAKE_PROFIT_PCT = 0.003         # 익절 비율 (0.3%)
 FEE_RATE = 0.0004               # 수수료 (0.04%)
 ```
 
 ### 3. 결과 확인
 
 ```bash
 # 거래 내역
 cat trades_double_bb.csv
 
 # 자본 곡선
 cat backtest_results_double_bb.csv
 ```
 
 ---
 
 ## � 라이브 트레이딩 실행
 
 ### 1. API 키 설정
 
 `live_trading/.env` 파일 생성 또는 `config.py` 수정:
 ```bash
 BINANCE_API_KEY=your_binance_api_key
 BINANCE_API_SECRET=your_binance_api_secret
 USE_TESTNET=False
 SYMBOL=BTCUSDC
 ```
 
 **⚠️ 중요**:
 - Binance Futures API 키 필요
 - 읽기 + 거래 권한 활성화
 - IP 화이트리스트 설정 권장
 
 ### 2. API 연결 테스트
 
 ```bash
 cd live_trading
 python test_api_ml.py
 ```
 
 ### 3. DRY RUN 모드 (테스트용)
 
 **현재 코드는 DRY RUN 모드입니다** - 실제 주문 없이 로그만 기록
 
 ```bash
 python double_bb.py
 ```
 
 **DRY RUN 모드 특징**:
 - � 실제 주문 실행 **없음** (모두 주석처리)
 - � BB 계산 및 진입 신호는 정상 작동
 - � `live_data/live_indicators.csv`에 실시간 지표 저장
 - ✅ TradingView와 BB 계산 비교 가능
 
 ### 4. 실제 거래 모드로 전환
 
 `double_bb.py`에서 주석을 해제하여 실제 거래 활성화:
 
 **주석 해제해야 할 부분**:
 1. `open_position()` - 마진, 레버리지, 시장가 주문 (line 509-537)
 2. `set_take_profit_order()` - 익절 지정가 주문 (line 592-612)
 3. `set_break_even_stop()` - 본절 스탑마켓 주문 (line 633-648)
 4. `cancel_stop_orders()` - STOP 주문 취소 (line 664-674)
 5. `cancel_pending_orders()` - 대기 주문 취소 (line 690)
 6. `monitor_positions()` - 포지션 모니터링 전체 (line 734-789)
 7. `close_position_manual()` - 수동 청산 주문 (line 847-852)
 
 **⚠️ 실제 거래 시 주의**:
 - 소액($100~$500)으로 먼저 테스트
 - 레버리지 10배는 청산 리스크 있음
 - 일일 손실 한도 설정 권장
 
 ### 5. 백그라운드 실행
 
 ```bash
 nohup python double_bb.py > output.log 2>&1 &
 
 # 로그 확인
 tail -f output.log
 
 # 일별 로그
 tail -f logs/double_bb_strategy_btcusdc_2025-XX-XX.log
 ```
 
 ### 6. 거래 내역 확인
 
 ```bash
 cat trade_results/double_st_trades.csv
 ```
 
 ---
 
 ## � 로그 및 모니터링
 
 ### 로그 파일:
 
 1. **일별 로그**: `logs/double_st_strategy_btcusdc_YYYY-MM-DD.log`
    - 진입/청산 기록
    - 틱터치 감지
    - 본절 활성화
 
 2. **거래 내역**: `trade_results/double_st_trades.csv`
    - timestamp, type, direction, price, size, pnl, balance
 
 3. **라이브 지표**: `live_data/live_indicators.csv` (DRY RUN 모드)
    - timestamp, OHLCV, bb_upper_20_2, bb_lower_20_2, bb_upper_4_4, bb_lower_4_4
 
 ### 로그 확인:
 
 ```bash
 # 오늘 로그
 tail -f logs/double_st_strategy_btcusdc_$(date +%Y-%m-%d).log
 
 # 진입 신호만
 grep "틱터치" logs/*.log
 
 # 청산 내역
 grep "청산" logs/*.log
 
 # DRY RUN 확인
 grep "DRY RUN" logs/*.log
 ```
 
 ---
 
 ## � 백테스트 로직 분석
 
 ### 진입 로직 (check_long_entry / check_short_entry):
 
 ```python
 # LONG
 if low <= bb_lower_20_2 and low <= bb_lower_4_4:
     return True, bb_lower_4_4  # 4/4 값에 진입
 
 # SHORT
 if high >= bb_upper_20_2 and high >= bb_upper_4_4:
     return True, bb_upper_4_4  # 4/4 값에 진입
 ```
 
 ### 청산 로직 (process_bar):
 
 **본절 타이밍**:
 ```python
 entry_bar_idx = position['entry_bar_idx']  # 진입 봉 인덱스
 sl_active = (idx > entry_bar_idx)          # 다음 봉부터 활성화
 ```
 
 **LONG 청산 (본절 활성화 시)**:
 1. **갭 다운**: `open_price < entry_price` → 시가에 손절
 2. **익절&본절 동시 가능**: 시가 기준으로 우선순위 판단
    - 시가 ≥ 진입가 → 익절 우선
    - 시가 < 진입가 → 본절 우선
 3. **익절만**: `high >= tp_price` → 익절가에 청산
 4. **본절만**: `low <= entry_price` → 진입가에 청산
 
 **진입 봉 (`sl_active=False`)**: 익절만 확인, 본절 없음
 
 ---
 
 ## � 라이브 트레이딩 로직 분석
 
 ### 웹소켓 스트림:
 
 ```python
 # 5분봉 + 틱데이터 동시 구독
 stream_url = "wss://fstream.binance.com/stream?streams=
               btcusdc@kline_5m/btcusdc@aggTrade"
 ```
 
 ### 데이터 처리:
 
 **5분봉 마감 시** (`kline['x'] == True`):
 ```python
 async def on_5m_candle_close(kline):
     # 1. 캔들 데이터 업데이트
     # 2. BB 지표 재계산
     # 3. 본절 활성화 체크 (check_candle_close)
     # 4. CSV 저장
 ```
 
 **틱데이터 수신 시** (실시간):
 ```python
 async def on_tick(trade):
     price = float(trade['p'])  # 현재 가격
 
     # BB 터치 감지
     if price <= bb_lower_20_2 and price <= bb_lower_4_4:
         await open_position('LONG', bb_lower_4_4)
 ```
 
 ### 포지션 관리:
 
 **진입**:
 ```python
 async def open_position(direction, entry_price):
     # 1. 레버리지 10배 설정
     # 2. 시장가 주문
     # 3. 익절 지정가 주문 설정
     # 4. entry_bar_closed = False (진입 봉)
 ```
 
 **본절 활성화**:
 ```python
 async def check_candle_close():
     # 진입 시간과 현재 시간 비교
     if current_time > entry_candle_time:
         # 본절 스탑로스 설정 (STOP_MARKET)
         entry_bar_closed = True
 ```
 
 **모니터링** (5초마다):
 ```python
 async def monitor_positions():
     # 바이낸스 실제 포지션 확인
     # 포지션 사라짐 → 익절 or 본절 or 손절 판단
     # 거래 기록 저장
 ```
 
 ---
 
 ## ⚠️ 주의사항
 
 ### 1. 리스크 관리
 - **절대 전체 자본 투입 금지**
 - 초기에는 소액($100~$500)으로 테스트
 - 레버리지 10배는 변동성 높으면 청산 리스크
 - 일일 손실 한도 설정 권장
 
 ### 2. 백테스트 vs 실전
 ```
 백테스트 수익률 ≠ 실전 수익률
 
 실전에서 발생하는 요소:
 - 슬리피지 (가격 미끄러짐)
 - 수수료 (실제가 더 많을 수 있음)
 - 웹소켓 지연
 - API 제한
 - 거래소 점검
 ```
 
 ### 3. 틱데이터 특성
 - aggTrade는 **체결된 거래**만 전송
 - 거래량 없으면 틱 없음 → 터치 못 잡을 수 있음
 - 변동성 낮을 때는 5분봉 High/Low와 차이 발생 가능
 
 ### 4. 모니터링 필수
 - 하루 최소 2~3회 거래 내역 확인
 - 예상치 못한 손실 발생 시 즉시 중단
 - 프로그램이 정상 작동하는지 로그 확인
 
 ### 5. 긴급 중단
 ```bash
 # 프로세스 찾기
 ps aux | grep double_bb
 
 # 프로세스 종료 (PID 확인 후)
 kill -9 [PID]
 
 # 모든 포지션 수동 청산 필요
 ```
 
 ---
 
 ## � 트러블슈팅
 
 ### 문제 1: "API 연결 실패"
 ```
 원인: API 키 오류 또는 네트워크 문제
 해결:
   1. config.py의 API 키 재확인
   2. Binance API 권한 확인 (Futures 거래 활성화)
   3. IP 화이트리스트 설정 확인
 ```
 
 ### 문제 2: "웹소켓 연결 끊김"
 ```
 원인: 네트워크 불안정
 해결:
   - 자동 재연결 로직 있음 (5초 대기 후 재시도)
   - WS_RECONNECT_DELAY 조정 가능
 ```
 
 ### 문제 3: "포지션 진입 안됨"
 ```
 원인:
   1. BB 터치가 없음
   2. 이미 포지션이 있음
   3. BB 계산 안됨 (데이터 부족)
 
 해결:
   - 로그 확인하여 BB 값 체크
   - 최소 20개 이상 5분봉 필요
 ```
 
 ### 문제 4: "본절 스탑로스 작동 안함"
 ```
 원인: entry_bar_closed 플래그 오류
 해결:
   - check_candle_close() 함수 확인
   - 로그에서 "본절 스탑로스 활성화" 메시지 확인
 ```
 
 ---
 
 ## � 핵심 개념 정리
 
 ### Bollinger Band 계산 (TradingView 표준):
 
 ```python
 # SMA
 sma = close.rolling(window=20).mean()
 
 # Population Std (ddof=0)
 std = close.rolling(window=20).std(ddof=0)
 
 # Upper/Lower Band
 upper = sma + (2 * std)
 lower = sma - (2 * std)
 ```
 
 ### Rolling Window:
 
 - 라이브: 최근 200개 5분봉 보관
 - BB(20,2): 최소 20개 필요
 - 200개면 10배 여유 → 충분함
 - `test_rolling_window.py`로 정확도 검증 완료
 
 ### 수수료 계산:
 
 ```python
 # 진입 수수료
 entry_fee = position_value * fee_rate
 
 # 청산 수수료
 exit_fee = position_value * fee_rate  # PnL과 무관하게 고정
 
 # 순 PnL
 net_pnl = gross_pnl - entry_fee - exit_fee
 ```
 
 ---
 
 ## � DRY RUN → 실제 거래 전환 가이드
 
 ### 1. DRY RUN 모드로 하루 테스트
 
 ```bash
 cd live_trading
 python double_bb.py
 ```
 
 **확인할 것**:
 1. `live_data/live_indicators.csv`와 TradingView BB 값 비교
 2. 진입 신호가 정상적으로 로그에 기록되는지 확인
 3. 본절 활성화 타이밍이 올바른지 확인
 
 ### 2. BB 계산 검증
 
 ```bash
 # 최근 20개 행 확인
 tail -20 live_data/live_indicators.csv
 
 # TradingView와 비교:
 # - bb_upper_20_2, bb_lower_20_2
 # - bb_upper_4_4, bb_lower_4_4
 ```
 
 ### 3. 실제 거래 모드 활성화
 
 `double_bb.py`에서 � [DRY RUN] 섹션의 주석을 해제:
 
 ```python
 # 주석 해제 예시 (line 527-533):
 order = self.client.futures_create_order(
     symbol=self.symbol,
     side=side,
     type=ORDER_TYPE_MARKET,
     quantity=quantity
 )
 # logger.info(f"� [DRY RUN] Market Order...")  # 이 줄은 삭제
 ```
 
 모든 � DRY RUN 섹션을 동일하게 처리
 
 ### 4. 실제 거래 시작
 
 ```bash
 # 백그라운드 실행
 nohup python double_bb.py > output.log 2>&1 &
 
 # 실시간 모니터링
 tail -f output.log
 ```
 
 ---
 
 **마지막 업데이트**: 2025-01-25
 **버전**: 2.0 (Double Bollinger Band)
 
 **⚠️ 면책 조항**: 이 소프트웨어는 교육 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해 개발자는 책임지지 않습니다. 투자는 본인
 책임 하에 진행하세요

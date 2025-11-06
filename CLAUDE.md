# Double SuperTrend Strategy - 완전 가이드

바이낸스 선물 거래를 위한 Double SuperTrend 자동매매 전략

---

## 📌 프로젝트 개요

이 프로젝트는 **5분봉 + 1시간봉**의 **4개 SuperTrend 지표**를 조합하여 BTC 선물 거래 신호를 생성하는 시스템입니다.

### 핵심 특징

- **멀티 타임프레임**: 5분봉과 1시간봉 동시 분석
- **4개 SuperTrend**: 각 타임프레임에서 ST(12,1), ST(12,3) 사용
- **동적 손절**: 과거 30개 봉 기준 최저/최고점
- **1:1 익절**: 손절 거리와 동일한 익절 + SuperTrend 반전 확인
- **리스크 관리**: 자본의 1% 고정 리스크, 동적 레버리지
- **RMA 기반 ATR**: TradingView/Binance 표준 계산 방식

---

## 🎯 전략 로직 상세 설명

### 1. 진입 조건

#### 필수 조건 (모두 충족 필요):

1. **1시간봉 정렬**: ST(12,1)과 ST(12,3)이 **모두 같은 방향**
   - LONG 정렬: 두 ST 모두 상승 신호 (direction = 1)
   - SHORT 정렬: 두 ST 모두 하락 신호 (direction = -1)
   - NEUTRAL: 방향이 다름 → 거래 안함

2. **5분봉 전환 신호**:
   - **LONG 진입**: 5분봉 두 ST가 모두 SHORT → 모두 LONG으로 전환
   - **SHORT 진입**: 5분봉 두 ST가 모두 LONG → 모두 SHORT로 전환

#### 플래그 시스템:

```
buy_set → buy_ready → LONG 진입
sell_set → sell_ready → SHORT 진입
```

**LONG 진입 예시**:
1. 5분봉 두 ST가 모두 SHORT → `buy_set = True`
2. 5분봉 두 ST가 모두 LONG으로 전환 → `buy_ready = True`
3. 1시간봉이 LONG 정렬이면 → **LONG 진입**

**SHORT 진입 예시**:
1. 5분봉 두 ST가 모두 LONG → `sell_set = True`
2. 5분봉 두 ST가 모두 SHORT로 전환 → `sell_ready = True`
3. 1시간봉이 SHORT 정렬이면 → **SHORT 진입**

#### 손절 후 재진입:

손절 발생 후에는 플래그 시스템을 거치지 않고:
- **LONG 손절 후**: 5분봉 두 ST가 모두 LONG이면 즉시 재진입
- **SHORT 손절 후**: 5분봉 두 ST가 모두 SHORT이면 즉시 재진입

---

### 2. 손절 (Stop Loss)

#### 계산 방식:
- **LONG**: 진입 전 **최근 30개 5분봉의 최저점**
- **SHORT**: 진입 전 **최근 30개 5분봉의 최고점**

#### 예시:
```
현재가: $67,000
최근 30개 봉 최저점: $66,000

LONG 진입 시:
  - 진입가: $67,000
  - 손절가: $66,000
  - 손절 거리: $1,000 (1.49%)
```

#### 데이터 부족 시:
- 30개 봉 데이터가 없으면 고정 3% 손절 사용
  - LONG: 진입가 × 0.97
  - SHORT: 진입가 × 1.03

#### 손절 실행:
- **LONG**: 5분봉 Low가 손절가 이하로 터치
- **SHORT**: 5분봉 High가 손절가 이상으로 터치

---

### 3. 익절 (Take Profit)

#### 계산 방식:
- **1:1 Risk/Reward**: 손절 거리와 동일한 익절가 설정

#### 예시:
```
LONG 진입:
  - 진입가: $67,000
  - 손절가: $66,000 (리스크: -$1,000)
  - 익절가: $68,000 (보상: +$1,000)
```

#### 익절 조건 (2단계):

**1단계**: 가격이 익절가 도달
- **LONG**: 5분봉 High가 익절가 이상
- **SHORT**: 5분봉 Low가 익절가 이하

**2단계**: 5분봉 ST(12,1) 반전 확인
- **LONG 익절**: ST(12,1)이 SHORT 신호로 전환
- **SHORT 익절**: ST(12,1)이 LONG 신호로 전환

**중요**: 1:1 도달했지만 ST 반전이 없으면 **익절 안함** (계속 홀드)

---

### 4. 포지션 사이징

#### 리스크 기반 계산:

```python
# 1. 리스크 금액 계산
risk_amount = capital × 0.01  # 자본의 1%

# 2. 손절 거리 (%)
stop_distance_pct = |entry_price - stop_price| / entry_price

# 3. 포지션 가치
position_value = risk_amount / stop_distance_pct

# 4. 포지션 크기 (BTC)
position_size = position_value / entry_price
```

#### 예시:
```
자본: $10,000
리스크: $100 (1%)
진입가: $67,000
손절가: $66,000
손절 거리: 1.49%

포지션 가치 = $100 / 0.0149 = $6,711
포지션 크기 = $6,711 / $67,000 = 0.1 BTC
```

#### 레버리지 계산:

```python
# 필요 레버리지
required_leverage = position_value / capital

# 최대 100배 제한
if required_leverage > 100:
    position_value = capital × 100
    position_size = position_value / entry_price
    leverage = 100
else:
    leverage = ceil(required_leverage)
```

#### 안전 장치:
- 손절 거리가 0.01% 미만이면 **진입 안함** (100배 초과 필요)
- 손절가가 진입가보다 불리하면 **진입 안함**
- 증거금 + 수수료가 자본 초과하면 **진입 안함**

---

## 📊 SuperTrend 계산 (RMA 방식)

### ATR 계산 (Wilder's Smoothing):

```python
# True Range
TR = max(High - Low, |High - Close[1]|, |Low - Close[1]|)

# RMA (첫 12개는 SMA)
ATR[11] = average(TR[0:12])

# 이후 RMA
for i in range(12, len):
    ATR[i] = (ATR[i-1] × 11 + TR[i]) / 12
```

### SuperTrend 계산:

```python
# HL2 (중간 가격)
HL2 = (High + Low) / 2

# Basic Bands
Basic_Up = HL2 - (factor × ATR)    # 하단 밴드
Basic_Dn = HL2 + (factor × ATR)    # 상단 밴드

# Final Bands (Trailing)
if Close[i-1] > Final_Up[i-1]:
    Final_Up[i] = max(Basic_Up[i], Final_Up[i-1])
else:
    Final_Up[i] = Basic_Up[i]

# Direction
if Close > Final_Up:
    Direction = 1   # Uptrend
else:
    Direction = -1  # Downtrend
```

---

## 🚀 설치 및 실행 방법

### 1. 환경 구성 (Linux/Rocky)

#### Python 3.12 설치:
```bash
# Rocky Linux / RHEL
sudo dnf install -y python3.12 python3.12-pip python3.12-venv

# 또는 Ubuntu
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-pip
```

#### 가상환경 생성:
```bash
cd /path/to/double_st_strategy

# 가상환경 생성
python3.12 -m venv venv

# 활성화
source venv/bin/activate
```

### 2. 필수 패키지 설치

```bash
# 기본 패키지
pip install --upgrade pip

# 필수 라이브러리
pip install pandas==2.1.4
pip install numpy==1.26.2
pip install python-binance==1.0.19
pip install websockets==12.0
pip install pytz==2023.3
pip install requests==2.31.0

# 또는 requirements.txt 사용
pip install -r requirements.txt
```

#### requirements.txt 내용:
```
pandas==2.1.4
numpy==1.26.2
python-binance==1.0.19
websockets==12.0
pytz==2023.3
requests==2.31.0
```

### 3. API 키 설정

`live_trading/config_ml.py` 파일 수정:
```python
class Config:
    API_KEY = 'your_binance_api_key'
    API_SECRET = 'your_binance_api_secret'
```

**⚠️ 중요**:
- Binance Futures API 키 필요
- 읽기 + 거래 권한 활성화
- IP 화이트리스트 설정 권장

---

## 📁 파일 구조

```
double_st_strategy/
├── CLAUDE.md                          # 이 파일 (전략 설명서)
│
├── calculate_indicators.py            # SuperTrend 계산 (RMA 방식)
├── prepare_backtest_data.py           # 백테스트 데이터 준비
├── prepare_backtest_data_2024_06_11.py
├── backtest_double_st.py              # 백테스트 엔진 (클래스)
├── backtest_double_st_aug_nov.py      # 백테스트 실행 스크립트
│
├── live_trading/
│   ├── double_st_strategy_live.py     # 라이브 트레이딩 (메인)
│   ├── config_ml.py                   # API 키 설정
│   └── test_api_ml.py                 # API 연결 테스트
│
├── backtest_data_2025/                # 백테스트 데이터
│   └── BTCUSDT_double_st_2024_06_11.csv
│
├── historical_data_2025/              # 원시 데이터
│   ├── BTCUSDT_5m_2025_raw.csv
│   └── BTCUSDT_1h_2025_raw.csv
│
└── trade_results/                     # 거래 결과
    └── double_st_trades.csv
```

---

## 🔧 백테스트 실행

### 1. 데이터 준비

```bash
cd double_st_strategy

# 과거 데이터 다운로드 (2024년 6월~11월)
../venv/bin/python prepare_backtest_data_2024_06_11.py
```

**설정 수정** (`prepare_backtest_data_2024_06_11.py` 상단):
```python
START_DATE = '2024-06-01'  # 시작 날짜
END_DATE = '2024-11-05'    # 종료 날짜
SYMBOL = 'BTCUSDT'
```

### 2. 백테스트 실행

```bash
../venv/bin/python backtest_double_st_aug_nov.py
```

**설정 수정** (`backtest_double_st_aug_nov.py` 상단):
```python
# 데이터 파일
DATA_FILE = 'backtest_data_2025/BTCUSDT_double_st_2024_06_11.csv'

# 백테스트 기간
START_DATE = '2024-08-01'  # 백테스트 시작
END_DATE = '2024-11-05'    # 백테스트 종료

# 초기 설정
INITIAL_CAPITAL = 1000      # 초기 자본 (USDT)
RISK_PER_TRADE = 0.01       # 거래당 리스크 (1%)
FEE_RATE = 0.000275         # 수수료 (0.0275%)

# 출력 파일
OUTPUT_CSV = 'backtest_results_aug_nov_2024.csv'
```

### 3. 백테스트 결과 확인

```bash
# 결과 파일 확인
cat backtest_results_aug_nov_2024.csv

# 거래 수 확인
wc -l backtest_results_aug_nov_2024.csv
```

---

## 🔴 라이브 트레이딩 실행

### 1. API 연결 테스트

```bash
cd live_trading

# API 키 테스트
../venv/bin/python test_api_ml.py
```

### 2. 라이브 실행 (실제 거래)

```bash
# 메인 프로그램 실행
../venv/bin/python double_st_strategy_live.py
```

**⚠️ 실행 전 확인사항**:
1. `config_ml.py`에 API 키 설정 완료
2. Binance Futures 계정 활성화
3. USDC 잔고 충분 (최소 $100 권장)
4. 테스트넷에서 먼저 테스트 권장

### 3. 설정 수정

`double_st_strategy_live.py` 파일 상단:
```python
# ============================================================================
# 전략 설정 (자유롭게 수정 가능)
# ============================================================================

# 심볼 설정
SYMBOL = 'BTCUSDC'

# 리스크 관리
RISK_PER_TRADE = 0.01          # 거래당 리스크 (1%)
MAX_LEVERAGE = 100              # 최대 레버리지
MIN_STOP_DISTANCE = 0.0001      # 최소 손절 거리 (0.01%)

# 손절 설정
LOOKBACK_CANDLES = 30           # 손절 계산용 과거 캔들 수
INITIAL_STOP_PCT = 0.03         # 데이터 부족시 기본 손절 (3%)

# 데이터 설정
MAX_5M_CANDLES = 500            # 5분봉 최대 보관 수
MAX_1H_CANDLES = 200            # 1시간봉 최대 보관 수
MIN_CANDLES_FOR_INDICATORS = 20 # 지표 계산 최소 캔들 수

# 파일 경로
TRADES_CSV_PATH = 'trade_results/double_st_trades.csv'
```

### 4. 백그라운드 실행

```bash
# nohup으로 백그라운드 실행
nohup ../venv/bin/python double_st_strategy_live.py > output.log 2>&1 &

# 프로세스 확인
ps aux | grep double_st_strategy_live

# 로그 실시간 확인
tail -f output.log

# 일별 로그 확인
tail -f logs/double_st_strategy_btcusdc_2025-XX-XX.log
```

### 5. 거래 내역 확인

```bash
# 거래 내역 CSV 확인
cat trade_results/double_st_trades.csv

# 최근 10개 거래
tail -10 trade_results/double_st_trades.csv

# 거래 횟수
wc -l trade_results/double_st_trades.csv
```

---

## 📈 로그 및 모니터링

### 로그 파일:

1. **일별 로그**: `logs/double_st_strategy_btcusdc_YYYY-MM-DD.log`
   - 진입/청산 기록
   - 에러/경고 메시지
   - 계좌 잔고 업데이트

2. **거래 내역**: `trade_results/double_st_trades.csv`
   - 컬럼: timestamp, type, direction, price, size, pnl, balance

### 로그 확인:

```bash
# 오늘 로그 확인
tail -f logs/double_st_strategy_btcusdc_$(date +%Y-%m-%d).log

# 진입 신호만 확인
grep "진입" logs/double_st_strategy_btcusdc_*.log

# 청산 내역만 확인
grep "청산" logs/double_st_strategy_btcusdc_*.log

# 에러 확인
grep "❌" logs/double_st_strategy_btcusdc_*.log
```

---

## ⚠️ 주의사항

### 1. 리스크 관리
- **절대 전체 자본 투입 금지**
- 초기에는 소액($100~$500)으로 테스트
- 레버리지 100배는 청산 리스크 높음
- 일일 손실 한도 설정 권장

### 2. 백테스트 vs 실전
```
백테스트 수익률 ≠ 실전 수익률

실전에서 발생하는 요소:
- 슬리피지 (가격 미끄러짐)
- 수수료 (백테스트보다 실제가 더 많을 수 있음)
- 웹소켓 지연
- API 제한
- 거래소 점검
```

### 3. 과최적화 방지
- 백테스트 데이터로 파라미터 과도한 튜닝 금지
- 테스트 기간과 다른 시장 환경에서는 성능 달라질 수 있음
- 정기적인 전략 재검증 필요

### 4. 모니터링 필수
- 하루 최소 2~3회 거래 내역 확인
- 예상치 못한 손실 발생 시 즉시 중단
- 프로그램이 정상 작동하는지 로그 확인

### 5. 긴급 중단
```bash
# 프로세스 찾기
ps aux | grep double_st_strategy_live

# 프로세스 종료 (PID 확인 후)
kill -9 [PID]

# 모든 포지션 수동 청산 필요
```

---

## 🐛 트러블슈팅

### 문제 1: "API 연결 실패"
```
원인: API 키 오류 또는 네트워크 문제
해결:
  1. config_ml.py의 API 키 재확인
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
  1. 손절 거리가 너무 작음 (< 0.01%)
  2. 1시간봉 정렬 안됨 (NEUTRAL)
  3. 5분봉 신호 안나옴

해결:
  - 로그 확인하여 플래그 상태 체크
  - 현재 1시간봉/5분봉 SuperTrend 확인
```

### 문제 4: "손실이 1%를 초과"
```
원인: 슬리피지 또는 가격 급변
해결:
  - 변동성 높은 시간대 피하기
  - RISK_PER_TRADE를 0.005 (0.5%)로 낮추기
```

### 문제 5: "메모리 부족"
```
원인: 캔들 데이터 과도하게 보관
해결:
  - MAX_5M_CANDLES = 300 (기본 500에서 축소)
  - MAX_1H_CANDLES = 100 (기본 200에서 축소)
```

---

## 📊 백테스트 vs 라이브 코드 차이점

### 백테스트 (`backtest_double_st.py`):
- 과거 데이터 기반 시뮬레이션
- DataFrame 전체 순회
- 정확한 손절/익절 가격 체결 가정
- 슬리피지 없음

### 라이브 (`double_st_strategy_live.py`):
- 실시간 웹소켓 데이터
- 비동기 처리 (asyncio)
- 실제 주문 실행 (Binance API)
- 슬리피지 발생 가능
- 레버리지 동적 설정
- 계좌 잔고 실시간 업데이트

### 공통점 (핵심 로직 동일):
✅ SuperTrend 계산 (RMA 방식)
✅ 진입 조건 (1시간봉 정렬 + 5분봉 전환)
✅ 손절가 계산 (30개 봉 최저/최고점)
✅ 익절 조건 (1:1 + ST 반전)
✅ 포지션 사이징 (리스크 1% 고정)
✅ 플래그 시스템 (buy_set → buy_ready)

---

## 🔬 전략 성능 (백테스트)

**테스트 기간**: 2024년 8월 ~ 11월 (4개월)
**초기 자본**: $1,000

### 예상 결과 (파라미터에 따라 변동):
- 총 거래 수: 100~300회
- 승률: 60~70%
- 수익률: 변동성에 따라 다름
- 최대 낙폭: 초기 자본의 10~20%

**⚠️ 주의**: 백테스트 결과는 과거 데이터 기반이며, 미래 성능을 보장하지 않습니다.

---

## 📚 추가 학습 자료

### SuperTrend 지표:
- [TradingView - SuperTrend](https://www.tradingview.com/support/solutions/43000634738-supertrend/)
- Wilder's Smoothing (RMA) 방식 ATR 계산

### 리스크 관리:
- Position Sizing (Kelly Criterion)
- Fixed Fractional Method (고정 % 리스크)

### 백테스팅:
- 시계열 분리 (Train/Test Split)
- Walk-Forward Analysis
- Monte Carlo Simulation

---

## 🆘 지원 및 문의

### 로그 분석:
```bash
# 전체 로그 검색
grep -r "진입" logs/

# 에러만 확인
grep -r "❌" logs/

# 특정 날짜 거래
grep "2025-01-15" trade_results/double_st_trades.csv
```

### 디버깅 모드:
`double_st_strategy_live.py` 에서 로깅 레벨 변경:
```python
# Line 84 근처
self.logger.setLevel(logging.DEBUG)  # INFO → DEBUG
```

---

## 📝 변경 이력

### v1.0 (2025-01-06)
- 초기 버전
- Double SuperTrend 전략 구현
- 백테스트 + 라이브 트레이딩 코드
- RMA 방식 SuperTrend 계산

---

**마지막 업데이트**: 2025-01-06
**버전**: 1.0
**작성자**: Claude Code

**⚠️ 면책 조항**: 이 소프트웨어는 교육 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해 개발자는 책임지지 않습니다. 투자는 본인 책임 하에 진행하세요.

## TODO

우리 live 코드에 주문을 넣을때 ml_strategy 와 완전 동일하게 주문을 넣었으면 좋겠어.
물론 완전동일한 로직으로 넣진않지만 binance 로 보내는 패킷은 같아야하고, 주문전송 후 바로 다음줄에 손절 STOP MARKET 도 걸게 해야지 그리고 모니터링하면서 손절가에 닿았는지만 계속 체크하고 손절주문은 스탑마켓으로 알아서 나가게.
아래는 ml_strategy 의 숏주문의 일부야.

   async def enter_short(self, features: Dict):
        """SHORT 진입"""
        try:
            # 백테스트와 동일하게 5분봉 Close 가격 사용 (Ticker 대신)
            entry_price = self.klines_5m[-1]['close']

            # ========== NEW MODEL: Fixed percentage stop/target ==========
            # 손절가: 진입가 + 0.25%
            stop_price = entry_price * (1 + 0.0025)  # 0.25% stop loss (for SHORT)

            # 익절가: 진입가 - 0.45%
            target_price = entry_price * (1 - 0.0045)  # 0.45% take profit (for SHORT)

            # 거리 계산 (포지션 크기 계산용)
            distance = abs(entry_price - stop_price)

            # 포지션 크기 및 레버리지 계산
            position_size, leverage = self.calculate_position_size(entry_price, stop_price)

            if position_size == 0:
                return

            # Isolated 마진 모드 설정
            try:
                self.client.futures_change_margin_type(symbol=Config.SYMBOL, marginType='ISOLATED')
                self.get_logger().info(f"Margin mode set to ISOLATED")
            except Exception as e:
                # 이미 ISOLATED 모드인 경우 에러 무시
                if 'No need to change margin type' not in str(e):
                    self.get_logger().warning(f"Margin type change: {e}")
                
            # 레버리지 설정
            try:
                self.client.futures_change_leverage(symbol=Config.SYMBOL, leverage=leverage)
                self.get_logger().info(f"Leverage set to {leverage}x")
            except Exception as e:
                self.get_logger().error(f"Failed to set leverage: {e}")
                return

            # 주문 수량 계산
            quantity = position_size / entry_price
            quantity = round(quantity, 3)

            if quantity < 0.001:
                self.get_logger().warning(f"Quantity too small: {quantity}")
                return

            # 실제 바이낸스 주문 실행
            order = self.client.futures_create_order(
                symbol=Config.SYMBOL,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

            # 포지션 저장
            self.position = {
                'side': 'SHORT',
                'entry_price': entry_price,
                'entry_time': datetime.now(pytz.UTC),
                'stop_price': stop_price,
                'target_price': target_price,
                'quantity': quantity,
                'leverage': leverage,
                'order_id': order['orderId']
            }

            # 손절 주문 설정
            await self.set_stop_loss_order()


            entry_msg = f"📉 SHORT 진입: {quantity} BTC @ ${entry_price:.2f} (Lev: {leverage}x, Stop: ${stop_price:.2f}, Target: ${target_price:.2f})"
            self.get_logger().info(entry_msg)
            print(entry_msg)

        except Exception as e:
            self.get_logger().error(f"Error entering SHORT: {e}")



이건 손절 주문 함수

async def set_stop_loss_order(self):
        """손절 주문 설정"""
        if not self.position:
            return

        stop_price = round(self.position['stop_price'], 1)

        try:
            if self.position['side'] == 'LONG':
                order = self.client.futures_create_order(
                    symbol=Config.SYMBOL,
                    side=SIDE_SELL,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )
            else:
                order = self.client.futures_create_order(
                    symbol=Config.SYMBOL,
                    side=SIDE_BUY,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )

            self.get_logger().info(f"🛑 Stop loss order placed at ${stop_price:.1f}")

        except Exception as e:
            self.get_logger().error(f"Failed to set stop loss: {e}")


이건 모니터링하다가 가격데이터보고 손절이 나갔는지 확인하는 함수
   async def monitor_positions(self):
        """바이낸스 포지션 상태 주기적 확인 (5초마다)"""
        while True:
            try:
                await asyncio.sleep(5)

                if self.position is None:
                    continue

                # 바이낸스 실제 포지션 확인
                positions = self.client.futures_position_information(symbol=Config.SYMBOL)

                has_position = False
                actual_pnl = 0

                for pos in positions:
                    position_amt = float(pos['positionAmt'])
                    if position_amt != 0:
                        has_position = True
                        actual_pnl = float(pos['unRealizedProfit'])
                        break

                # 포지션이 사라졌는데 self.position이 있으면 = 자동 청산됨
                if not has_position and self.position is not None:
                    # 손절인지 익절인지 판단
                    if actual_pnl < 0:
                        reason = "STOP_LOSS"
                        exit_price = self.position['stop_price']  # 손절가로 추정
                    else:
                        reason = "TAKE_PROFIT"
                        exit_price = self.position['target_price']  # 익절가로 추정

                    self.get_logger().info(f"💰 {self.position['side']} {reason}, PnL: ${actual_pnl:.2f} (바이낸스 자동 청산)")

                    # 자본 동기화 먼저
                    await self.sync_capital()

                    # 거래 기록 저장
                    await self.save_trade_record(reason, exit_price)

                    # 모든 대기 주문 취소
                    await self.cancel_pending_orders()

                    # 포지션 초기화
                    self.position = None

            except Exception as e:
                self.get_logger().error(f"Position monitoring error: {e}")

    async def check_exit(self):
        """청산 모니터링 (로그만 남김, 실제 주문은 바이낸스 STOP/LIMIT이 처리)"""
        if self.position is None:
            return

        if len(self.klines_5m) == 0:
            return

        try:
            # 5분봉의 최신 high/low 사용
            current_low = self.klines_5m[-1]['low']
            current_high = self.klines_5m[-1]['high']

            # 손절/익절 가격 도달 여부만 확인하고 로그만 남김
            if self.position['side'] == 'LONG':
                # 손절 가격 도달 감지 (Low 기준)
                if current_low <= self.position['stop_price']:
                    self.get_logger().info(f"🛑 LONG 손절 가격 도달: Low ${current_low:.2f} (Stop: ${self.position['stop_price']:.2f})")

                # 익절 가격 도달 감지 (High 기준)
                elif current_high >= self.position['target_price']:
                    self.get_logger().info(f"🎯 LONG 익절 가격 도달: High ${current_high:.2f} (Target: ${self.position['target_price']:.2f})")

            elif self.position['side'] == 'SHORT':
                # 손절 가격 도달 감지 (High 기준)
                if current_high >= self.position['stop_price']:
                    self.get_logger().info(f"🛑 SHORT 손절 가격 도달: High ${current_high:.2f} (Stop: ${self.position['stop_price']:.2f})")

                # 익절 가격 도달 감지 (Low 기준)
                elif current_low <= self.position['target_price']:
                    self.get_logger().info(f"🎯 SHORT 익절 가격 도달: Low ${current_low:.2f} (Target: ${self.position['target_price']:.2f})")

        except Exception as e:
            self.get_logger().error(f"Error checking exit: {e}")



이건 손절이나 익절나갔으면 미리나가있는 STOP LOSS 주문 취소하는 함수
    async def cancel_pending_orders(self):
        """대기 주문 취소"""
        try:
            self.client.futures_cancel_all_open_orders(symbol=Config.SYMBOL)
        except Exception as e:
            self.get_logger().warning(f"Failed to cancel orders: {e}")


위 함수들을 거의 완전 그대로 쓸수있으면 쓰고 비지니스로직이 머신러닝에 맞춰져있는부분만 빼고 가져다써

특히 이런건 
                order = self.client.futures_create_order(
                    symbol=Config.SYMBOL,
                    side=SIDE_BUY,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )

                그대로 써. type 같은거 바꾸지말고.

결국 주문의 흐름은 -> 신호 발생 -> 포지션 진입 + 손절 STOP_MARKET 미리 걸어두기 -> 5분마다 들어오는 가격데이터로 포지션 체크 -> 손절이나 익절나가면 대기주문 취소.

이걸 제대로 구현해야해.
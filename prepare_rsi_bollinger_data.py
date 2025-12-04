"""
RSI + Bollinger Band (RB) Strategy - 백테스트 데이터 준비 스크립트

이 스크립트는 다음 작업을 수행합니다:
1. 바이낸스에서 5분봉 데이터 다운로드
2. RSI(6) 지표 계산 (TradingView 방식)
3. Bollinger Band(200, 2) 지표 계산 (TradingView 방식)
4. 크로스오버/크로스언더 신호 계산
5. STOP 주문 진입 로직 시뮬레이션
6. 최종 백테스트용 CSV 생성

전략 조건 (TradingView Pine Script 기반):
- RSI(6), 과매수/과매도 기준: 50
- BB(200, 2): 종가 기준
- LONG 신호: RSI가 50 크로스오버 + 가격이 BB 하단 크로스오버
- SHORT 신호: RSI가 50 크로스언더 + 가격이 BB 상단 크로스언더
- LONG 진입: 신호 발생 후 가격이 BB lower까지 리테스트 시 (STOP 주문)
- SHORT 진입: 신호 발생 후 가격이 BB upper까지 리테스트 시 (STOP 주문)
- 신호 조건이 불충족되면 대기 주문 취소

사용법:
    python prepare_rsi_bollinger_data.py
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os

# ================================================================================
# CONFIG: 모든 설정 값 (자유롭게 수정 가능)
# ================================================================================

# 다운로드 기간 설정
START_DATE = '2022-01-01'  # 시작 날짜
END_DATE = '2025-11-30'    # 종료 날짜

# 심볼 설정
SYMBOL = 'BTCUSDT'

# 타임프레임 설정 (5분봉만 사용)
TIMEFRAME = '5m'

# 디렉토리 설정
OUTPUT_DIR = 'historical_data/'       # 원시 데이터 저장 경로
BACKTEST_DATA_DIR = 'backtest_data/'  # 백테스트 데이터 저장 경로

# 파일명 설정
RAW_FILENAME = f"{SYMBOL}_{TIMEFRAME}_raw.csv"
FINAL_FILENAME = f"{SYMBOL}_rb_strategy.csv"

# API 설정
API_LIMIT = 1500              # 바이낸스 API 한 번 요청 시 최대 캔들 수
API_SLEEP = 0.1               # API 요청 간격 (초)
API_RETRY_SLEEP = 5           # API 오류 시 재시도 대기 시간 (초)

# 진행 상황 출력 설정
PROGRESS_UPDATE_INTERVAL = 15000  # 진행 상황 업데이트 간격 (캔들 수)

# RSI 설정
RSI_LENGTH = 10            # RSI 기간
RSI_OVERBOUGHT = 50       # RSI 과매수 기준 (크로스언더 체크용)
RSI_OVERSOLD = 50         # RSI 과매도 기준 (크로스오버 체크용)

# Bollinger Band 설정
BB_LENGTH = 200           # BB 기간
BB_MULT = 2               # BB 표준편차 배수

# ================================================================================
# 출력 메시지 설정
# ================================================================================
SECTION_DIVIDER = "=" * 80
TITLE = "RB Strategy - 백테스트 데이터 준비"

# ================================================================================
# 1. RSI 계산 함수 (TradingView 방식)
# ================================================================================

def calculate_rma(series, length):
    """
    RMA (Relative Moving Average) 계산 - TradingView/Wilder's Smoothing 방식

    RMA는 EMA와 유사하지만 alpha = 1/length를 사용
    첫 번째 값은 SMA로 시작하고, 이후 RMA 공식 적용:
    RMA = (prev_rma * (length - 1) + current_value) / length

    Parameters:
    - series: 계산할 시리즈 (pandas Series)
    - length: RMA 기간

    Returns:
    - RMA 시리즈
    """
    alpha = 1.0 / length

    # 첫 번째 유효한 RMA 값을 SMA로 계산
    rma = series.copy()
    rma[:] = np.nan

    # 첫 length개의 평균을 시작점으로 사용
    first_valid_idx = length - 1
    if len(series) > first_valid_idx:
        rma.iloc[first_valid_idx] = series.iloc[:length].mean()

        # 이후 RMA 계산 (Wilder's smoothing)
        for i in range(first_valid_idx + 1, len(series)):
            rma.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * rma.iloc[i - 1]

    return rma


def calculate_rsi(df, length=6, source='Close'):
    """
    RSI (Relative Strength Index) 계산 - TradingView 방식

    TradingView RSI는 RMA(Wilder's Smoothing)를 사용:
    1. 가격 변화량 계산 (change = close - close[1])
    2. 상승분(gain)과 하락분(loss) 분리
    3. RMA로 평균 상승분과 평균 하락분 계산
    4. RS = avg_gain / avg_loss
    5. RSI = 100 - (100 / (1 + RS))

    Parameters:
    - df: OHLC 데이터프레임
    - length: RSI 기간 (기본 6)
    - source: RSI 계산에 사용할 가격 소스 (기본 'Close')

    Returns:
    - df with RSI column added
    """
    df = df.copy()

    # 가격 변화량 계산
    change = df[source].diff()

    # 상승분 (gain): 양수 변화만
    gain = change.where(change > 0, 0.0)

    # 하락분 (loss): 음수 변화의 절대값
    loss = (-change).where(change < 0, 0.0)

    # RMA로 평균 계산 (TradingView 방식)
    avg_gain = calculate_rma(gain, length)
    avg_loss = calculate_rma(loss, length)

    # RS 계산 (0으로 나누기 방지)
    rs = avg_gain / avg_loss.replace(0, np.nan)

    # RSI 계산
    rsi = 100 - (100 / (1 + rs))

    # 특수 케이스 처리
    # avg_loss가 0이면 RSI = 100 (모두 상승)
    rsi = rsi.where(avg_loss != 0, 100.0)
    # avg_gain이 0이면 RSI = 0 (모두 하락)
    rsi = rsi.where(avg_gain != 0, 0.0)

    df['rsi'] = rsi

    return df


# ================================================================================
# 2. Bollinger Band 계산 함수
# ================================================================================

def calculate_bollinger_band(df, length, std_dev, source='Close'):
    """
    Bollinger Band 계산 (TradingView 표준)

    Parameters:
    - df: OHLC 데이터프레임
    - length: SMA 기간
    - std_dev: 표준편차 배수
    - source: BB 계산에 사용할 가격 소스 (기본 'Close')

    Returns:
    - df with Bollinger Band columns added
    """
    df = df.copy()

    # SMA 계산
    sma = df[source].rolling(window=length).mean()

    # 표준편차 계산 (TradingView 표준: population std, ddof=0)
    std = df[source].rolling(window=length).std(ddof=0)

    # Upper/Lower Band 계산
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)

    df['bb_basis'] = sma
    df['bb_upper'] = upper
    df['bb_lower'] = lower

    return df


# ================================================================================
# 3. 크로스오버/크로스언더 계산 함수
# ================================================================================

def calculate_crossovers(df):
    """
    RSI 및 가격 크로스오버/크로스언더 신호 계산

    Pine Script 조건:
    - LONG: crossover(vrsi, RSIoverSold) and crossover(source, BBlower)
    - SHORT: crossunder(vrsi, RSIoverBought) and crossunder(source, BBupper)

    crossover(a, b): a[1] < b[1] and a > b (a가 b를 아래에서 위로 돌파)
    crossunder(a, b): a[1] > b[1] and a < b (a가 b를 위에서 아래로 돌파)
    """
    df = df.copy()

    # RSI 크로스오버/크로스언더 (기준선 50)
    rsi_prev = df['rsi'].shift(1)

    # RSI crossover 50: 이전 RSI < 50 and 현재 RSI > 50
    df['rsi_crossover_50'] = (rsi_prev < RSI_OVERSOLD) & (df['rsi'] > RSI_OVERSOLD)

    # RSI crossunder 50: 이전 RSI > 50 and 현재 RSI < 50
    df['rsi_crossunder_50'] = (rsi_prev > RSI_OVERBOUGHT) & (df['rsi'] < RSI_OVERBOUGHT)

    # 가격 크로스오버/크로스언더 (BB 밴드)
    close_prev = df['Close'].shift(1)
    bb_lower_prev = df['bb_lower'].shift(1)
    bb_upper_prev = df['bb_upper'].shift(1)

    # Close crossover BB lower: 이전 Close < BB lower and 현재 Close > BB lower
    df['price_crossover_bb_lower'] = (close_prev < bb_lower_prev) & (df['Close'] > df['bb_lower'])

    # Close crossunder BB upper: 이전 Close > BB upper and 현재 Close < BB upper
    df['price_crossunder_bb_upper'] = (close_prev > bb_upper_prev) & (df['Close'] < df['bb_upper'])

    # 조건 신호 (대기 주문 생성 조건)
    # LONG 조건: RSI crossover 50 AND Close crossover BB lower
    df['long_condition'] = df['rsi_crossover_50'] & df['price_crossover_bb_lower']

    # SHORT 조건: RSI crossunder 50 AND Close crossunder BB upper
    df['short_condition'] = df['rsi_crossunder_50'] & df['price_crossunder_bb_upper']

    return df


def simulate_stop_orders(df):
    """
    STOP 주문 진입 시뮬레이션

    Pine Script 로직:
    - strategy.entry("RSI_BB_L", strategy.long, stop=BBlower, ...)
    - 조건 충족 시 BB lower에 STOP BUY 대기 주문 설정
    - 가격이 BB lower까지 내려오면 (리테스트) 진입
    - 조건 불충족 시 대기 주문 취소 (strategy.cancel)

    STOP 주문 특성 (LONG):
    - stop=BBlower: 가격이 BBlower까지 내려오면 BUY
    - 즉, Low <= BBlower 이면 진입

    STOP 주문 특성 (SHORT):
    - stop=BBupper: 가격이 BBupper까지 올라오면 SELL
    - 즉, High >= BBupper 이면 진입
    """
    df = df.copy()

    # 진입 신호 초기화
    df['long_signal'] = False
    df['short_signal'] = False
    df['entry_price'] = np.nan

    # 대기 주문 상태
    pending_long = False
    pending_short = False
    pending_long_stop = None  # BB lower 값 (STOP 가격)
    pending_short_stop = None  # BB upper 값 (STOP 가격)

    for idx in range(len(df)):
        row = df.iloc[idx]

        # 현재 봉의 조건 확인
        long_cond = row['long_condition']
        short_cond = row['short_condition']

        # === LONG 처리 ===
        if long_cond:
            # 새로운 LONG 조건 발생 → STOP 주문 설정
            pending_long = True
            pending_long_stop = row['bb_lower']
        elif pending_long and not long_cond:
            # 조건 불충족 → 대기 주문 취소
            pending_long = False
            pending_long_stop = None

        # LONG STOP 주문 체결 확인 (가격이 BB lower까지 내려옴)
        if pending_long and pending_long_stop is not None:
            if row['Low'] <= pending_long_stop:
                # STOP 주문 체결 → 진입
                df.at[df.index[idx], 'long_signal'] = True
                df.at[df.index[idx], 'entry_price'] = pending_long_stop
                # 대기 주문 초기화
                pending_long = False
                pending_long_stop = None

        # === SHORT 처리 ===
        if short_cond:
            # 새로운 SHORT 조건 발생 → STOP 주문 설정
            pending_short = True
            pending_short_stop = row['bb_upper']
        elif pending_short and not short_cond:
            # 조건 불충족 → 대기 주문 취소
            pending_short = False
            pending_short_stop = None

        # SHORT STOP 주문 체결 확인 (가격이 BB upper까지 올라옴)
        if pending_short and pending_short_stop is not None:
            if row['High'] >= pending_short_stop:
                # STOP 주문 체결 → 진입
                df.at[df.index[idx], 'short_signal'] = True
                df.at[df.index[idx], 'entry_price'] = pending_short_stop
                # 대기 주문 초기화
                pending_short = False
                pending_short_stop = None

    return df


def calculate_all_indicators(df):
    """
    모든 지표 계산
    """
    print("   지표 계산 중...")

    # RSI 계산
    df = calculate_rsi(df, length=RSI_LENGTH, source='Close')
    print(f"      - RSI({RSI_LENGTH}) 완료")

    # Bollinger Band 계산
    df = calculate_bollinger_band(df, length=BB_LENGTH, std_dev=BB_MULT, source='Close')
    print(f"      - BB({BB_LENGTH}, {BB_MULT}) 완료")

    # 크로스오버/크로스언더 계산
    df = calculate_crossovers(df)
    print(f"      - 크로스오버/크로스언더 조건 완료")

    # STOP 주문 시뮬레이션 (리테스트 진입)
    df = simulate_stop_orders(df)
    print(f"      - STOP 주문 진입 시뮬레이션 완료")

    return df


# ================================================================================
# 4. 데이터 다운로드 함수
# ================================================================================

def download_binance_klines(symbol, interval, start_date, end_date):
    """바이낸스 선물 캔들 데이터 다운로드"""
    base_url = 'https://fapi.binance.com/fapi/v1/klines'

    # 날짜를 밀리초로 변환
    start_ms = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

    all_klines = []
    current_start = start_ms

    print(f"\n{SECTION_DIVIDER}")
    print(f"📥 다운로드 중: {symbol} {interval}")
    print(f"   기간: {start_date} ~ {end_date}")
    print(SECTION_DIVIDER)

    while current_start < end_ms:
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': current_start,
            'endTime': end_ms,
            'limit': API_LIMIT
        }

        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            klines = response.json()

            if not klines:
                break

            all_klines.extend(klines)
            current_start = klines[-1][0] + 1

            # 진행 상황 출력
            if len(all_klines) % PROGRESS_UPDATE_INTERVAL == 0:
                current_date = datetime.fromtimestamp(klines[-1][0] / 1000).strftime('%Y-%m-%d')
                print(f"   진행 중... {current_date} ({len(all_klines):,} candles)")

            time.sleep(API_SLEEP)

        except requests.exceptions.RequestException as e:
            print(f"   ⚠️ API Error: {e}")
            print("   5초 후 재시도...")
            time.sleep(API_RETRY_SLEEP)
            continue

    if not all_klines:
        print("   ❌ 다운로드 실패: 데이터 없음")
        return None

    # DataFrame 변환
    df = pd.DataFrame(all_klines, columns=[
        'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
        'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base',
        'Taker_buy_quote', 'Ignore'
    ])

    # 타입 변환
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    df[numeric_cols] = df[numeric_cols].astype(float)

    # 필요한 컬럼만 선택
    df = df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']]

    print(f"   ✅ 다운로드 완료: {len(df):,} candles")

    return df


# ================================================================================
# 5. 데이터 저장 함수
# ================================================================================

def save_raw_data(df, output_dir, filename):
    """다운로드한 원시 데이터를 CSV로 저장"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"   💾 원시 데이터 저장: {filepath}")
    return filepath


def prepare_final_columns(df):
    """
    최종 CSV에 필요한 컬럼만 선택 및 정렬
    """
    columns_to_keep = [
        # 기본 정보
        'timestamp',

        # 5분봉 OHLCV
        'Open', 'High', 'Low', 'Close', 'Volume',

        # RSI
        'rsi',

        # Bollinger Band
        'bb_basis',
        'bb_upper',
        'bb_lower',

        # 크로스오버/크로스언더 신호
        'rsi_crossover_50',
        'rsi_crossunder_50',
        'price_crossover_bb_lower',
        'price_crossunder_bb_upper',

        # 조건 신호 (대기 주문 생성 조건)
        'long_condition',
        'short_condition',

        # 진입 신호 (STOP 주문 체결)
        'long_signal',
        'short_signal',
        'entry_price',
    ]

    # 존재하는 컬럼만 선택
    available_columns = [col for col in columns_to_keep if col in df.columns]

    return df[available_columns].copy()


# ================================================================================
# 6. 메인 실행 함수
# ================================================================================

def main():
    """메인 실행 함수"""
    print("\n" + SECTION_DIVIDER)
    print(f"🚀 {TITLE}")
    print(SECTION_DIVIDER)

    # 출력 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(BACKTEST_DATA_DIR, exist_ok=True)

    # 1. 데이터 다운로드
    print("\n[STEP 1/3] 5분봉 데이터 다운로드")
    df = download_binance_klines(SYMBOL, TIMEFRAME, START_DATE, END_DATE)

    if df is None:
        print("   ❌ 데이터 다운로드 실패")
        return

    # 원시 데이터 저장
    save_raw_data(df, OUTPUT_DIR, RAW_FILENAME)

    # 2. 지표 계산
    print(f"\n[STEP 2/3] 지표 계산")
    df = calculate_all_indicators(df)

    # 3. 최종 컬럼 정리 및 저장 (모든 봉 저장 - 백테스트에 필요)
    print("\n[STEP 3/3] 최종 백테스트 데이터 생성")
    df_final = prepare_final_columns(df)

    # NaN 제거 (초기 구간 - BB 200 계산으로 인한)
    # bb_basis가 NaN인 행만 제거 (지표 계산 초기 구간)
    initial_rows = len(df_final)
    df_final = df_final.dropna(subset=['bb_basis', 'rsi'])
    dropped_rows = initial_rows - len(df_final)

    if dropped_rows > 0:
        print(f"   ⚠️ NaN 제거: {dropped_rows} rows (지표 계산 초기 구간)")

    # 모든 봉 저장 (신호 필터링 없음 - 백테스트에서 모든 봉의 BB/RSI 값 필요)
    print(f"   📊 모든 봉 데이터 저장 (신호 필터링 없음)")

    # 최종 파일 저장
    output_path = os.path.join(BACKTEST_DATA_DIR, FINAL_FILENAME)
    df_final.to_csv(output_path, index=False)

    print(f"   💾 최종 백테스트 데이터 저장: {output_path}")
    print(f"   📊 데이터 크기: {len(df_final):,} rows x {len(df_final.columns)} columns")

    # 데이터 요약 출력
    print("\n" + SECTION_DIVIDER)
    print("📋 최종 데이터 요약")
    print(SECTION_DIVIDER)
    print(f"기간: {df_final['timestamp'].min()} ~ {df_final['timestamp'].max()}")
    print(f"행 수: {len(df_final):,}")
    print(f"컬럼 수: {len(df_final.columns)}")
    print(f"\n컬럼 목록:")
    for i, col in enumerate(df_final.columns, 1):
        print(f"  {i:2d}. {col}")

    # RSI 통계 출력
    print("\n" + SECTION_DIVIDER)
    print("📊 RSI 통계")
    print(SECTION_DIVIDER)
    print(f"   최소값: {df_final['rsi'].min():.2f}")
    print(f"   최대값: {df_final['rsi'].max():.2f}")
    print(f"   평균값: {df_final['rsi'].mean():.2f}")
    print(f"   중앙값: {df_final['rsi'].median():.2f}")

    # Bollinger Band 통계 출력
    print("\n" + SECTION_DIVIDER)
    print("📊 Bollinger Band 통계")
    print(SECTION_DIVIDER)
    print(f"   BB Basis 평균: {df_final['bb_basis'].mean():.2f}")
    print(f"   BB Upper 평균: {df_final['bb_upper'].mean():.2f}")
    print(f"   BB Lower 평균: {df_final['bb_lower'].mean():.2f}")

    # 신호 통계 출력
    print("\n" + SECTION_DIVIDER)
    print("📊 신호 통계")
    print(SECTION_DIVIDER)
    print(f"   RSI Crossover 50: {df_final['rsi_crossover_50'].sum()}회")
    print(f"   RSI Crossunder 50: {df_final['rsi_crossunder_50'].sum()}회")
    print(f"   Price Crossover BB Lower: {df_final['price_crossover_bb_lower'].sum()}회")
    print(f"   Price Crossunder BB Upper: {df_final['price_crossunder_bb_upper'].sum()}회")
    print(f"   LONG 조건 (대기 주문): {df_final['long_condition'].sum()}회")
    print(f"   SHORT 조건 (대기 주문): {df_final['short_condition'].sum()}회")
    print(f"   LONG 진입 (리테스트): {df_final['long_signal'].sum()}회")
    print(f"   SHORT 진입 (리테스트): {df_final['short_signal'].sum()}회")

    # 샘플 데이터 출력
    print("\n" + SECTION_DIVIDER)
    print("🔍 샘플 데이터 (처음 5행)")
    print(SECTION_DIVIDER)
    print(df_final.head().to_string())

    print(f"\n✅ 백테스트 데이터 준비 완료!")
    print(f"   파일: {output_path}")
    print(f"   기간: {START_DATE} ~ {END_DATE}")


if __name__ == "__main__":
    main()

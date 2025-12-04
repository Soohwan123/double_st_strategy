"""
RSI Divergence Strategy - 백테스트 데이터 준비 스크립트

이 스크립트는 다음 작업을 수행합니다:
1. 바이낸스에서 5분봉 데이터 다운로드
2. RSI(14) 지표 계산 (TradingView 방식)
3. RSI 피벗 감지 (Pivot High/Low)
4. 다이버전스 감지 (Regular Bullish/Bearish)
5. 더블 다이버전스 감지 (3-Pivot Sliding 방식)
6. 최종 백테스트용 CSV 생성

다이버전스 로직:
- Regular Bullish: 가격 Lower Low + RSI Higher Low (과매도 필터: RSI < 30)
- Regular Bearish: 가격 Higher High + RSI Lower High (과매수 필터: RSI > 70)
- Double Divergence: 현재(2) vs 0번 피벗 다이버전스 + 1번 vs 0번 피벗 다이버전스

사용법:
    python prepare_rsi_data.py
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
START_DATE = '2022-1-01'  # 시작 날짜
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
FINAL_FILENAME = f"{SYMBOL}_rsi_2025_07_11.csv"

# API 설정
API_LIMIT = 1500              # 바이낸스 API 한 번 요청 시 최대 캔들 수
API_SLEEP = 0.1               # API 요청 간격 (초)
API_RETRY_SLEEP = 5           # API 오류 시 재시도 대기 시간 (초)

# 진행 상황 출력 설정
PROGRESS_UPDATE_INTERVAL = 15000  # 진행 상황 업데이트 간격 (캔들 수)

# RSI 설정
RSI_LENGTH = 14  # RSI 기간

# 피벗 설정 (TradingView Pine Script와 동일)
PIVOT_LOOKBACK_LEFT = 5   # lbL: 피벗 좌측 확인 봉 수
PIVOT_LOOKBACK_RIGHT = 3  # lbR: 피벗 우측 확인 봉 수
RANGE_UPPER = 120         # 이전 피벗 최대 거리 (봉)
RANGE_LOWER = 5           # 이전 피벗 최소 거리 (봉)

# RSI 과매수/과매도 기준
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# ================================================================================
# 출력 메시지 설정
# ================================================================================
SECTION_DIVIDER = "=" * 80
TITLE = "RSI Strategy - 백테스트 데이터 준비"

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


def calculate_rsi(df, length=14, source='Close'):
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
    - length: RSI 기간 (기본 14)
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


def calculate_all_indicators(df):
    """
    모든 RSI 지표 계산
    """
    print("   RSI 지표 계산 중...")

    df = calculate_rsi(df, length=RSI_LENGTH, source='Close')
    print(f"      - RSI({RSI_LENGTH}) 완료")

    return df


# ================================================================================
# 2. 피벗 및 다이버전스 계산 함수
# ================================================================================

def detect_pivot_low(rsi_series, idx, lbL, lbR):
    """
    RSI Pivot Low 감지
    현재 위치(idx - lbR)가 좌측 lbL개, 우측 lbR개보다 낮은지 확인

    Parameters:
    - rsi_series: RSI 시리즈
    - idx: 현재 봉 인덱스 (피벗은 idx - lbR 위치에서 확인)
    - lbL: 좌측 확인 봉 수
    - lbR: 우측 확인 봉 수

    Returns:
    - True if pivot low found, False otherwise
    """
    pivot_idx = idx - lbR

    # 범위 체크
    if pivot_idx < lbL or pivot_idx >= len(rsi_series) - lbR:
        return False

    pivot_value = rsi_series.iloc[pivot_idx]

    # 좌측 lbL개 봉보다 낮아야 함
    for i in range(1, lbL + 1):
        if rsi_series.iloc[pivot_idx - i] <= pivot_value:
            return False

    # 우측 lbR개 봉보다 낮아야 함
    for i in range(1, lbR + 1):
        if rsi_series.iloc[pivot_idx + i] <= pivot_value:
            return False

    return True


def detect_pivot_high(rsi_series, idx, lbL, lbR):
    """
    RSI Pivot High 감지
    현재 위치(idx - lbR)가 좌측 lbL개, 우측 lbR개보다 높은지 확인

    Parameters:
    - rsi_series: RSI 시리즈
    - idx: 현재 봉 인덱스 (피벗은 idx - lbR 위치에서 확인)
    - lbL: 좌측 확인 봉 수
    - lbR: 우측 확인 봉 수

    Returns:
    - True if pivot high found, False otherwise
    """
    pivot_idx = idx - lbR

    # 범위 체크
    if pivot_idx < lbL or pivot_idx >= len(rsi_series) - lbR:
        return False

    pivot_value = rsi_series.iloc[pivot_idx]

    # 좌측 lbL개 봉보다 높아야 함
    for i in range(1, lbL + 1):
        if rsi_series.iloc[pivot_idx - i] >= pivot_value:
            return False

    # 우측 lbR개 봉보다 높아야 함
    for i in range(1, lbR + 1):
        if rsi_series.iloc[pivot_idx + i] >= pivot_value:
            return False

    return True


def calculate_divergence(df):
    """
    RSI 다이버전스 및 더블 다이버전스 계산

    TradingView Pine Script 로직을 Python으로 구현:
    - 3-Pivot Sliding Window 방식
    - Regular Divergence만 감지 (Hidden 제외)
    - 더블 다이버전스: curr(2) vs prev2(0) 다이버전스 + prev1(1) vs prev2(0) 다이버전스

    Returns:
    - df with divergence columns added:
      - pivot_low: RSI 저점 피벗 여부
      - pivot_high: RSI 고점 피벗 여부
      - bull_div: Bullish Divergence 여부
      - bear_div: Bearish Divergence 여부
      - double_bull_div: Double Bullish Divergence 여부
      - double_bear_div: Double Bearish Divergence 여부
    """
    print("   RSI 다이버전스 계산 중...")

    df = df.copy()
    n = len(df)

    # 결과 컬럼 초기화
    df['pivot_low'] = False
    df['pivot_high'] = False
    df['bull_div'] = False
    df['bear_div'] = False
    df['double_bull_div'] = False
    df['double_bear_div'] = False

    # 피벗 저장 배열 (최근 3개만 유지)
    # 각 요소: (bar_index, rsi_value, price_value)
    pivot_lows = []   # (idx, rsi, low_price)
    pivot_highs = []  # (idx, rsi, high_price)

    lbL = PIVOT_LOOKBACK_LEFT
    lbR = PIVOT_LOOKBACK_RIGHT

    rsi_series = df['rsi']
    low_series = df['Low']
    high_series = df['High']

    for idx in range(lbL + lbR, n):
        pivot_idx = idx - lbR  # 실제 피벗 위치

        # ===== Pivot Low 감지 =====
        if detect_pivot_low(rsi_series, idx, lbL, lbR):
            df.loc[df.index[pivot_idx], 'pivot_low'] = True

            curr_rsi = rsi_series.iloc[pivot_idx]
            curr_price = low_series.iloc[pivot_idx]
            curr_bar = pivot_idx

            # Pine Script와 동일하게: 먼저 배열에 추가
            pivot_lows.append((curr_bar, curr_rsi, curr_price))
            if len(pivot_lows) > 3:
                pivot_lows.pop(0)  # 가장 오래된 것 제거

            # 추가 후 다이버전스 체크 (Pine Script: sz = array.size() 후 인덱싱)
            sz = len(pivot_lows)

            bull_cond1 = False  # curr vs prev1 (sz-2)
            bull_cond2 = False  # curr vs prev2 (sz-3)

            # curr vs prev1 (sz-2) - 바로 이전 피벗
            if sz >= 2:
                prev1_bar, prev1_rsi, prev1_price = pivot_lows[sz - 2]
                bars_diff = curr_bar - prev1_bar

                if RANGE_LOWER <= bars_diff <= RANGE_UPPER:
                    oversold_ok = (curr_rsi < RSI_OVERSOLD or prev1_rsi < RSI_OVERSOLD)
                    # Regular Bullish: 가격 Lower Low + RSI Higher Low
                    if oversold_ok and (prev1_price > curr_price) and (prev1_rsi < curr_rsi):
                        bull_cond1 = True
                        df.loc[df.index[pivot_idx], 'bull_div'] = True

            # curr vs prev2 (sz-3) - 2개 전 피벗
            if sz >= 3:
                prev2_bar, prev2_rsi, prev2_price = pivot_lows[sz - 3]
                bars_diff = curr_bar - prev2_bar

                if RANGE_LOWER <= bars_diff <= RANGE_UPPER:
                    oversold_ok = (curr_rsi < RSI_OVERSOLD or prev2_rsi < RSI_OVERSOLD)
                    if oversold_ok and (prev2_price > curr_price) and (prev2_rsi < curr_rsi):
                        bull_cond2 = True
                        df.loc[df.index[pivot_idx], 'bull_div'] = True

            # 더블 다이버전스: curr vs prev2 다이버전스 + prev1 vs prev2 다이버전스
            # prev1(sz-2)과 prev2(sz-3) 사이의 다이버전스 체크
            if bull_cond2 and sz >= 3:
                prev1_bar, prev1_rsi, prev1_price = pivot_lows[sz - 2]
                prev2_bar, prev2_rsi, prev2_price = pivot_lows[sz - 3]
                bars_diff_1_2 = prev1_bar - prev2_bar

                if RANGE_LOWER <= bars_diff_1_2 <= RANGE_UPPER:
                    oversold_ok_1_2 = (prev1_rsi < RSI_OVERSOLD or prev2_rsi < RSI_OVERSOLD)
                    if oversold_ok_1_2 and (prev2_price > prev1_price) and (prev2_rsi < prev1_rsi):
                        # prev1 vs prev2도 다이버전스 → 더블 다이버전스
                        df.loc[df.index[pivot_idx], 'double_bull_div'] = True

        # ===== Pivot High 감지 =====
        if detect_pivot_high(rsi_series, idx, lbL, lbR):
            df.loc[df.index[pivot_idx], 'pivot_high'] = True

            curr_rsi = rsi_series.iloc[pivot_idx]
            curr_price = high_series.iloc[pivot_idx]
            curr_bar = pivot_idx

            # Pine Script와 동일하게: 먼저 배열에 추가
            pivot_highs.append((curr_bar, curr_rsi, curr_price))
            if len(pivot_highs) > 3:
                pivot_highs.pop(0)  # 가장 오래된 것 제거

            # 추가 후 다이버전스 체크 (Pine Script: sz = array.size() 후 인덱싱)
            sz = len(pivot_highs)

            bear_cond1 = False  # curr vs prev1 (sz-2)
            bear_cond2 = False  # curr vs prev2 (sz-3)

            # curr vs prev1 (sz-2) - 바로 이전 피벗
            if sz >= 2:
                prev1_bar, prev1_rsi, prev1_price = pivot_highs[sz - 2]
                bars_diff = curr_bar - prev1_bar

                if RANGE_LOWER <= bars_diff <= RANGE_UPPER:
                    overbought_ok = (curr_rsi > RSI_OVERBOUGHT or prev1_rsi > RSI_OVERBOUGHT)
                    # Regular Bearish: 가격 Higher High + RSI Lower High
                    if overbought_ok and (prev1_price < curr_price) and (prev1_rsi > curr_rsi):
                        bear_cond1 = True
                        df.loc[df.index[pivot_idx], 'bear_div'] = True

            # curr vs prev2 (sz-3) - 2개 전 피벗
            if sz >= 3:
                prev2_bar, prev2_rsi, prev2_price = pivot_highs[sz - 3]
                bars_diff = curr_bar - prev2_bar

                if RANGE_LOWER <= bars_diff <= RANGE_UPPER:
                    overbought_ok = (curr_rsi > RSI_OVERBOUGHT or prev2_rsi > RSI_OVERBOUGHT)
                    if overbought_ok and (prev2_price < curr_price) and (prev2_rsi > curr_rsi):
                        bear_cond2 = True
                        df.loc[df.index[pivot_idx], 'bear_div'] = True

            # 더블 다이버전스: curr vs prev2 다이버전스 + prev1 vs prev2 다이버전스
            # prev1(sz-2)과 prev2(sz-3) 사이의 다이버전스 체크
            if bear_cond2 and sz >= 3:
                prev1_bar, prev1_rsi, prev1_price = pivot_highs[sz - 2]
                prev2_bar, prev2_rsi, prev2_price = pivot_highs[sz - 3]
                bars_diff_1_2 = prev1_bar - prev2_bar

                if RANGE_LOWER <= bars_diff_1_2 <= RANGE_UPPER:
                    overbought_ok_1_2 = (prev1_rsi > RSI_OVERBOUGHT or prev2_rsi > RSI_OVERBOUGHT)
                    if overbought_ok_1_2 and (prev2_price < prev1_price) and (prev2_rsi > prev1_rsi):
                        # prev1 vs prev2도 다이버전스 → 더블 다이버전스
                        df.loc[df.index[pivot_idx], 'double_bear_div'] = True

    # 통계 출력
    pivot_low_count = df['pivot_low'].sum()
    pivot_high_count = df['pivot_high'].sum()
    bull_div_count = df['bull_div'].sum()
    bear_div_count = df['bear_div'].sum()
    double_bull_count = df['double_bull_div'].sum()
    double_bear_count = df['double_bear_div'].sum()

    print(f"      - Pivot Low: {pivot_low_count}개")
    print(f"      - Pivot High: {pivot_high_count}개")
    print(f"      - Bullish Divergence: {bull_div_count}개")
    print(f"      - Bearish Divergence: {bear_div_count}개")
    print(f"      - Double Bullish Divergence: {double_bull_count}개")
    print(f"      - Double Bearish Divergence: {double_bear_count}개")

    return df


def apply_indicator_shift(df):
    """
    지표 타이밍 shift 적용
    실제 트레이딩에서는 현재 봉이 완료되기 전까지 지표값을 알 수 없으므로
    지표값을 1봉 shift하여 이전 봉의 완료된 지표값을 사용

    예: 5:45 봉의 RSI 값은 5:40 봉이 마감된 시점의 RSI 값
    """
    print("   지표 타이밍 shift 적용 중...")

    # shift할 컬럼 목록 (RSI 관련 모든 컬럼)
    rsi_columns = [col for col in df.columns if col.startswith('rsi')]

    # 1봉 shift (현재 봉 = 이전 봉의 지표값)
    for col in rsi_columns:
        df[col] = df[col].shift(1)

    print(f"      - {len(rsi_columns)}개 컬럼 shift 완료")

    return df


# ================================================================================
# 2. 데이터 다운로드 함수
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
# 3. 데이터 저장 함수
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
    순서: timestamp, OHLCV, RSI, 피벗, 다이버전스
    """
    columns_to_keep = [
        # 기본 정보
        'timestamp',

        # 5분봉 OHLCV
        'Open', 'High', 'Low', 'Close', 'Volume',

        # RSI
        'rsi',

        # 피벗
        'pivot_low',
        'pivot_high',

        # 다이버전스
        'bull_div',
        'bear_div',

        # 더블 다이버전스
        'double_bull_div',
        'double_bear_div',
    ]

    # 존재하는 컬럼만 선택
    available_columns = [col for col in columns_to_keep if col in df.columns]

    return df[available_columns].copy()


# ================================================================================
# 4. 메인 실행 함수
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
    print("\n[STEP 1/4] 5분봉 데이터 다운로드")
    df = download_binance_klines(SYMBOL, TIMEFRAME, START_DATE, END_DATE)

    if df is None:
        print("   ❌ 데이터 다운로드 실패")
        return

    # 원시 데이터 저장
    save_raw_data(df, OUTPUT_DIR, RAW_FILENAME)

    # 2. RSI 지표 계산
    print(f"\n[STEP 2/4] RSI 지표 계산")
    df = calculate_all_indicators(df)

    # NOTE: shift 미적용 - TradingView와 동일하게 해당 봉의 close 포함 계산
    # 백테스트에서 필요시 apply_indicator_shift(df) 호출

    # 3. 다이버전스 계산
    print(f"\n[STEP 3/4] RSI 다이버전스 계산")
    df = calculate_divergence(df)

    # 4. 최종 컬럼 정리 및 저장
    print("\n[STEP 4/4] 최종 백테스트 데이터 생성")
    df_final = prepare_final_columns(df)

    # NaN 제거 (초기 구간 - RSI 계산으로 인한)
    initial_rows = len(df_final)
    df_final = df_final.dropna()
    dropped_rows = initial_rows - len(df_final)

    if dropped_rows > 0:
        print(f"   ⚠️ NaN 제거: {dropped_rows} rows (지표 계산 초기 구간)")

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

    # 다이버전스 통계 출력
    print("\n" + SECTION_DIVIDER)
    print("📊 다이버전스 통계")
    print(SECTION_DIVIDER)
    print(f"   Pivot Low: {df_final['pivot_low'].sum()}개")
    print(f"   Pivot High: {df_final['pivot_high'].sum()}개")
    print(f"   Bullish Divergence: {df_final['bull_div'].sum()}개")
    print(f"   Bearish Divergence: {df_final['bear_div'].sum()}개")
    print(f"   Double Bullish Divergence: {df_final['double_bull_div'].sum()}개")
    print(f"   Double Bearish Divergence: {df_final['double_bear_div'].sum()}개")

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

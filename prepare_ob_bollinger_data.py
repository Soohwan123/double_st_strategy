"""
OB + Bollinger Engulfing Strategy - 백테스트 데이터 준비 스크립트

전략 조건 (TradingView Pine Script 기반):
- Bollinger Band (20, 2): SMA 기반
- Order Block (OB) 패턴:
  - Bullish OB: 음봉 → 양봉 Engulfing (양봉 몸통 >= 음봉 몸통 * 1.5, 음봉 종가 ≈ 양봉 시가)
  - Bearish OB: 양봉 → 음봉 Engulfing (음봉 몸통 >= 양봉 몸통 * 1.5, 양봉 종가 ≈ 음봉 시가)
- 신호:
  - LONG: Bullish OB + BB 하단 터치(두 봉 중 하나) + 종가 밴드 안쪽
  - SHORT: Bearish OB + BB 상단 터치(두 봉 중 하나) + 종가 밴드 안쪽

사용법:
    python prepare_ob_bollinger_data.py
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os

# ================================================================================
# CONFIG
# ================================================================================

# 다운로드 기간 설정
START_DATE = '2023-01-01'
END_DATE = '2025-12-31'

# 심볼 설정
SYMBOL = 'ETHUSDT'

# 타임프레임 설정
TIMEFRAME = '5m'

# 디렉토리 설정
OUTPUT_DIR = 'historical_data/'
BACKTEST_DATA_DIR = 'backtest_data/'

# 파일명 설정
RAW_FILENAME = f"{SYMBOL}_{TIMEFRAME}_raw.csv"
FINAL_FILENAME = f"{SYMBOL}_ob_bollinger.csv"

# API 설정
API_LIMIT = 1500
API_SLEEP = 0.1
API_RETRY_SLEEP = 5

# Bollinger Band 설정
BB_LENGTH = 20
BB_MULT = 2.0
BB_MA_TYPE = 'SMA'  # SMA, EMA, SMMA, WMA, VWMA

# Order Block 설정
MIN_BODY_RATIO = 1.5  # 양/음 최소 몸통 비율

# ================================================================================
# Bollinger Band 계산
# ================================================================================

def calculate_ma(series, length, ma_type='SMA'):
    """
    Moving Average 계산 (TradingView 방식)
    """
    if ma_type == 'SMA':
        return series.rolling(window=length).mean()
    elif ma_type == 'EMA':
        return series.ewm(span=length, adjust=False).mean()
    elif ma_type == 'SMMA' or ma_type == 'RMA':
        # Wilder's smoothing (RMA)
        alpha = 1.0 / length
        rma = series.copy()
        rma[:] = np.nan
        if len(series) >= length:
            rma.iloc[length - 1] = series.iloc[:length].mean()
            for i in range(length, len(series)):
                rma.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * rma.iloc[i - 1]
        return rma
    elif ma_type == 'WMA':
        weights = np.arange(1, length + 1)
        return series.rolling(window=length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    elif ma_type == 'VWMA':
        # VWMA는 Volume이 필요하므로 여기서는 SMA로 대체
        return series.rolling(window=length).mean()
    else:
        return series.rolling(window=length).mean()


def calculate_bollinger_band(df, length=20, mult=2.0, ma_type='SMA', source='Close'):
    """
    Bollinger Band 계산 (TradingView 방식)
    """
    df = df.copy()

    # Basis (MA)
    basis = calculate_ma(df[source], length, ma_type)

    # Standard Deviation (ddof=0 for population std)
    std = df[source].rolling(window=length).std(ddof=0)

    # Upper/Lower bands
    upper = basis + (mult * std)
    lower = basis - (mult * std)

    df['bb_basis'] = basis
    df['bb_upper'] = upper
    df['bb_lower'] = lower

    return df


# ================================================================================
# Order Block 패턴 계산
# ================================================================================

def calculate_ob_signals(df, min_body_ratio=1.5):
    """
    Order Block 신호 계산 (강화된 조건)

    Bullish OB: 음봉 + 음봉 + 양봉 (양봉이 두 음봉 몸통 모두 감싸기)
    - 2봉 전이 음봉
    - 1봉 전이 음봉
    - 현재 봉이 양봉
    - 양봉이 두 음봉의 몸통을 모두 감싸야 함
      (양봉 시가 <= 두 음봉 몸통 하단, 양봉 종가 >= 두 음봉 몸통 상단)

    Bearish OB: 양봉 + 양봉 + 음봉 (음봉이 두 양봉 몸통 모두 감싸기)
    - 2봉 전이 양봉
    - 1봉 전이 양봉
    - 현재 봉이 음봉
    - 음봉이 두 양봉의 몸통을 모두 감싸야 함
      (음봉 시가 >= 두 양봉 몸통 상단, 음봉 종가 <= 두 양봉 몸통 하단)
    """
    df = df.copy()

    # 봉 속성 계산
    df['is_bull'] = df['Close'] > df['Open']
    df['is_bear'] = df['Close'] < df['Open']
    df['body_top'] = df[['Open', 'Close']].max(axis=1)  # 몸통 상단
    df['body_bottom'] = df[['Open', 'Close']].min(axis=1)  # 몸통 하단

    # 1봉 전 값
    df['prev1_is_bull'] = df['is_bull'].shift(1)
    df['prev1_is_bear'] = df['is_bear'].shift(1)
    df['prev1_body_top'] = df['body_top'].shift(1)
    df['prev1_body_bottom'] = df['body_bottom'].shift(1)
    df['prev1_high'] = df['High'].shift(1)
    df['prev1_low'] = df['Low'].shift(1)

    # 2봉 전 값
    df['prev2_is_bull'] = df['is_bull'].shift(2)
    df['prev2_is_bear'] = df['is_bear'].shift(2)
    df['prev2_body_top'] = df['body_top'].shift(2)
    df['prev2_body_bottom'] = df['body_bottom'].shift(2)
    df['prev2_high'] = df['High'].shift(2)
    df['prev2_low'] = df['Low'].shift(2)

    # === Bullish OB ===
    # 음봉 + 음봉 + 양봉
    cond_bear_prev2 = df['prev2_is_bear']
    cond_bear_prev1 = df['prev1_is_bear']
    cond_bull_now = df['is_bull']

    # 두 음봉 몸통의 최상단과 최하단
    two_bear_body_top = df[['prev1_body_top', 'prev2_body_top']].max(axis=1)
    two_bear_body_bottom = df[['prev1_body_bottom', 'prev2_body_bottom']].min(axis=1)

    # 양봉이 두 음봉 몸통을 감싸야 함
    # 양봉 시가(=몸통 하단) <= 두 음봉 몸통 하단
    # 양봉 종가(=몸통 상단) >= 두 음봉 몸통 상단
    cond_engulf_bull = (df['Open'] <= two_bear_body_bottom) & (df['Close'] >= two_bear_body_top)

    df['bullish_ob'] = (
        cond_bear_prev2 & cond_bear_prev1 & cond_bull_now & cond_engulf_bull
    )

    # === Bearish OB ===
    # 양봉 + 양봉 + 음봉
    cond_bull_prev2 = df['prev2_is_bull']
    cond_bull_prev1 = df['prev1_is_bull']
    cond_bear_now = df['is_bear']

    # 두 양봉 몸통의 최상단과 최하단
    two_bull_body_top = df[['prev1_body_top', 'prev2_body_top']].max(axis=1)
    two_bull_body_bottom = df[['prev1_body_bottom', 'prev2_body_bottom']].min(axis=1)

    # 음봉이 두 양봉 몸통을 감싸야 함
    # 음봉 시가(=몸통 상단) >= 두 양봉 몸통 상단
    # 음봉 종가(=몸통 하단) <= 두 양봉 몸통 하단
    cond_engulf_bear = (df['Open'] >= two_bull_body_top) & (df['Close'] <= two_bull_body_bottom)

    df['bearish_ob'] = (
        cond_bull_prev2 & cond_bull_prev1 & cond_bear_now & cond_engulf_bear
    )

    return df


def calculate_final_signals(df):
    """
    최종 신호 계산 (OB + Bollinger 조건 결합)

    - Bull Signal: Bullish OB + 세 봉 중 하나가 BB 하단 터치 + 종가가 밴드 안쪽
    - Bear Signal: Bearish OB + 세 봉 중 하나가 BB 상단 터치 + 종가가 밴드 안쪽
    """
    df = df.copy()

    # BB 터치 조건 (세 봉 중 아무거나 - 현재, 1봉 전, 2봉 전)
    df['prev1_bb_upper'] = df['bb_upper'].shift(1)
    df['prev1_bb_lower'] = df['bb_lower'].shift(1)
    df['prev2_bb_upper'] = df['bb_upper'].shift(2)
    df['prev2_bb_lower'] = df['bb_lower'].shift(2)

    # 상단 터치: High >= BB Upper
    touch_upper_now = df['High'] >= df['bb_upper']
    touch_upper_prev1 = df['prev1_high'] >= df['prev1_bb_upper']
    touch_upper_prev2 = df['prev2_high'] >= df['prev2_bb_upper']
    touch_upper_any = touch_upper_now | touch_upper_prev1 | touch_upper_prev2

    # 하단 터치: Low <= BB Lower
    touch_lower_now = df['Low'] <= df['bb_lower']
    touch_lower_prev1 = df['prev1_low'] <= df['prev1_bb_lower']
    touch_lower_prev2 = df['prev2_low'] <= df['prev2_bb_lower']
    touch_lower_any = touch_lower_now | touch_lower_prev1 | touch_lower_prev2

    # 종가가 밴드 안쪽
    close_inside_band = (df['Close'] <= df['bb_upper']) & (df['Close'] >= df['bb_lower'])

    # 최종 신호
    # LONG: Bullish OB + BB 하단 터치 + 종가 밴드 안쪽
    df['long_signal'] = df['bullish_ob'] & touch_lower_any & close_inside_band

    # SHORT: Bearish OB + BB 상단 터치 + 종가 밴드 안쪽
    df['short_signal'] = df['bearish_ob'] & touch_upper_any & close_inside_band

    # OB 박스 영역 저장 (진입 후 손절 계산용)
    df['ob_box_top'] = np.nan
    df['ob_box_bottom'] = np.nan

    # Bullish OB의 경우: 양봉 몸통 = open(아래) ~ close(위)
    df.loc[df['long_signal'], 'ob_box_top'] = df.loc[df['long_signal'], 'Close']
    df.loc[df['long_signal'], 'ob_box_bottom'] = df.loc[df['long_signal'], 'Open']

    # Bearish OB의 경우: 음봉 몸통 = open(위) ~ close(아래)
    df.loc[df['short_signal'], 'ob_box_top'] = df.loc[df['short_signal'], 'Open']
    df.loc[df['short_signal'], 'ob_box_bottom'] = df.loc[df['short_signal'], 'Close']

    # 손절가는 백테스터에서 진입가 기준 0.5%로 계산하므로 여기서 계산하지 않음

    return df


# ================================================================================
# 데이터 다운로드 함수
# ================================================================================

def download_binance_klines(symbol, interval, start_date, end_date):
    """바이낸스 선물 캔들 데이터 다운로드"""
    base_url = 'https://fapi.binance.com/fapi/v1/klines'

    start_ms = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

    all_klines = []
    current_start = start_ms

    print(f"\n{'=' * 80}")
    print(f"다운로드 중: {symbol} {interval}")
    print(f"   기간: {start_date} ~ {end_date}")
    print('=' * 80)

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

            if len(all_klines) % 15000 == 0:
                current_date = datetime.fromtimestamp(klines[-1][0] / 1000).strftime('%Y-%m-%d')
                print(f"   진행 중... {current_date} ({len(all_klines):,} candles)")

            time.sleep(API_SLEEP)

        except requests.exceptions.RequestException as e:
            print(f"   API Error: {e}")
            print("   5초 후 재시도...")
            time.sleep(API_RETRY_SLEEP)
            continue

    if not all_klines:
        print("   다운로드 실패: 데이터 없음")
        return None

    # DataFrame 변환
    df = pd.DataFrame(all_klines, columns=[
        'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
        'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base',
        'Taker_buy_quote', 'Ignore'
    ])

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    df[numeric_cols] = df[numeric_cols].astype(float)
    df = df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']]

    print(f"   다운로드 완료: {len(df):,} candles")

    return df


def load_existing_data():
    """기존 원시 데이터 로드"""
    filepath = os.path.join(OUTPUT_DIR, RAW_FILENAME)
    if os.path.exists(filepath):
        print(f"\n기존 데이터 로드: {filepath}")
        df = pd.read_csv(filepath)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        print(f"   로드 완료: {len(df):,} candles")
        return df
    return None


# ================================================================================
# 메인 실행
# ================================================================================

def main():
    print("\n" + "=" * 80)
    print("OB + Bollinger Engulfing Strategy - 데이터 준비")
    print("=" * 80)

    # 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(BACKTEST_DATA_DIR, exist_ok=True)

    # 1. 데이터 로드 (기존 데이터 있으면 사용, 없으면 다운로드)
    df = load_existing_data()
    if df is None:
        df = download_binance_klines(SYMBOL, TIMEFRAME, START_DATE, END_DATE)
        if df is None:
            print("데이터 다운로드 실패")
            return
        # 원시 데이터 저장
        df.to_csv(os.path.join(OUTPUT_DIR, RAW_FILENAME), index=False)
        print(f"   원시 데이터 저장: {OUTPUT_DIR}{RAW_FILENAME}")

    # # 기간 필터링
    # df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    # df = df.sort_values('timestamp').reset_index(drop=True)

    # print(f"\n[STEP 1] Bollinger Band 계산")
    # df = calculate_bollinger_band(df, length=BB_LENGTH, mult=BB_MULT, ma_type=BB_MA_TYPE)
    # print(f"   BB({BB_LENGTH}, {BB_MULT}) 완료")

    # print(f"\n[STEP 2] Order Block 신호 계산")
    # df = calculate_ob_signals(df, min_body_ratio=MIN_BODY_RATIO)
    # print(f"   Bullish OB: {df['bullish_ob'].sum()}개")
    # print(f"   Bearish OB: {df['bearish_ob'].sum()}개")

    # print(f"\n[STEP 3] 최종 신호 계산 (OB + BB 조건)")
    # df = calculate_final_signals(df)
    # print(f"   LONG 신호: {df['long_signal'].sum()}개")
    # print(f"   SHORT 신호: {df['short_signal'].sum()}개")

    # # NaN 제거 (BB 초기 구간)
    # initial_rows = len(df)
    # df = df.dropna(subset=['bb_basis'])
    # dropped = initial_rows - len(df)
    # if dropped > 0:
    #     print(f"   NaN 제거: {dropped} rows (BB 초기 구간)")

    # # 필요한 컬럼만 선택
    # columns_to_keep = [
    #     'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
    #     'bb_basis', 'bb_upper', 'bb_lower',
    #     'bullish_ob', 'bearish_ob',
    #     'long_signal', 'short_signal',
    #     'ob_box_top', 'ob_box_bottom'
    # ]
    # df_final = df[columns_to_keep].copy()

    # # 저장
    # output_path = os.path.join(BACKTEST_DATA_DIR, FINAL_FILENAME)
    # df_final.to_csv(output_path, index=False)

    print(f"\n" + "=" * 80)
    print(f"데이터 준비 완료!")
    print("=" * 80)
    # print(f"파일: {output_path}")
    # print(f"기간: {df_final['timestamp'].min()} ~ {df_final['timestamp'].max()}")
    # print(f"데이터 수: {len(df_final):,} rows")
    # print(f"LONG 신호: {df_final['long_signal'].sum()}개")
    # print(f"SHORT 신호: {df_final['short_signal'].sum()}개")


if __name__ == "__main__":
    main()

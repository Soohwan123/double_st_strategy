"""
Double Bollinger Band Strategy - 백테스트 데이터 준비 스크립트

이 스크립트는 다음 작업을 수행합니다:
1. 바이낸스에서 2025년 8월-11월 5분봉 데이터 다운로드
2. Bollinger Band (20,2), (4,4) 지표 계산
3. 지표 타이밍 shift 적용 (1봉 shift - 실제 트레이딩 시 이전 봉의 지표값 사용)
4. 최종 백테스트용 CSV 생성

사용법:
    python prepare_bollinger_data.py
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
START_DATE = '2019-10-01'  # 시작 날짜
END_DATE = '2025-12-30'    # 종료 날짜

# 심볼 설정
SYMBOL = 'BTCUSDC'

# 타임프레임 설정 (5분봉만 사용)
TIMEFRAME = '15m'

# 디렉토리 설정
OUTPUT_DIR = 'historical_data/'       # 원시 데이터 저장 경로
BACKTEST_DATA_DIR = 'backtest_data/'  # 백테스트 데이터 저장 경로

# 파일명 설정
RAW_FILENAME = f"{SYMBOL}_{TIMEFRAME}_raw.csv"
FINAL_FILENAME = f"{SYMBOL}_double_bb_2019_10_11.csv"

# API 설정
API_LIMIT = 1500              # 바이낸스 API 한 번 요청 시 최대 캔들 수
API_SLEEP = 0.1               # API 요청 간격 (초)
API_RETRY_SLEEP = 5           # API 오류 시 재시도 대기 시간 (초)

# 진행 상황 출력 설정
PROGRESS_UPDATE_INTERVAL = 15000  # 진행 상황 업데이트 간격 (캔들 수)

# Bollinger Band 설정
BB_SETTINGS = [
    {'length': 20, 'std': 2, 'suffix': '20_2', 'source': 'Close'},  # BB(20,2) - 종가 기준
    {'length': 4, 'std': 4, 'suffix': '4_4', 'source': 'Open'}      # BB(4,4) - 시가 기준
]

# ================================================================================
# 출력 메시지 설정
# ================================================================================
SECTION_DIVIDER = "=" * 80
TITLE = "Double Bollinger Band Strategy - 백테스트 데이터 준비"

# ================================================================================
# 1. Bollinger Band 계산 함수
# ================================================================================

def calculate_bollinger_band(df, length, std_dev, suffix='', source='Close'):
    """
    Bollinger Band 계산

    Parameters:
    - df: OHLC 데이터프레임
    - length: SMA 기간
    - std_dev: 표준편차 배수
    - suffix: 컬럼명 suffix (예: '20_2', '4_4')
    - source: BB 계산에 사용할 가격 소스 ('Close' 또는 'Open')

    Returns:
    - df with Bollinger Band columns added
    """
    df = df.copy()

    # SMA 계산 (소스 선택)
    sma = df[source].rolling(window=length).mean()

    # 표준편차 계산 (TradingView 표준: population std, ddof=0)
    std = df[source].rolling(window=length).std(ddof=0)

    # Upper/Lower Band 계산
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)

    # 컬럼명 설정
    sma_col = f'bb_sma_{suffix}'
    upper_col = f'bb_upper_{suffix}'
    lower_col = f'bb_lower_{suffix}'

    df[sma_col] = sma
    df[upper_col] = upper
    df[lower_col] = lower

    return df


def calculate_all_indicators(df):
    """
    모든 Bollinger Band 지표 계산
    """
    print("   Bollinger Band 지표 계산 중...")

    for setting in BB_SETTINGS:
        df = calculate_bollinger_band(
            df,
            length=setting['length'],
            std_dev=setting['std'],
            suffix=setting['suffix'],
            source=setting.get('source', 'Close')  # 기본값은 종가
        )
        source_name = setting.get('source', 'Close')
        print(f"      - BB({setting['length']},{setting['std']}) [{source_name}] 완료")

    return df


def apply_indicator_shift(df):
    """
    지표 타이밍 shift 적용
    실제 트레이딩에서는 현재 봉이 완료되기 전까지 지표값을 알 수 없으므로
    지표값을 1봉 shift하여 이전 봉의 완료된 지표값을 사용

    예: 5:45 봉의 BB 값은 5:40 봉이 마감된 시점의 BB 값
    """
    print("   지표 타이밍 shift 적용 중...")

    # shift할 컬럼 목록 (BB 관련 모든 컬럼)
    bb_columns = [col for col in df.columns if col.startswith('bb_')]

    # 1봉 shift (현재 봉 = 이전 봉의 지표값)
    for col in bb_columns:
        df[col] = df[col].shift(1)

    print(f"      - {len(bb_columns)}개 컬럼 shift 완료")

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
    순서: timestamp, OHLCV, BB(20,2) upper/lower, BB(4,4) upper/lower
    """
    columns_to_keep = [
        # 기본 정보
        'timestamp',

        # 5분봉 OHLCV
        'Open', 'High', 'Low', 'Close', 'Volume',

        # Bollinger Band 20/2
        'bb_upper_20_2', 'bb_lower_20_2',

        # Bollinger Band 4/4
        'bb_upper_4_4', 'bb_lower_4_4',
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
    print("\n[STEP 1/3] 5분봉 데이터 다운로드")
    df = download_binance_klines(SYMBOL, TIMEFRAME, START_DATE, END_DATE)

    if df is None:
        print("   ❌ 데이터 다운로드 실패")
        return

    # 원시 데이터 저장
    save_raw_data(df, OUTPUT_DIR, RAW_FILENAME)

    # 2. Bollinger Band 지표 계산
    print(f"\n[STEP 2/3] Bollinger Band 지표 계산")
    df = calculate_all_indicators(df)

    # NOTE: shift 미적용 - TradingView와 동일하게 해당 봉의 close 포함 계산
    # 백테스트에서 "봉 진행 중 터치" 로직은 High/Low vs BB 비교로 처리

    # 3. 최종 컬럼 정리 및 저장
    print("\n[STEP 3/3] 최종 백테스트 데이터 생성")
    df_final = prepare_final_columns(df)

    # NaN 제거 (초기 구간 - BB 계산으로 인한)
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

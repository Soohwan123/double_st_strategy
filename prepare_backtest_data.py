"""
Double SuperTrend Strategy - 2025년 6-11월 백테스트 데이터 준비 스크립트

이 스크립트는 다음 작업을 수행합니다:
1. 바이낸스에서 2025년 6월-11월 5분봉, 1시간봉 데이터 다운로드
2. SuperTrend(12,1), SuperTrend(12,3) 지표 계산
3. 5분봉과 1시간봉 데이터 병합
4. 최종 백테스트용 CSV 생성

사용법:
    python prepare_backtest_data_2025.py
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os
from calculate_indicators import (
    calculate_indicators_5m,
    calculate_indicators_1h,
    prepare_final_columns
)

# ================================================================================
# CONFIG: 모든 설정 값 (자유롭게 수정 가능)
# ================================================================================

# 다운로드 기간 설정
START_DATE = '2020-01-01'  # 시작 날짜
END_DATE = '2025-11-05'    # 종료 날짜

# 심볼 설정
SYMBOL = 'BTCUSDT'

# 타임프레임 설정
TIMEFRAMES = ['5m', '1h']  # 5분봉, 1시간봉

# 디렉토리 설정
OUTPUT_DIR = 'historical_data_2025/'       # 원시 데이터 저장 경로
BACKTEST_DATA_DIR = 'backtest_data_2025/'  # 백테스트 데이터 저장 경로

# 파일명 설정
RAW_FILENAME_FORMAT = "{symbol}_{interval}_2025_raw.csv"           # 원시 데이터 파일명 형식
FINAL_FILENAME_FORMAT = "{symbol}_double_st_2025_01_01.csv"        # 최종 백테스트 파일명 형식

# API 설정
API_LIMIT = 1500              # 바이낸스 API 한 번 요청 시 최대 캔들 수
API_SLEEP = 0.1               # API 요청 간격 (초)
API_RETRY_SLEEP = 5           # API 오류 시 재시도 대기 시간 (초)

# 진행 상황 출력 설정
PROGRESS_UPDATE_INTERVAL = 15000  # 진행 상황 업데이트 간격 (캔들 수)

# 출력 메시지 설정
TITLE = "Double SuperTrend Strategy - 2025년 1-11월 백테스트 데이터 준비"
SECTION_DIVIDER = "=" * 80
DOWNLOAD_HEADER = "📥 다운로드 중: {symbol} {interval}"
DOWNLOAD_PERIOD = "   기간: {start} ~ {end}"
PROGRESS_MSG = "   진행 중... {date} ({count:,} candles)"
ERROR_MSG = "   ⚠️ API Error: {error}"
RETRY_MSG = "   5초 후 재시도..."
NO_DATA_MSG = "   ❌ 다운로드 실패: 데이터 없음"
DOWNLOAD_SUCCESS = "   ✅ 다운로드 완료: {count:,} candles"
SAVE_SUCCESS = "   💾 저장 완료: {path}"
MERGE_START = "📊 타임프레임 병합 중..."
MERGE_SUCCESS = "   ✅ 병합 완료: {count:,} rows"
INDICATOR_5M_MSG = "5분봉 SuperTrend 지표 계산"
INDICATOR_1H_MSG = "1시간봉 SuperTrend 지표 계산"
INDICATOR_SUCCESS = "   ✅ {interval} 지표 계산 완료"
NAN_WARNING = "   ⚠️ NaN 제거: {count} rows (지표 계산 초기 구간)"
FINAL_SAVE_MSG = "   💾 최종 백테스트 데이터 저장: {path}"
DATA_SIZE_MSG = "   📊 데이터 크기: {rows:,} rows x {cols} columns"
SUMMARY_TITLE = "📋 최종 데이터 요약"
SAMPLE_TITLE = "🔍 샘플 데이터 (처음 5행)"
COMPLETE_MSG = "✅ 2025년 1-11월 백테스트 데이터 준비 완료!"

# ================================================================================
# 1. 데이터 다운로드 함수
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
    print(DOWNLOAD_HEADER.format(symbol=symbol, interval=interval))
    print(DOWNLOAD_PERIOD.format(start=start_date, end=end_date))
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
                print(PROGRESS_MSG.format(date=current_date, count=len(all_klines)))

            time.sleep(API_SLEEP)  # API 제한 고려

        except requests.exceptions.RequestException as e:
            print(ERROR_MSG.format(error=e))
            print(RETRY_MSG)
            time.sleep(API_RETRY_SLEEP)
            continue

    if not all_klines:
        print(NO_DATA_MSG)
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

    print(DOWNLOAD_SUCCESS.format(count=len(df)))

    return df


# ================================================================================
# 2. 데이터 저장 함수
# ================================================================================

def save_data(df, symbol, interval, output_dir):
    """다운로드한 데이터를 CSV로 저장"""
    os.makedirs(output_dir, exist_ok=True)

    filename = RAW_FILENAME_FORMAT.format(symbol=symbol, interval=interval)
    filepath = os.path.join(output_dir, filename)

    df.to_csv(filepath, index=False)
    print(SAVE_SUCCESS.format(path=filepath))

    return filepath


# ================================================================================
# 3. 데이터 병합 함수
# ================================================================================

def merge_timeframes(df_5m, df_1h):
    """
    5분봉과 1시간봉 데이터 병합
    1시간봉 데이터를 1시간 앞으로 shift하여 병합
    예: 5분봉 19:00 데이터 = 1시간봉 20:00 데이터와 매칭
    """
    print(f"\n{MERGE_START}")

    # 1시간봉 컬럼명 변경
    df_1h_renamed = df_1h.copy()
    df_1h_renamed.columns = [col + '_1h' if col != 'timestamp' else col
                             for col in df_1h.columns]

    # 1시간봉 타임스탬프를 1시간 뒤로 이동 (데이터는 1시간 앞의 것을 사용)
    # 즉, 원래 20:00 데이터를 19:00 위치로 이동
    df_1h_renamed['timestamp'] = df_1h_renamed['timestamp'] - pd.Timedelta(hours=1)

    # 타임스탬프를 기준으로 정렬
    df_5m = df_5m.sort_values('timestamp')
    df_1h_renamed = df_1h_renamed.sort_values('timestamp')

    # 1시간봉 데이터를 5분봉에 맞춰 병합 (forward fill)
    # shift된 타임스탬프 기준으로 병합
    df_merged = pd.merge_asof(
        df_5m,
        df_1h_renamed,
        on='timestamp',
        direction='backward'  # 이전 1시간봉 데이터 사용
    )

    print(MERGE_SUCCESS.format(count=len(df_merged)))
    print(f"   📌 1시간봉 데이터가 1시간 앞으로 shift됨 (5분봉 19:00 = 1시간봉 20:00)")

    return df_merged


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
    print("\n[STEP 1/5] 데이터 다운로드")

    data_files = {}
    for interval in TIMEFRAMES:
        df = download_binance_klines(SYMBOL, interval, START_DATE, END_DATE)
        if df is not None:
            filepath = save_data(df, SYMBOL, interval, OUTPUT_DIR)
            data_files[interval] = df
        else:
            print(f"   ❌ {interval} 다운로드 실패")
            return

    # 2. 지표 계산 (5분봉)
    print(f"\n[STEP 2/5] {INDICATOR_5M_MSG}")
    df_5m = data_files['5m'].copy()
    df_5m = calculate_indicators_5m(df_5m)
    print(INDICATOR_SUCCESS.format(interval='5분봉'))

    # 3. 지표 계산 (1시간봉)
    print(f"\n[STEP 3/5] {INDICATOR_1H_MSG}")
    df_1h = data_files['1h'].copy()
    df_1h = calculate_indicators_1h(df_1h)
    print(INDICATOR_SUCCESS.format(interval='1시간봉'))

    # 4. 데이터 병합
    print("\n[STEP 4/5] 타임프레임 병합")
    df_merged = merge_timeframes(df_5m, df_1h)

    # 5. 최종 컬럼 정리 및 저장
    print("\n[STEP 5/5] 최종 백테스트 데이터 생성")
    df_final = prepare_final_columns(df_merged)

    # NaN 제거 (초기 구간)
    initial_rows = len(df_final)
    df_final = df_final.dropna()
    dropped_rows = initial_rows - len(df_final)

    if dropped_rows > 0:
        print(NAN_WARNING.format(count=dropped_rows))

    # 최종 파일 저장
    output_filename = FINAL_FILENAME_FORMAT.format(symbol=SYMBOL)
    output_path = os.path.join(BACKTEST_DATA_DIR, output_filename)
    df_final.to_csv(output_path, index=False)

    print(FINAL_SAVE_MSG.format(path=output_path))
    print(DATA_SIZE_MSG.format(rows=len(df_final), cols=len(df_final.columns)))

    # 데이터 요약 출력
    print("\n" + SECTION_DIVIDER)
    print(SUMMARY_TITLE)
    print(SECTION_DIVIDER)
    print(f"기간: {df_final['timestamp'].min()} ~ {df_final['timestamp'].max()}")
    print(f"행 수: {len(df_final):,}")
    print(f"컬럼 수: {len(df_final.columns)}")
    print(f"\n컬럼 목록:")
    for i, col in enumerate(df_final.columns, 1):
        print(f"  {i:2d}. {col}")

    # 샘플 데이터 출력
    print("\n" + SECTION_DIVIDER)
    print(SAMPLE_TITLE)
    print(SECTION_DIVIDER)
    print(df_final.head())

    print(f"\n{COMPLETE_MSG}")
    print(f"   파일: {output_path}")
    print(f"   이제 {START_DATE} ~ {END_DATE} 백테스트를 실행할 수 있습니다.")


if __name__ == "__main__":
    main()
"""
SMA/VWMA 멀티 타임프레임 데이터 준비 스크립트

TradingView와 동일한 계산 방식 사용
- 5분봉: 50 SMA, 100 VWMA, 200 SMA, 400 SMA
- 15분봉: 200 SMA
- 1시간봉: 200 SMA
- 4시간봉: 200 SMA

사용법:
    python prepare_ema_data.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG
# ================================================================================

# 입력 파일 (5분봉 원시 데이터)
INPUT_FILE = 'historical_data/BTCUSDT_5m_raw.csv'

# 출력 파일
OUTPUT_FILE = 'backtest_data/BTCUSDT_sma_mtf.csv'

# 데이터 기간
START_DATE = '2024-01-01'
END_DATE = '2025-12-31'


# ================================================================================
# SMA/VWMA 계산 (TradingView 방식)
# ================================================================================

def calculate_sma(series, period):
    """
    Simple Moving Average (SMA)
    TradingView와 동일: 단순 이동평균
    """
    return series.rolling(window=period).mean()


def calculate_vwma(close, volume, period):
    """
    Volume Weighted Moving Average (VWMA)
    TradingView와 동일: VWMA = sum(close * volume, period) / sum(volume, period)
    """
    vwma = (close * volume).rolling(window=period).sum() / volume.rolling(window=period).sum()
    return vwma


def calculate_rsi(series, period=14):
    """
    RSI 계산 (TradingView 방식)
    TradingView는 RMA(Wilder's Smoothing)를 사용
    """
    delta = series.diff()

    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)

    # RMA (Wilder's Smoothing) = EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def resample_to_higher_timeframe(df_5m, timeframe):
    """
    5분봉 데이터를 더 높은 타임프레임으로 리샘플링

    Parameters:
        df_5m: 5분봉 DataFrame
        timeframe: '15min', '1h', '4h' 등
    """
    df_resampled = df_5m.set_index('timestamp').resample(timeframe).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()

    return df_resampled.reset_index()


def map_higher_tf_to_5m(df_5m, df_htf, column_name, htf_column='sma_200'):
    """
    높은 타임프레임의 값을 5분봉에 매핑
    각 5분봉은 해당 시점의 완성된 상위 타임프레임 값을 사용
    """
    # 상위 타임프레임 인덱스 설정
    df_htf_indexed = df_htf.set_index('timestamp')[[htf_column]].copy()
    df_htf_indexed.columns = [column_name]

    # 5분봉에 매핑 (forward fill - 이전 완성된 캔들의 값 사용)
    df_5m_indexed = df_5m.set_index('timestamp')

    # reindex로 5분봉 타임스탬프에 맞추고 forward fill
    result = df_htf_indexed.reindex(df_5m_indexed.index, method='ffill')

    return result[column_name].values


# ================================================================================
# 메인 함수
# ================================================================================

def main():
    print("=" * 70)
    print("SMA/VWMA 멀티 타임프레임 데이터 준비")
    print("=" * 70)

    # 데이터 로드
    print(f"\n[1] 데이터 로드: {INPUT_FILE}")
    df = pd.read_csv(INPUT_FILE)

    # timestamp 변환
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    elif 'Open time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['Open time'], unit='ms')

    # 필요한 컬럼만 선택
    required_cols = ['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_cols:
        if col not in df.columns:
            for orig_col in df.columns:
                if orig_col.lower() == col.lower():
                    df[col] = df[orig_col]
                    break

    df = df[required_cols].copy()

    # 정렬
    df = df.sort_values('timestamp').reset_index(drop=True)

    print(f"   전체 기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print(f"   전체 데이터: {len(df):,} rows")

    # ========================================
    # 5분봉 SMA/VWMA 계산
    # ========================================
    print(f"\n[2] 5분봉 SMA/VWMA 계산")

    df['sma_50'] = calculate_sma(df['Close'], 50)
    print(f"   5m SMA(50) 완료")

    df['vwma_100'] = calculate_vwma(df['Close'], df['Volume'], 100)
    print(f"   5m VWMA(100) 완료")

    df['sma_200'] = calculate_sma(df['Close'], 200)
    print(f"   5m SMA(200) 완료")

    df['sma_400'] = calculate_sma(df['Close'], 400)
    print(f"   5m SMA(400) 완료")

    # ========================================
    # 15분봉 200 SMA 계산
    # ========================================
    print(f"\n[3] 15분봉 SMA(200) 계산")
    df_15m = resample_to_higher_timeframe(df, '15min')
    df_15m['sma_200'] = calculate_sma(df_15m['Close'], 200)
    print(f"   15m 캔들 수: {len(df_15m):,}")

    # 5분봉에 매핑
    df['sma_200_15m'] = map_higher_tf_to_5m(df, df_15m, 'sma_200_15m', 'sma_200')
    print(f"   15m SMA(200) → 5m 매핑 완료")

    # ========================================
    # 1시간봉 200 SMA + RSI(14) 계산
    # ========================================
    print(f"\n[4] 1시간봉 SMA(200) + RSI(14) 계산")
    df_1h = resample_to_higher_timeframe(df, '1h')
    df_1h['sma_200'] = calculate_sma(df_1h['Close'], 200)
    df_1h['rsi_14'] = calculate_rsi(df_1h['Close'], 14)
    print(f"   1h 캔들 수: {len(df_1h):,}")

    # 5분봉에 매핑
    df['sma_200_1h'] = map_higher_tf_to_5m(df, df_1h, 'sma_200_1h', 'sma_200')
    print(f"   1h SMA(200) → 5m 매핑 완료")

    df['rsi_14_1h'] = map_higher_tf_to_5m(df, df_1h, 'rsi_14_1h', 'rsi_14')
    print(f"   1h RSI(14) → 5m 매핑 완료")

    # ========================================
    # 4시간봉 200 SMA 계산
    # ========================================
    print(f"\n[5] 4시간봉 SMA(200) 계산")
    df_4h = resample_to_higher_timeframe(df, '4h')
    df_4h['sma_200'] = calculate_sma(df_4h['Close'], 200)
    print(f"   4h 캔들 수: {len(df_4h):,}")

    # 5분봉에 매핑
    df['sma_200_4h'] = map_higher_tf_to_5m(df, df_4h, 'sma_200_4h', 'sma_200')
    print(f"   4h SMA(200) → 5m 매핑 완료")

    # ========================================
    # 기간 필터링 및 저장
    # ========================================
    print(f"\n[6] 데이터 정리")

    # 기간 필터링
    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]

    # NaN 제거 (SMA/VWMA 계산 초기값)
    initial_rows = len(df)
    df = df.dropna().reset_index(drop=True)
    dropped = initial_rows - len(df)
    print(f"   NaN 제거: {dropped} rows (MA 초기 구간)")

    # 최종 컬럼 순서 정리
    final_columns = [
        'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
        'sma_50', 'vwma_100', 'sma_200', 'sma_400',  # 5분봉
        'sma_200_15m',  # 15분봉
        'sma_200_1h', 'rsi_14_1h',  # 1시간봉
        'sma_200_4h'    # 4시간봉
    ]
    df = df[final_columns]

    # 저장
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"\n" + "=" * 70)
    print(f"데이터 준비 완료!")
    print("=" * 70)
    print(f"파일: {OUTPUT_FILE}")
    print(f"기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print(f"데이터 수: {len(df):,} rows")

    print(f"\n컬럼 목록:")
    print(f"   5분봉 : sma_50, vwma_100, sma_200, sma_400")
    print(f"   15분봉: sma_200_15m")
    print(f"   1시간봉: sma_200_1h, rsi_14_1h")
    print(f"   4시간봉: sma_200_4h")

    # 샘플 출력
    print(f"\n샘플 데이터 (마지막 5행):")
    sample_cols = ['timestamp', 'Close', 'sma_50', 'vwma_100', 'sma_200', 'sma_200_15m', 'sma_200_1h', 'sma_200_4h']
    print(df[sample_cols].tail().to_string(index=False))


if __name__ == "__main__":
    main()

"""
Double SuperTrend Strategy - 지표 계산 모듈
바이낸스/TradingView 표준 SuperTrend 계산 (shift 적용)
"""

import pandas as pd
import numpy as np


def calculate_supertrend(df, length, factor, suffix=''):
    """
    바이낸스/TradingView 표준 SuperTrend 계산

    Parameters:
    - df: OHLC 데이터프레임
    - length: ATR 기간 (12)
    - factor: ATR 배수 (1 또는 3)
    - suffix: 컬럼명 suffix (예: '_5m', '_1h')

    Returns:
    - df with SuperTrend columns added
    """
    df = df.copy()

    # True Range 계산
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift(1))
    low_close = np.abs(df['Low'] - df['Close'].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # ATR 계산 (RMA - Wilder's Smoothing, TradingView 표준)
    # RMA = (previous_RMA * (length - 1) + current_value) / length
    atr = pd.Series(0.0, index=df.index)

    # 첫 length개는 SMA로 초기화
    atr.iloc[length-1] = tr.iloc[:length].mean()

    # 이후는 RMA 공식 사용
    for i in range(length, len(df)):
        atr.iloc[i] = (atr.iloc[i-1] * (length - 1) + tr.iloc[i]) / length

    # HL2 (중간 가격)
    hl2 = (df['High'] + df['Low']) / 2

    # Basic Upper/Lower Band
    # Up = HL2 - (factor × ATR)  -> Lower Band (상승 추세선)
    # Dn = HL2 + (factor × ATR)  -> Upper Band (하락 추세선)
    basic_up = hl2 - (factor * atr)
    basic_dn = hl2 + (factor * atr)

    # Final Bands 초기화
    final_up = pd.Series(0.0, index=df.index)
    final_dn = pd.Series(0.0, index=df.index)

    # SuperTrend 컬럼
    st_col = f'st_{length}_{factor}{suffix}'
    dir_col = f'st_{length}_{factor}{suffix}_dir'

    supertrend = pd.Series(0.0, index=df.index)
    direction = pd.Series(1, index=df.index)  # 1: Uptrend, -1: Downtrend

    # 표준 SuperTrend 계산 (length부터 시작)
    for i in range(length, len(df)):
        # Final Upper Band (TrendUp)
        if i == length:
            final_up.iloc[i] = basic_up.iloc[i]
        else:
            prev_close = df['Close'].iloc[i-1]
            prev_final_up = final_up.iloc[i-1]
            curr_basic_up = basic_up.iloc[i]

            # 이전 Close가 이전 TrendUp보다 위면
            if prev_close > prev_final_up:
                final_up.iloc[i] = max(curr_basic_up, prev_final_up)
            else:
                final_up.iloc[i] = curr_basic_up

        # Final Lower Band (TrendDown)
        if i == length:
            final_dn.iloc[i] = basic_dn.iloc[i]
        else:
            prev_close = df['Close'].iloc[i-1]
            prev_final_dn = final_dn.iloc[i-1]
            curr_basic_dn = basic_dn.iloc[i]

            # 이전 Close가 이전 TrendDown보다 아래면
            if prev_close < prev_final_dn:
                final_dn.iloc[i] = min(curr_basic_dn, prev_final_dn)
            else:
                final_dn.iloc[i] = curr_basic_dn

        # Trend Direction 결정
        curr_close = df['Close'].iloc[i]
        prev_final_dn = final_dn.iloc[i-1] if i > length else final_dn.iloc[i]
        prev_final_up = final_up.iloc[i-1] if i > length else final_up.iloc[i]

        if i == length:
            # 초기 방향: Close가 HL2보다 위면 Uptrend
            if curr_close > hl2.iloc[i]:
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1
        else:
            prev_dir = direction.iloc[i-1]

            # Close가 이전 TrendDown을 돌파하면 Uptrend
            if curr_close > prev_final_dn:
                direction.iloc[i] = 1
            # Close가 이전 TrendUp을 이탈하면 Downtrend
            elif curr_close < prev_final_up:
                direction.iloc[i] = -1
            else:
                # 추세 유지
                direction.iloc[i] = prev_dir

        # SuperTrend 값 설정
        if direction.iloc[i] == 1:
            supertrend.iloc[i] = final_up.iloc[i]
        else:
            supertrend.iloc[i] = final_dn.iloc[i]

    # 데이터프레임에 추가
    df[st_col] = supertrend
    df[dir_col] = direction

    return df


def calculate_indicators_5m(df):
    """
    5분봉 데이터에 SuperTrend 지표 추가
    현재 봉 종료 시점의 값 사용 (shift 없음)
    """
    print("   5분봉 SuperTrend 계산 중...")

    # SuperTrend 12/1 계산
    df = calculate_supertrend(df.copy(), length=12, factor=1, suffix='_5m')
    print("      - ST(12,1) 완료")

    # SuperTrend 12/3 계산
    df = calculate_supertrend(df, length=12, factor=3, suffix='_5m')
    print("      - ST(12,3) 완료")

    return df


def calculate_indicators_1h(df):
    """
    1시간봉 데이터에 SuperTrend 지표 추가
    현재 봉 종료 시점의 값 사용 (shift 없음)
    """
    print("   1시간봉 SuperTrend 계산 중...")

    # SuperTrend 12/1 계산
    df = calculate_supertrend(df.copy(), length=12, factor=1, suffix='_1h')
    print("      - ST(12,1) 완료")

    # SuperTrend 12/3 계산
    df = calculate_supertrend(df, length=12, factor=3, suffix='_1h')
    print("      - ST(12,3) 완료")

    return df


def prepare_final_columns(df):
    """
    최종 CSV에 필요한 컬럼만 선택
    5분봉: timestamp, OHLCV, st_12_1, st_12_3 (값과 방향)
    1시간봉: OHLC, st_12_1, st_12_3 (값과 방향)
    """
    # 필요한 컬럼 리스트
    columns_to_keep = [
        # 기본 정보
        'timestamp',

        # 5분봉 OHLCV
        'Open', 'High', 'Low', 'Close', 'Volume',

        # 5분봉 SuperTrend
        'st_12_1_5m', 'st_12_1_5m_dir',
        'st_12_3_5m', 'st_12_3_5m_dir',

        # 1시간봉 OHLC
        'Open_1h', 'High_1h', 'Low_1h', 'Close_1h',

        # 1시간봉 SuperTrend
        'st_12_1_1h_1h', 'st_12_1_1h_dir_1h',
        'st_12_3_1h_1h', 'st_12_3_1h_dir_1h'
    ]

    # 존재하는 컬럼만 선택
    available_columns = [col for col in columns_to_keep if col in df.columns]

    df_final = df[available_columns].copy()

    # 컬럼명 간소화 (_1h 중복 제거)
    rename_dict = {
        'st_12_1_1h_1h': 'st_12_1_1h',
        'st_12_1_1h_dir_1h': 'st_12_1_1h_dir',
        'st_12_3_1h_1h': 'st_12_3_1h',
        'st_12_3_1h_dir_1h': 'st_12_3_1h_dir'
    }

    df_final.rename(columns=rename_dict, inplace=True)

    return df_final


if __name__ == "__main__":
    print("Double SuperTrend Strategy - Indicators Module")
    print("This module calculates SuperTrend using Binance/TradingView standard")
    print("- 5min: SuperTrend(12,1) and SuperTrend(12,3)")
    print("- 1hour: SuperTrend(12,1) and SuperTrend(12,3)")
    print("- Direction: 1 = Long (상승), -1 = Short (하락)")
    print("Values represent candle close state (no shift applied)")
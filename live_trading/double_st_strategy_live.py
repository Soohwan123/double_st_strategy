#!/usr/bin/env python3
"""
Double SuperTrend Strategy 실시간 자동매매 프로그램
Binance Futures BTCUSDC Perpetual 거래용
5분봉 + 1시간봉 더블 타임프레임 분석
"""

import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import sys
import logging
from typing import Dict, List, Optional, Tuple
import websockets
import websockets.exceptions
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *
import pytz
from collections import deque
import csv
import time
from glob import glob
import requests
import shutil
from config_ml import Config

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
LOGS_DIR = 'logs'
TRADE_RESULTS_DIR = 'trade_results'
LIVE_INDICATOR_DIR = 'live_indicator'
LIVE_INDICATOR_CSV = 'live_indicator/live_indicators.csv'

# 웹소켓 설정
WS_RECONNECT_DELAY = 5          # 웹소켓 재연결 대기 시간 (초)

# 로깅 설정
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(TRADE_RESULTS_DIR, exist_ok=True)
os.makedirs(LIVE_INDICATOR_DIR, exist_ok=True)


class DailyLogHandler:
    def __init__(self, strategy_name):
        self.strategy_name = strategy_name
        self.current_date = None
        self.logger = None
        self.setup_logger()

    def setup_logger(self):
        today = datetime.now(pytz.timezone('UTC')).strftime('%Y-%m-%d')
        if today != self.current_date:
            self.current_date = today
            log_filename = f'logs/{self.strategy_name}_{today}.log'

            if self.logger:
                for handler in self.logger.handlers[:]:
                    handler.close()
                    self.logger.removeHandler(handler)

            self.logger = logging.getLogger(f'{self.strategy_name}_{today}')
            self.logger.setLevel(logging.INFO)
            self.logger.handlers.clear()

            log_dir = os.path.dirname(log_filename)
            os.makedirs(log_dir, exist_ok=True)

            if not os.path.exists(log_filename):
                with open(log_filename, 'w') as f:
                    f.write(f"# Double SuperTrend Strategy Log - {today}\n")

            file_handler = logging.FileHandler(log_filename)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(file_handler)

            self.logger.info(f"📅 새로운 날짜 로그 파일 시작: {today}")

    def get_logger(self):
        self.setup_logger()
        return self.logger


# 전역 로그 핸들러 생성
daily_log_handler = DailyLogHandler('double_st_strategy_btcusdc')
logger = daily_log_handler.get_logger()


# ============================================================================
# SuperTrend 지표 계산
# ============================================================================

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
    atr = pd.Series(0.0, index=df.index)

    # 첫 length개는 SMA로 초기화
    if len(df) >= length:
        atr.iloc[length-1] = tr.iloc[:length].mean()

        # 이후는 RMA 공식 사용
        for i in range(length, len(df)):
            atr.iloc[i] = (atr.iloc[i-1] * (length - 1) + tr.iloc[i]) / length

    # HL2 (중간 가격)
    hl2 = (df['High'] + df['Low']) / 2

    # Basic Upper/Lower Band
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
                supertrend.iloc[i] = final_up.iloc[i]
            else:
                direction.iloc[i] = -1
                supertrend.iloc[i] = final_dn.iloc[i]
        else:
            prev_dir = direction.iloc[i-1]

            # 현재 Close 기준으로 방향 변경 체크
            if prev_dir == 1:  # 이전이 Uptrend
                if curr_close <= final_up.iloc[i]:
                    # Downtrend로 변경
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = final_dn.iloc[i]
                else:
                    # Uptrend 유지
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = final_up.iloc[i]
            else:  # 이전이 Downtrend
                if curr_close >= final_dn.iloc[i]:
                    # Uptrend로 변경
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = final_up.iloc[i]
                else:
                    # Downtrend 유지
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = final_dn.iloc[i]

    # 컬럼 추가
    df[st_col] = supertrend
    df[dir_col] = direction

    return df


# ============================================================================
# 캔들 데이터 관리
# ============================================================================

class CandleData:
    """캔들 데이터 관리 클래스"""

    def __init__(self, timeframe, max_candles=500):
        self.timeframe = timeframe
        self.max_candles = max_candles
        self.candles = []
        self.df = pd.DataFrame()
        self.first_update = True  # 첫 업데이트 플래그

    def update_from_kline(self, kline):
        """
        웹소켓 kline 데이터 업데이트

        초기 로드 후 첫 웹소켓 데이터:
          - 과거 데이터 마지막 봉과 timestamp 동일 → 교체 (업데이트)

        이후 웹소켓 데이터:
          - 같은 timestamp → 마지막 캔들 업데이트 (진행중 봉)
          - 다른 timestamp → 새 캔들 추가 (새 봉 시작)
        """
        candle = {
            'timestamp': datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC),
            'Open': float(kline['o']),
            'High': float(kline['h']),
            'Low': float(kline['l']),
            'Close': float(kline['c']),
            'Volume': float(kline['v'])
        }

        if self.first_update and self.candles:
            # 첫 업데이트: 마지막 캔들과 비교
            if self.candles[-1]['timestamp'] == candle['timestamp']:
                # 같은 시간 = 과거 마지막 봉 업데이트
                self.candles[-1] = candle
            else:
                # 다른 시간 = 새 봉 추가
                self.candles.append(candle)
                if len(self.candles) > self.max_candles:
                    self.candles.pop(0)
            self.first_update = False
        else:
            # 일반 업데이트
            if self.candles and self.candles[-1]['timestamp'] == candle['timestamp']:
                # 같은 timestamp = 진행중 봉 업데이트
                self.candles[-1] = candle
            else:
                # 새 봉 시작
                self.candles.append(candle)
                # 최대 캔들 수 제한 (FIFO)
                if len(self.candles) > self.max_candles:
                    self.candles.pop(0)

        # DataFrame 업데이트
        if self.candles:
            self.df = pd.DataFrame(self.candles)

    def calculate_indicators(self, suffix=''):
        """SuperTrend 지표 계산"""
        if len(self.df) >= MIN_CANDLES_FOR_INDICATORS:  # 최소 필요 캔들 수
            # ST(12,1) 계산
            self.df = calculate_supertrend(self.df, 12, 1, suffix)
            # ST(12,3) 계산
            self.df = calculate_supertrend(self.df, 12, 3, suffix)

    def get_latest_indicators(self):
        """최신 지표 값 반환"""
        if len(self.df) > 0:
            latest = self.df.iloc[-1]
            return {
                'timestamp': latest['timestamp'],
                'Close': latest['Close'],
                'High': latest['High'],
                'Low': latest['Low'],
                'st_12_1_dir': latest.get(f'st_12_1{self.timeframe}_dir', 0),
                'st_12_3_dir': latest.get(f'st_12_3{self.timeframe}_dir', 0),
                'st_12_1': latest.get(f'st_12_1{self.timeframe}', 0),
                'st_12_3': latest.get(f'st_12_3{self.timeframe}', 0)
            }
        return None


# ============================================================================
# Double SuperTrend 전략
# ============================================================================

class DoubleSuperTrendStrategy:
    """Double SuperTrend 실시간 트레이딩 전략"""

    def __init__(self, client, log_handler):
        self.client = client
        self.log_handler = log_handler

        # 캔들 데이터 관리
        self.candle_5m = CandleData('_5m', max_candles=MAX_5M_CANDLES)
        self.candle_1h = CandleData('_1h', max_candles=MAX_1H_CANDLES)

        # 포지션 상태
        self.position = None
        self.position_side = None  # 'LONG' or 'SHORT'
        self.entry_price = 0
        self.stop_loss_price = 0
        self.take_profit_price = 0
        self.position_size = 0

        # 전략 플래그
        self.buy_set = False
        self.sell_set = False
        self.buy_ready = False
        self.sell_ready = False
        self.after_stop_loss_long = False
        self.after_stop_loss_short = False

        # 정각 시간 캔들 대기 플래그
        self.pending_5m_candle = None
        self.pending_1h_candle = None
        self.waiting_for_hourly = False

        # 설정 (상단 변수 사용)
        self.symbol = SYMBOL
        self.risk_per_trade = RISK_PER_TRADE
        self.lookback_candles = LOOKBACK_CANDLES
        self.initial_stop_pct = INITIAL_STOP_PCT
        self.max_leverage = MAX_LEVERAGE
        self.min_stop_distance = MIN_STOP_DISTANCE

        # CSV 저장
        self.trades_csv_path = TRADES_CSV_PATH

        # 잔고 정보
        self.usdc_balance = 0
        self.capital = 0

    def get_logger(self):
        """일별 로거 반환"""
        return self.log_handler.get_logger()

    async def save_historical_data_to_csv(self):
        """
        과거 데이터 전체를 CSV에 저장 (초기 로드 후 1회 실행)
        prepare_backtest_data.py와 동일한 컬럼 순서
        """
        try:
            # CSV 파일이 이미 있으면 삭제 (새로 시작)
            if os.path.isfile(LIVE_INDICATOR_CSV):
                os.remove(LIVE_INDICATOR_CSV)

            all_rows = []

            # 5분봉 데이터 전체 순회
            for idx, row_5m in self.candle_5m.df.iterrows():
                # 1시간봉 데이터 (1시간 shift 적용)
                target_1h_timestamp = row_5m['timestamp'] + pd.Timedelta(hours=1)

                # 1시간봉에서 해당 timestamp 찾기
                matching_1h = self.candle_1h.df[self.candle_1h.df['timestamp'] == target_1h_timestamp]

                if len(matching_1h) > 0:
                    row_1h = matching_1h.iloc[0]
                else:
                    # 매칭되는 1시간봉이 없으면 가장 가까운 것 사용 (forward fill)
                    # 1시간봉 timestamp가 5분봉보다 이전인 것 중 가장 최근 것
                    earlier_1h = self.candle_1h.df[self.candle_1h.df['timestamp'] <= row_5m['timestamp']]
                    if len(earlier_1h) > 0:
                        row_1h = earlier_1h.iloc[-1]
                    else:
                        continue  # 1시간봉 데이터 없으면 스킵

                # prepare_backtest_data.py와 동일한 컬럼 순서
                row_data = {
                    # 기본 정보
                    'timestamp': row_5m['timestamp'],

                    # 5분봉 OHLCV
                    'Open': row_5m['Open'],
                    'High': row_5m['High'],
                    'Low': row_5m['Low'],
                    'Close': row_5m['Close'],
                    'Volume': row_5m['Volume'],

                    # 5분봉 SuperTrend
                    'st_12_1_5m': row_5m.get('st_12_1_5m', 0),
                    'st_12_1_5m_dir': row_5m.get('st_12_1_5m_dir', 0),
                    'st_12_3_5m': row_5m.get('st_12_3_5m', 0),
                    'st_12_3_5m_dir': row_5m.get('st_12_3_5m_dir', 0),

                    # 1시간봉 OHLC
                    'Open_1h': row_1h['Open'],
                    'High_1h': row_1h['High'],
                    'Low_1h': row_1h['Low'],
                    'Close_1h': row_1h['Close'],

                    # 1시간봉 SuperTrend
                    'st_12_1_1h': row_1h.get('st_12_1_1h', 0),
                    'st_12_1_1h_dir': row_1h.get('st_12_1_1h_dir', 0),
                    'st_12_3_1h': row_1h.get('st_12_3_1h', 0),
                    'st_12_3_1h_dir': row_1h.get('st_12_3_1h_dir', 0)
                }

                all_rows.append(row_data)

            # DataFrame으로 변환 후 저장
            df_all = pd.DataFrame(all_rows)
            df_all.to_csv(LIVE_INDICATOR_CSV, index=False)

        except Exception as e:
            logger = self.get_logger()
            logger.error(f"과거 데이터 CSV 저장 실패: {e}")

    def save_indicators_to_csv(self):
        """
        현재 5분봉 + 1시간봉 지표를 CSV에 append
        prepare_backtest_data.py와 동일한 컬럼 순서
        """
        if len(self.candle_5m.df) == 0:
            return

        try:
            # 최신 5분봉 데이터
            latest_5m = self.candle_5m.df.iloc[-1]

            # 1시간봉 데이터 (1시간 shift 적용)
            # 5분봉 timestamp에서 1시간 뒤의 1시간봉 데이터를 찾음
            target_1h_timestamp = latest_5m['timestamp'] + pd.Timedelta(hours=1)

            # 1시간봉에서 해당 timestamp 찾기
            if len(self.candle_1h.df) > 0:
                matching_1h = self.candle_1h.df[self.candle_1h.df['timestamp'] == target_1h_timestamp]

                if len(matching_1h) > 0:
                    latest_1h = matching_1h.iloc[0]
                else:
                    # 매칭되는 1시간봉이 없으면 가장 최근 것 사용
                    latest_1h = self.candle_1h.df.iloc[-1]
            else:
                return

            # prepare_backtest_data.py와 동일한 컬럼 순서
            row_data = {
                # 기본 정보
                'timestamp': latest_5m['timestamp'],

                # 5분봉 OHLCV
                'Open': latest_5m['Open'],
                'High': latest_5m['High'],
                'Low': latest_5m['Low'],
                'Close': latest_5m['Close'],
                'Volume': latest_5m['Volume'],

                # 5분봉 SuperTrend
                'st_12_1_5m': latest_5m.get('st_12_1_5m', 0),
                'st_12_1_5m_dir': latest_5m.get('st_12_1_5m_dir', 0),
                'st_12_3_5m': latest_5m.get('st_12_3_5m', 0),
                'st_12_3_5m_dir': latest_5m.get('st_12_3_5m_dir', 0),

                # 1시간봉 OHLC
                'Open_1h': latest_1h['Open'],
                'High_1h': latest_1h['High'],
                'Low_1h': latest_1h['Low'],
                'Close_1h': latest_1h['Close'],

                # 1시간봉 SuperTrend
                'st_12_1_1h': latest_1h.get('st_12_1_1h', 0),
                'st_12_1_1h_dir': latest_1h.get('st_12_1_1h_dir', 0),
                'st_12_3_1h': latest_1h.get('st_12_3_1h', 0),
                'st_12_3_1h_dir': latest_1h.get('st_12_3_1h_dir', 0)
            }

            # CSV에 append
            df_row = pd.DataFrame([row_data])
            df_row.to_csv(
                LIVE_INDICATOR_CSV,
                mode='a',
                header=False,  # append 모드에서는 헤더 없이
                index=False
            )

        except Exception as e:
            logger = self.get_logger()
            logger.error(f"CSV 저장 실패: {e}")

    async def load_historical_data(self):
        """과거 데이터 로드 및 초기 지표 계산"""
        logger = self.get_logger()
        logger.info("📊 과거 데이터 로드 시작...")

        try:
            # 5분봉 데이터 로드 (501개 → 마지막 미완성 봉 제외 = 500개)
            klines_5m = self.client.futures_klines(
                symbol=self.symbol,
                interval='5m',
                limit=501
            )

            # 마지막 캔들(미완성) 제외하고 저장
            for kline in klines_5m[:-1]:  # 마지막 제외
                candle = {
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                    'Open': float(kline[1]),
                    'High': float(kline[2]),
                    'Low': float(kline[3]),
                    'Close': float(kline[4]),
                    'Volume': float(kline[5])
                }
                self.candle_5m.candles.append(candle)

            self.candle_5m.df = pd.DataFrame(self.candle_5m.candles)
            self.candle_5m.calculate_indicators('_5m')
            logger.info(f"✅ 5분봉 로드 완료: {len(self.candle_5m.df)}개 (마지막 미완성 봉 제외)")

            # 1시간봉 데이터 로드 (201개 → 마지막 미완성 봉 제외 = 200개)
            klines_1h = self.client.futures_klines(
                symbol=self.symbol,
                interval='1h',
                limit=201
            )

            # 마지막 캔들(미완성) 제외하고 저장
            for kline in klines_1h[:-1]:  # 마지막 제외
                candle = {
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                    'Open': float(kline[1]),
                    'High': float(kline[2]),
                    'Low': float(kline[3]),
                    'Close': float(kline[4]),
                    'Volume': float(kline[5])
                }
                self.candle_1h.candles.append(candle)

            self.candle_1h.df = pd.DataFrame(self.candle_1h.candles)
            self.candle_1h.calculate_indicators('_1h')
            logger.info(f"✅ 1시간봉 로드 완료: {len(self.candle_1h.df)}개 (마지막 미완성 봉 제외)")

            # 과거 데이터 전체를 CSV에 저장
            logger.info("📝 과거 데이터 CSV 저장 시작...")
            await self.save_historical_data_to_csv()
            logger.info(f"✅ 과거 데이터 CSV 저장 완료: {len(self.candle_5m.df)}개 행")

        except Exception as e:
            logger.error(f"❌ 과거 데이터 로드 실패: {e}")
            raise

    def update_5m_flags(self):
        """5분봉 SuperTrend 플래그 업데이트"""
        if len(self.candle_5m.df) < 2:
            return

        latest = self.candle_5m.df.iloc[-1]
        st_12_1_dir = latest.get('st_12_1_5m_dir', 0)
        st_12_3_dir = latest.get('st_12_3_5m_dir', 0)

        both_long = (st_12_1_dir == 1) and (st_12_3_dir == 1)
        both_short = (st_12_1_dir == -1) and (st_12_3_dir == -1)

        # 백테스트와 동일한 로직
        if both_short:
            # 두 ST가 모두 SHORT
            if not self.buy_set:
                self.buy_set = True
                self.buy_ready = False  # ready 리셋

        elif both_long:
            # 두 ST가 모두 LONG
            if self.buy_set:
                # SHORT 상태였다가 LONG으로 전환 = LONG 진입 신호
                self.buy_ready = True
                self.buy_set = False
                self.sell_set = True  # 이제 SHORT 진입 준비

            elif not self.sell_set:
                # 처음 LONG 상태
                self.sell_set = True
                self.sell_ready = False

        # SHORT 진입 신호
        if both_short and self.sell_set:
            # LONG 상태였다가 SHORT로 전환 = SHORT 진입 신호
            self.sell_ready = True
            self.sell_set = False
            self.buy_set = True  # 이제 LONG 진입 준비

    def check_1h_alignment(self):
        """1시간봉 SuperTrend 정렬 확인"""
        if len(self.candle_1h.df) == 0:
            return 'NEUTRAL'

        latest = self.candle_1h.df.iloc[-1]
        st_12_1_dir = latest.get('st_12_1_1h_dir', 0)
        st_12_3_dir = latest.get('st_12_3_1h_dir', 0)

        if st_12_1_dir == 1 and st_12_3_dir == 1:
            return 'LONG'
        elif st_12_1_dir == -1 and st_12_3_dir == -1:
            return 'SHORT'
        else:
            return 'NEUTRAL'

    def calculate_stop_loss(self, direction):
        """손절가 계산"""
        if len(self.candle_5m.df) < self.lookback_candles:
            # 데이터 부족 시 고정 손절
            current_price = self.candle_5m.df.iloc[-1]['Close']
            if direction == 'LONG':
                return current_price * (1 - self.initial_stop_pct)
            else:
                return current_price * (1 + self.initial_stop_pct)

        # 최근 30개 캔들 기준
        recent_candles = self.candle_5m.df.iloc[-self.lookback_candles:]

        if direction == 'LONG':
            return recent_candles['Low'].min()
        else:
            return recent_candles['High'].max()

    def calculate_position_size(self, entry_price, stop_price):
        """포지션 크기 계산"""
        # 손절 거리 (%)
        stop_distance_pct = abs(entry_price - stop_price) / entry_price

        # 손절 거리가 너무 작으면 진입 안함
        if stop_distance_pct < self.min_stop_distance:
            return 0

        # 리스크 기반 포지션 크기
        risk_amount = self.capital * self.risk_per_trade
        position_value = risk_amount / stop_distance_pct
        position_size = position_value / entry_price

        # 필요 레버리지 계산
        required_leverage = position_value / self.capital

        # 최대 레버리지 초과 시 포지션 축소
        if required_leverage > self.max_leverage:
            position_value = self.capital * self.max_leverage
            position_size = position_value / entry_price

        return position_size

    async def check_entry_signal(self):
        """진입 신호 확인"""
        # 이미 포지션이 있으면 패스
        if self.position is not None:
            return

        # 1시간봉 정렬 확인
        h1_alignment = self.check_1h_alignment()

        if h1_alignment == 'NEUTRAL':
            return

        # 5분봉 상태 확인
        latest_5m = self.candle_5m.df.iloc[-1] if len(self.candle_5m.df) > 0 else None
        if latest_5m is None:
            return

        st_12_1_5m_dir = latest_5m.get('st_12_1_5m_dir', 0)
        st_12_3_5m_dir = latest_5m.get('st_12_3_5m_dir', 0)
        both_long_5m = (st_12_1_5m_dir == 1) and (st_12_3_5m_dir == 1)
        both_short_5m = (st_12_1_5m_dir == -1) and (st_12_3_5m_dir == -1)

        entry_price = latest_5m['Close']

        # LONG 진입 조건
        if h1_alignment == 'LONG':
            # 일반 진입: buy_ready
            if self.buy_ready:
                await self.open_position('LONG', entry_price)
            # 손절 후 재진입: 5분봉 두 ST 모두 BUY
            elif self.after_stop_loss_long and both_long_5m:
                await self.open_position('LONG', entry_price)

        # SHORT 진입 조건
        elif h1_alignment == 'SHORT':
            # 일반 진입: sell_ready
            if self.sell_ready:
                await self.open_position('SHORT', entry_price)
            # 손절 후 재진입: 5분봉 두 ST 모두 SELL
            elif self.after_stop_loss_short and both_short_5m:
                await self.open_position('SHORT', entry_price)

    async def open_position(self, direction, entry_price):
        """포지션 진입"""
        logger = self.get_logger()

        try:
            # 손절가 계산
            stop_price = self.calculate_stop_loss(direction)

            # 손절가가 불리한 경우 진입 안함
            if direction == 'LONG' and stop_price >= entry_price:
                logger.warning(f"⚠️ LONG 진입 취소: 손절가({stop_price}) >= 진입가({entry_price})")
                return
            elif direction == 'SHORT' and stop_price <= entry_price:
                logger.warning(f"⚠️ SHORT 진입 취소: 손절가({stop_price}) <= 진입가({entry_price})")
                return

            # 포지션 크기 계산
            position_size = self.calculate_position_size(entry_price, stop_price)

            if position_size <= 0:
                logger.warning(f"⚠️ 진입 취소: 포지션 크기 0")
                return

            # 익절가 계산 (1:1 risk/reward)
            if direction == 'LONG':
                risk = entry_price - stop_price
                take_profit_price = entry_price + risk
                side = SIDE_BUY
            else:
                risk = stop_price - entry_price
                take_profit_price = entry_price - risk
                side = SIDE_SELL

            # Isolated 마진 모드 설정
            try:
                self.client.futures_change_margin_type(symbol=self.symbol, marginType='ISOLATED')
                logger.info(f"Margin mode set to ISOLATED")
            except Exception as e:
                # 이미 ISOLATED 모드인 경우 에러 무시
                if 'No need to change margin type' not in str(e):
                    logger.warning(f"Margin type change: {e}")

            # 레버리지 설정
            leverage = min(int(position_size * entry_price / self.capital) + 1, self.max_leverage)
            try:
                self.client.futures_change_leverage(symbol=self.symbol, leverage=leverage)
                logger.info(f"Leverage set to {leverage}x")
            except Exception as e:
                logger.error(f"Failed to set leverage: {e}")
                return

            # 주문 수량 계산
            quantity = round(position_size, 3)
            if quantity < 0.001:
                logger.warning(f"Quantity too small: {quantity}")
                return

            # 실제 바이낸스 주문 실행
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

            # 포지션 정보 저장
            self.position = {
                'side': direction,
                'entry_price': entry_price,
                'entry_time': datetime.now(pytz.UTC),
                'stop_price': stop_price,
                'target_price': take_profit_price,
                'quantity': quantity,
                'leverage': leverage,
                'order_id': order['orderId']
            }

            # 이전 정보들도 유지 (하위 호환성)
            self.position_side = direction
            self.entry_price = entry_price
            self.stop_loss_price = stop_price
            self.take_profit_price = take_profit_price
            self.position_size = quantity

            # 손절 STOP_MARKET 주문 설정
            await self.set_stop_loss_order()

            # 플래그 리셋
            self.buy_ready = False
            self.sell_ready = False
            self.after_stop_loss_long = False
            self.after_stop_loss_short = False

            entry_msg = f"✅ {direction} 포지션 진입: 가격=${entry_price:.2f}, 크기={quantity:.4f} BTC, 손절=${stop_price:.2f}, 익절=${take_profit_price:.2f}, Lev={leverage}x"
            logger.info(entry_msg)
            print(entry_msg)

            # CSV 기록
            self.save_trade_to_csv('OPEN', direction, entry_price, quantity, 0)

        except Exception as e:
            logger.error(f"❌ 포지션 진입 실패: {e}")

    async def set_stop_loss_order(self):
        """손절 STOP_MARKET 주문 설정"""
        if not self.position:
            return

        logger = self.get_logger()
        stop_price = round(self.position['stop_price'], 1)

        try:
            if self.position['side'] == 'LONG':
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=SIDE_SELL,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )
            else:  # SHORT
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=SIDE_BUY,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )

            logger.info(f"🛑 Stop loss order placed at ${stop_price:.1f}")

        except Exception as e:
            logger.error(f"Failed to set stop loss: {e}")

    async def cancel_pending_orders(self):
        """대기 주문 취소"""
        logger = self.get_logger()
        try:
            self.client.futures_cancel_all_open_orders(symbol=self.symbol)
            logger.info("✅ 대기 주문 취소 완료")
        except Exception as e:
            logger.warning(f"Failed to cancel orders: {e}")

    async def sync_capital(self):
        """자본 동기화"""
        await self.update_account_info()

    async def save_trade_record(self, exit_type, exit_price):
        """거래 기록 저장"""
        if self.position is None:
            return

        # PnL 계산
        if self.position['side'] == 'LONG':
            pnl = (exit_price - self.position['entry_price']) * self.position['quantity']
        else:
            pnl = (self.position['entry_price'] - exit_price) * self.position['quantity']

        # CSV 저장
        self.save_trade_to_csv(exit_type, self.position['side'], exit_price, self.position['quantity'], pnl)

    async def monitor_positions(self):
        """바이낸스 포지션 상태 주기적 확인 (5초마다)"""
        while True:
            try:
                await asyncio.sleep(5)

                if self.position is None:
                    continue

                # 바이낸스 실제 포지션 확인
                positions = self.client.futures_position_information(symbol=self.symbol)

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
                    logger = self.get_logger()

                    # 손절인지 익절인지 판단
                    if actual_pnl < 0:
                        reason = "STOP_LOSS"
                        exit_price = self.position['stop_price']  # 손절가로 추정
                        # 손절 후 플래그 설정
                        if self.position['side'] == 'LONG':
                            self.after_stop_loss_long = True
                        else:
                            self.after_stop_loss_short = True
                    else:
                        reason = "TAKE_PROFIT"
                        exit_price = self.position['target_price']  # 익절가로 추정

                    logger.info(f"💰 {self.position['side']} {reason}, PnL: ${actual_pnl:.2f} (바이낸스 자동 청산)")

                    # 자본 동기화 먼저
                    await self.sync_capital()

                    # 거래 기록 저장
                    await self.save_trade_record(reason, exit_price)

                    # 모든 대기 주문 취소
                    await self.cancel_pending_orders()

                    # 포지션 초기화
                    self.position = None
                    self.position_side = None
                    self.entry_price = 0
                    self.stop_loss_price = 0
                    self.take_profit_price = 0
                    self.position_size = 0

                    # 5분봉 상태 확인하여 플래그 업데이트
                    self.update_5m_flags()

            except Exception as e:
                logger = self.get_logger()
                logger.error(f"Position monitoring error: {e}")

    async def check_exit_conditions(self):
        """청산 모니터링 (로그만 남김, 실제 청산은 STOP_MARKET이 처리)"""
        if self.position is None:
            return

        latest_5m = self.candle_5m.df.iloc[-1] if len(self.candle_5m.df) > 0 else None
        if latest_5m is None:
            return

        logger = self.get_logger()
        high = latest_5m['High']
        low = latest_5m['Low']

        # 익절 조건만 체크 (손절은 STOP_MARKET이 처리)
        if self.position_side == 'LONG':
            # 손절 가격 도달 감지 (로그만)
            if low <= self.stop_loss_price:
                logger.info(f"🛑 LONG 손절 가격 도달: Low ${low:.2f} (Stop: ${self.stop_loss_price:.2f})")

            # 익절 조건: 1:1 도달 + ST 반전
            elif high >= self.take_profit_price:
                st_12_1_dir = latest_5m.get('st_12_1_5m_dir', 0)
                if st_12_1_dir == -1:
                    # 익절 실행
                    exit_price = max(latest_5m['Close'], self.take_profit_price)
                    await self.close_position_manual('TAKE_PROFIT', exit_price)
                else:
                    logger.info(f"🎯 LONG 익절 가격 도달 (${high:.2f}) 하지만 ST 반전 대기중...")

        else:  # SHORT
            # 손절 가격 도달 감지 (로그만)
            if high >= self.stop_loss_price:
                logger.info(f"🛑 SHORT 손절 가격 도달: High ${high:.2f} (Stop: ${self.stop_loss_price:.2f})")

            # 익절 조건: 1:1 도달 + ST 반전
            elif low <= self.take_profit_price:
                st_12_1_dir = latest_5m.get('st_12_1_5m_dir', 0)
                if st_12_1_dir == 1:
                    # 익절 실행
                    exit_price = min(latest_5m['Close'], self.take_profit_price)
                    await self.close_position_manual('TAKE_PROFIT', exit_price)
                else:
                    logger.info(f"🎯 SHORT 익절 가격 도달 (${low:.2f}) 하지만 ST 반전 대기중...")

    async def close_position_manual(self, exit_type, exit_price):
        """수동 포지션 청산 (익절용)"""
        logger = self.get_logger()

        if self.position is None:
            return

        try:
            # 포지션 청산 주문
            if self.position_side == 'LONG':
                side = SIDE_SELL
                pnl = (exit_price - self.entry_price) * self.position_size
            else:
                side = SIDE_BUY
                pnl = (self.entry_price - exit_price) * self.position_size

            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=round(self.position_size, 3)
            )

            logger.info(f"✅ 포지션 익절 청산: 가격=${exit_price:.2f}, PnL=${pnl:.2f}")

            # 자본 동기화
            await self.sync_capital()

            # 거래 기록 저장
            await self.save_trade_record(exit_type, exit_price)

            # 모든 대기 주문 취소 (STOP_MARKET 포함)
            await self.cancel_pending_orders()

            # 포지션 초기화
            self.position = None
            self.position_side = None
            self.entry_price = 0
            self.stop_loss_price = 0
            self.take_profit_price = 0
            self.position_size = 0

            # 5분봉 상태 확인하여 플래그 업데이트
            self.update_5m_flags()

        except Exception as e:
            logger.error(f"❌ 포지션 청산 실패: {e}")

    def save_trade_to_csv(self, trade_type, direction, price, size, pnl):
        """거래 내역 CSV 저장"""
        try:
            file_exists = os.path.isfile(self.trades_csv_path)

            with open(self.trades_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)

                if not file_exists:
                    writer.writerow(['timestamp', 'type', 'direction', 'price', 'size', 'pnl', 'balance'])

                writer.writerow([
                    datetime.now(pytz.UTC).isoformat(),
                    trade_type,
                    direction,
                    price,
                    size,
                    pnl,
                    self.capital
                ])

        except Exception as e:
            logger = self.get_logger()
            logger.error(f"CSV 저장 실패: {e}")

    async def update_account_info(self):
        """계좌 정보 업데이트"""
        try:
            account = self.client.futures_account()

            # USDC 잔고 찾기
            for asset in account['assets']:
                if asset['asset'] == 'USDC':
                    self.usdc_balance = float(asset['walletBalance'])
                    self.capital = float(asset['availableBalance'])
                    break

        except Exception as e:
            logger = self.get_logger()
            logger.error(f"계좌 정보 업데이트 실패: {e}")

    def is_hourly_time(self, timestamp):
        """정각 시간인지 확인 (분이 0인지)"""
        return timestamp.minute == 0

    async def process_both_candles(self):
        """5분봉 + 1시간봉 둘 다 도착 후 처리"""
        logger = self.get_logger()

        # 캔들 데이터 업데이트
        self.candle_5m.update_from_kline(self.pending_5m_candle)
        self.candle_1h.update_from_kline(self.pending_1h_candle)

        # 지표 계산
        self.candle_5m.calculate_indicators('_5m')
        self.candle_1h.calculate_indicators('_1h')

        logger.info("✅ 정각 시간: 5분봉 + 1시간봉 모두 처리 완료")

        # 플래그 업데이트
        self.update_5m_flags()

        # 진입 신호 체크
        await self.check_entry_signal()

        # 청산 조건 체크
        await self.check_exit_conditions()

        # CSV 저장 (prepare_backtest_data.py와 동일한 형식)
        self.save_indicators_to_csv()

        # 대기 플래그 리셋
        self.pending_5m_candle = None
        self.pending_1h_candle = None
        self.waiting_for_hourly = False

    async def on_5m_candle_close(self, kline):
        """5분봉 종료 시 처리"""
        logger = self.get_logger()

        # 정각 시간인지 확인
        candle_time = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)

        if self.is_hourly_time(candle_time):
            # 정각 시간: 1시간봉 대기
            self.pending_5m_candle = kline
            self.waiting_for_hourly = True
            logger.info(f"⏳ 정각 {candle_time.strftime('%H:%M')} - 1시간봉 대기 중...")

            # 1시간봉이 이미 도착했으면 즉시 처리
            if self.pending_1h_candle is not None:
                await self.process_both_candles()
        else:
            # 일반 5분봉 처리
            self.candle_5m.update_from_kline(kline)
            self.candle_5m.calculate_indicators('_5m')

            # 플래그 업데이트
            self.update_5m_flags()

            # 진입 신호 체크
            await self.check_entry_signal()

            # 청산 조건 체크
            await self.check_exit_conditions()

            # CSV 저장
            self.save_indicators_to_csv()

    async def on_1h_candle_close(self, kline):
        """1시간봉 종료 시 처리"""
        logger = self.get_logger()

        if self.waiting_for_hourly:
            # 5분봉이 대기 중
            self.pending_1h_candle = kline
            logger.info(f"⏳ 1시간봉 도착 - 5분봉과 함께 처리")

            # 5분봉이 이미 도착했으면 즉시 처리
            if self.pending_5m_candle is not None:
                await self.process_both_candles()
        else:
            # 일반 1시간봉 처리 (5분봉 대기 없음)
            self.candle_1h.update_from_kline(kline)
            self.candle_1h.calculate_indicators('_1h')

            # 진입 신호 체크 (1시간봉 정렬이 바뀌었을 수 있음)
            await self.check_entry_signal()


# ============================================================================
# 웹소켓 스트림 처리
# ============================================================================

async def stream_handler(strategy):
    """웹소켓 스트림 핸들러"""
    logger = strategy.get_logger()

    # 스트림 URL
    stream_url = f"wss://fstream.binance.com/stream?streams={strategy.symbol.lower()}@kline_5m/{strategy.symbol.lower()}@kline_1h"

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info("🔗 웹소켓 연결 성공")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if 'data' in data:
                        stream_data = data['data']
                        kline = stream_data['k']

                        # 캔들 종료 확인
                        if kline['x']:  # 캔들 종료
                            interval = kline['i']

                            if interval == '5m':
                                await strategy.on_5m_candle_close(kline)
                            elif interval == '1h':
                                await strategy.on_1h_candle_close(kline)

        except Exception as e:
            logger.error(f"웹소켓 에러: {e}")
            await asyncio.sleep(WS_RECONNECT_DELAY)


# ============================================================================
# 메인 실행
# ============================================================================

async def main():
    """메인 실행 함수"""
    logger = daily_log_handler.get_logger()
    logger.info("=" * 80)
    logger.info("🚀 Double SuperTrend Strategy 시작")
    logger.info("=" * 80)

    # Binance 클라이언트 생성
    client = Client(Config.API_KEY, Config.API_SECRET)

    # 전략 인스턴스 생성
    strategy = DoubleSuperTrendStrategy(client, daily_log_handler)

    # 과거 데이터 로드
    await strategy.load_historical_data()

    # 계좌 정보 업데이트
    await strategy.update_account_info()
    logger.info(f"💰 계좌 잔고: {strategy.capital:.2f} USDC")

    # 초기 플래그 설정
    strategy.update_5m_flags()

    # 포지션 모니터링 태스크 시작
    monitor_task = asyncio.create_task(strategy.monitor_positions())
    logger.info("🔍 포지션 모니터링 시작 (5초 간격)")

    # 웹소켓 스트림 시작
    try:
        await stream_handler(strategy)
    finally:
        # 정리 작업
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger = daily_log_handler.get_logger()
        logger.info("\n👋 프로그램 종료")
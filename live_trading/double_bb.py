#!/usr/bin/env python3
"""
Double Bollinger Band Strategy 실시간 자동매매 프로그램
Binance Futures BTCUSDC Perpetual 거래용
5분봉 기준 BB(20,2) + BB(4,4) 동시 터치 전략
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
from config import Config

# ============================================================================
# 전략 설정 (config.py에서 관리)
# ============================================================================

# Bollinger Band 설정 (고정값)
BB_SETTINGS = [
    {'length': 20, 'std': 2, 'suffix': '20_2'},  # BB(20,2)
    {'length': 4, 'std': 4, 'suffix': '4_4'}     # BB(4,4)
]

# 로깅 설정
os.makedirs(Config.LOGS_DIR, exist_ok=True)
os.makedirs('trade_results', exist_ok=True)
os.makedirs('live_data', exist_ok=True)
os.makedirs('tick_data', exist_ok=True)


class DailyLogHandler:
    def __init__(self, strategy_name):
        self.strategy_name = strategy_name
        self.current_date = None
        self.logger = None
        self.tick_logger = None
        self.setup_logger()

    def setup_logger(self):
        today = datetime.now(pytz.timezone('UTC')).strftime('%Y-%m-%d')
        if today != self.current_date:
            self.current_date = today
            log_filename = f'{Config.LOGS_DIR}/{self.strategy_name}_{today}.log'
            tick_log_filename = f'tick_data/tick_data_{today}.log'

            # 기존 로거 설정
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

            # 틱데이터 전용 로거 설정
            if self.tick_logger:
                for handler in self.tick_logger.handlers[:]:
                    handler.close()
                    self.tick_logger.removeHandler(handler)

            self.tick_logger = logging.getLogger(f'tick_data_{today}')
            self.tick_logger.setLevel(logging.INFO)
            self.tick_logger.handlers.clear()

            tick_file_handler = logging.FileHandler(tick_log_filename)
            tick_file_handler.setFormatter(logging.Formatter('%(asctime)s.%(msecs)03d - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            self.tick_logger.addHandler(tick_file_handler)

            self.tick_logger.info(f"# Tick Data Log - {today}")
            self.tick_logger.info(f"# Format: timestamp | price | quantity | trade_time | event_time")

    def get_logger(self):
        self.setup_logger()
        return self.logger

    def get_tick_logger(self):
        self.setup_logger()
        return self.tick_logger


# 전역 로그 핸들러 생성
daily_log_handler = DailyLogHandler('double_st_strategy_btcusdc')
logger = daily_log_handler.get_logger()


# ============================================================================
# Bollinger Band 지표 계산
# ============================================================================

def calculate_bollinger_band(df, length, std_dev, suffix=''):
    """
    TradingView 표준 Bollinger Band 계산

    Parameters:
    - df: OHLC 데이터프레임
    - length: SMA 기간 (20 또는 4)
    - std_dev: 표준편차 배수 (2 또는 4)
    - suffix: 컬럼명 suffix (예: '20_2', '4_4')

    Returns:
    - df with Bollinger Band columns added
    """
    df = df.copy()

    # SMA 계산
    sma = df['Close'].rolling(window=length).mean()

    # 표준편차 계산 (TradingView 표준: population std, ddof=0)
    std = df['Close'].rolling(window=length).std(ddof=0)

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

def calculate_all_bollinger_bands(df):
    """
    모든 Bollinger Band 지표 계산
    BB(20,2) and BB(4,4)
    """
    for setting in BB_SETTINGS:
        df = calculate_bollinger_band(
            df,
            length=setting['length'],
            std_dev=setting['std'],
            suffix=setting['suffix']
        )
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
        웹소켓 kline 데이터 업데이트 (증분 방식)

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

        is_new_candle = False

        if self.first_update and self.candles:
            # 첫 업데이트: 마지막 캔들과 비교
            if self.candles[-1]['timestamp'] == candle['timestamp']:
                # 같은 시간 = 과거 마지막 봉 업데이트
                self.candles[-1] = candle
                # DataFrame 마지막 행 업데이트
                if len(self.df) > 0:
                    for key, value in candle.items():
                        self.df.at[self.df.index[-1], key] = value
            else:
                # 다른 시간 = 새 봉 추가
                self.candles.append(candle)
                if len(self.candles) > self.max_candles:
                    self.candles.pop(0)
                    # DataFrame도 첫 행 제거
                    self.df = self.df.iloc[1:].reset_index(drop=True)

                # DataFrame에 새 행 추가
                new_row = pd.DataFrame([candle])
                self.df = pd.concat([self.df, new_row], ignore_index=True)
                is_new_candle = True

            self.first_update = False
        else:
            # 일반 업데이트
            if self.candles and self.candles[-1]['timestamp'] == candle['timestamp']:
                # 같은 timestamp = 진행중 봉 업데이트
                self.candles[-1] = candle

                # DataFrame 마지막 행 업데이트 (지표 컬럼은 유지)
                if len(self.df) > 0:
                    for key in ['Open', 'High', 'Low', 'Close', 'Volume', 'timestamp']:
                        if key in candle:
                            self.df.at[self.df.index[-1], key] = candle[key]
            else:
                # 새 봉 시작
                self.candles.append(candle)
                # 최대 캔들 수 제한 (FIFO)
                if len(self.candles) > self.max_candles:
                    self.candles.pop(0)
                    # DataFrame도 첫 행 제거
                    self.df = self.df.iloc[1:].reset_index(drop=True)

                # DataFrame에 새 행 추가
                new_row = pd.DataFrame([candle])
                self.df = pd.concat([self.df, new_row], ignore_index=True)
                is_new_candle = True

        # 새 캔들인 경우에만 전체 재계산 필요 여부 플래그
        self.needs_full_recalc = is_new_candle

    def calculate_indicators(self, suffix=''):
        """Bollinger Band 지표 계산"""
        if len(self.df) >= Config.MIN_CANDLES_FOR_INDICATORS:  # 최소 필요 캔들 수
            # 모든 Bollinger Band 계산
            self.df = calculate_all_bollinger_bands(self.df)

    def get_latest_indicators(self):
        """최신 지표 값 반환"""
        if len(self.df) > 0:
            latest = self.df.iloc[-1]
            return {
                'timestamp': latest['timestamp'],
                'Open': latest['Open'],
                'High': latest['High'],
                'Low': latest['Low'],
                'Close': latest['Close'],
                'bb_upper_20_2': latest.get('bb_upper_20_2', np.nan),
                'bb_lower_20_2': latest.get('bb_lower_20_2', np.nan),
                'bb_upper_4_4': latest.get('bb_upper_4_4', np.nan),
                'bb_lower_4_4': latest.get('bb_lower_4_4', np.nan),
                'bb_sma_20_2': latest.get('bb_sma_20_2', np.nan),
                'bb_sma_4_4': latest.get('bb_sma_4_4', np.nan)
            }
        return None


# ============================================================================
# Double Bollinger Band 전략
# ============================================================================

class DoubleBBStrategy:
    """Double Bollinger Band 실시간 트레이딩 전략"""

    def __init__(self, client, log_handler):
        self.client = client
        self.log_handler = log_handler

        # 캔들 데이터 관리 (5분봉만 사용)
        self.candle_5m = CandleData('_5m', max_candles=Config.MAX_5M_CANDLES)

        # 포지션 상태
        self.position = None
        self.position_side = None  # 'LONG' or 'SHORT'
        self.entry_price = 0
        self.entry_bar_closed = False  # 진입 봉 마감 여부
        self.take_profit_price = 0
        self.position_size = 0
        self.position_value = 0

        # 마지막 터치 추적 (실시간 터치 감지용)
        self.last_bb_touch = {
            'long': {'20_2': False, '4_4': False, 'timestamp': None},
            'short': {'20_2': False, '4_4': False, 'timestamp': None}
        }

        # 타임프레임 동기화
        self.last_candle_time = {'5m': None}

        # 설정 (Config에서 가져오기)
        self.symbol = Config.SYMBOL
        self.leverage = Config.LEVERAGE
        self.position_size_pct = Config.POSITION_SIZE_PCT
        self.take_profit_pct = Config.TAKE_PROFIT_PCT
        self.fee_rate = Config.FEE_RATE

        # CSV 저장
        self.trades_csv_path = Config.TRADES_CSV_PATH

        # 잔고 정보
        self.usdc_balance = 0
        self.capital = 0

    def get_logger(self):
        """일별 로거 반환"""
        return self.log_handler.get_logger()

    async def save_historical_data_to_csv(self):
        """
        과거 데이터 전체를 CSV에 저장 (초기 로드 후 1회 실행)
        prepare_bollinger_data.py와 동일한 컬럼 순서
        """
        try:
            # CSV 파일이 이미 있으면 삭제 (새로 시작)
            if os.path.isfile(Config.LIVE_INDICATOR_CSV):
                os.remove(Config.LIVE_INDICATOR_CSV)

            all_rows = []

            # 5분봉 데이터 전체 순회
            for idx, row_5m in self.candle_5m.df.iterrows():
                # prepare_bollinger_data.py와 동일한 컬럼 순서
                row_data = {
                    # 기본 정보
                    'timestamp': row_5m['timestamp'],

                    # 5분봉 OHLCV
                    'Open': row_5m['Open'],
                    'High': row_5m['High'],
                    'Low': row_5m['Low'],
                    'Close': row_5m['Close'],
                    'Volume': row_5m['Volume'],

                    # Bollinger Band 20/2
                    'bb_upper_20_2': row_5m.get('bb_upper_20_2', np.nan),
                    'bb_lower_20_2': row_5m.get('bb_lower_20_2', np.nan),

                    # Bollinger Band 4/4
                    'bb_upper_4_4': row_5m.get('bb_upper_4_4', np.nan),
                    'bb_lower_4_4': row_5m.get('bb_lower_4_4', np.nan)
                }

                all_rows.append(row_data)

            # DataFrame으로 변환 후 저장
            df_all = pd.DataFrame(all_rows)
            df_all.to_csv(Config.LIVE_INDICATOR_CSV, index=False)

        except Exception as e:
            logger = self.get_logger()
            logger.error(f"과거 데이터 CSV 저장 실패: {e}")

    def save_indicators_to_csv(self):
        """
        현재 5분봉 BB 지표를 CSV에 append
        prepare_bollinger_data.py와 동일한 컬럼 순서
        """
        if len(self.candle_5m.df) == 0:
            return

        try:
            # 최신 5분봉 데이터
            latest_5m = self.candle_5m.df.iloc[-1]

            # prepare_bollinger_data.py와 동일한 컬럼 순서
            row_data = {
                # 기본 정보
                'timestamp': latest_5m['timestamp'],

                # 5분봉 OHLCV
                'Open': latest_5m['Open'],
                'High': latest_5m['High'],
                'Low': latest_5m['Low'],
                'Close': latest_5m['Close'],
                'Volume': latest_5m['Volume'],

                # Bollinger Band 20/2
                'bb_upper_20_2': latest_5m.get('bb_upper_20_2', np.nan),
                'bb_lower_20_2': latest_5m.get('bb_lower_20_2', np.nan),

                # Bollinger Band 4/4
                'bb_upper_4_4': latest_5m.get('bb_upper_4_4', np.nan),
                'bb_lower_4_4': latest_5m.get('bb_lower_4_4', np.nan)
            }

            # CSV에 append
            df_row = pd.DataFrame([row_data])
            df_row.to_csv(
                Config.LIVE_INDICATOR_CSV,
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
            self.candle_5m.calculate_indicators()  # BB 지표 계산
            logger.info(f"✅ 5분봉 로드 완료: {len(self.candle_5m.df)}개 (마지막 미완성 봉 제외)")

            # 초기 last_candle_time 설정
            if len(self.candle_5m.df) > 0:
                self.last_candle_time['5m'] = self.candle_5m.df.iloc[-1]['timestamp']

            logger.info(f"✅ 초기 타임프레임 설정: 5m={self.last_candle_time['5m']}")

            # 과거 데이터 전체를 CSV에 저장
            logger.info("📝 과거 데이터 CSV 저장 시작...")
            await self.save_historical_data_to_csv()
            logger.info(f"✅ 과거 데이터 CSV 저장 완료: {len(self.candle_5m.df)}개 행")

        except Exception as e:
            logger.error(f"❌ 과거 데이터 로드 실패: {e}")
            raise

    def update_bb_status(self):
        """BB 상태 업데이트 및 로깅"""
        if len(self.candle_5m.df) < 2:
            return

        latest = self.candle_5m.get_latest_indicators()
        if latest is None:
            return

        # BB 밴드 간격 확인 (변동성 체크)
        bb_upper_20_2 = latest.get('bb_upper_20_2', np.nan)
        bb_lower_20_2 = latest.get('bb_lower_20_2', np.nan)

        if not pd.isna(bb_upper_20_2) and not pd.isna(bb_lower_20_2):
            band_width = (bb_upper_20_2 - bb_lower_20_2) / latest['Close'] * 100

            # 밴드 폭이 너무 좁으면 로깅 (변동성 낮음)
            if band_width < 0.5:
                logger = self.get_logger()
                logger.debug(f"📉 Low volatility: BB(20,2) width = {band_width:.2f}%")





    async def open_position(self, direction, entry_price):
        """
        포지션 진입
        - 레버리지 10배 고정
        - 익절: 진입가의 0.3%
        - 본절 스탑로스: 다음 봉부터 진입가에 설정
        """
        logger = self.get_logger()

        try:
            # 잔고 확인
            if self.capital <= 0:
                logger.warning(f"⚠️ 진입 취소: 잔고 부족 (${self.capital:.2f})")
                return

            # 포지션 가치 계산 (자본의 100% * 레버리지)
            position_value = self.capital * self.position_size_pct * self.leverage

            # 포지션 크기 계산 (BTC 수량)
            position_size = position_value / entry_price

            # 주문 수량 계산 (소수점 3자리)
            quantity = round(position_size, 3)
            if quantity < 0.001:
                logger.warning(f"⚠️ 진입 취소: 수량 너무 작음 ({quantity})")
                return

            # 익절가 계산 (0.3%)
            if direction == 'LONG':
                take_profit_price = entry_price * (1 + self.take_profit_pct)
                side = SIDE_BUY
            else:
                take_profit_price = entry_price * (1 - self.take_profit_pct)
                side = SIDE_SELL

            # ============================================================
            # 🔇 DRY RUN MODE: 실제 주문 비활성화 (테스트용)
            # ============================================================

            # Isolated 마진 모드 설정 (주석처리)
            # try:
            #     self.client.futures_change_margin_type(symbol=self.symbol, marginType='ISOLATED')
            #     logger.info(f"✔ Margin mode: ISOLATED")
            # except Exception as e:
            #     if 'No need to change margin type' not in str(e):
            #         logger.warning(f"Margin type: {e}")
            logger.info(f"🔇 [DRY RUN] Margin mode: ISOLATED")

            # 레버리지 설정 (주석처리)
            # try:
            #     self.client.futures_change_leverage(symbol=self.symbol, leverage=self.leverage)
            #     logger.info(f"✔ Leverage: {self.leverage}x")
            # except Exception as e:
            #     logger.error(f"❌ 레버리지 설정 실패: {e}")
            #     return
            logger.info(f"🔇 [DRY RUN] Leverage: {self.leverage}x")

            # 실제 바이낸스 주문 실행 (주석처리)
            # order = self.client.futures_create_order(
            #     symbol=self.symbol,
            #     side=side,
            #     type=ORDER_TYPE_MARKET,
            #     quantity=quantity
            # )
            logger.info(f"🔇 [DRY RUN] Market Order: {direction} {quantity:.4f} BTC @ ${entry_price:.2f}")

            # 가짜 주문 ID 생성
            order = {'orderId': f"DRYRUN_{int(datetime.now(pytz.UTC).timestamp() * 1000)}"}

            # 포지션 정보 저장
            self.position = {
                'side': direction,
                'entry_price': entry_price,
                'entry_time': datetime.now(pytz.UTC),
                'entry_bar_closed': False,  # 진입 봉 아직 안 닫힘
                'target_price': take_profit_price,
                'quantity': quantity,
                'position_value': position_value,
                'leverage': self.leverage,
                'order_id': order['orderId']
            }

            # 이전 정보들도 유지 (하위 호환성)
            self.position_side = direction
            self.entry_price = entry_price
            self.take_profit_price = take_profit_price
            self.position_size = quantity
            self.position_value = position_value
            self.entry_bar_closed = False

            # 익절 주문 설정 (지정가)
            await self.set_take_profit_order()

            entry_msg = f"✅ {direction} 진입 완료\n"
            entry_msg += f"   진입가: ${entry_price:.2f}\n"
            entry_msg += f"   수량: {quantity:.4f} BTC\n"
            entry_msg += f"   익절: ${take_profit_price:.2f} ({self.take_profit_pct*100:.1f}%)\n"
            entry_msg += f"   본절: 다음 봉부터 진입가에 활성화\n"
            entry_msg += f"   레버리지: {self.leverage}x"

            logger.info(entry_msg)
            print(entry_msg)

            # CSV 기록
            self.save_trade_to_csv('OPEN', direction, entry_price, quantity, 0)

        except Exception as e:
            logger.error(f"❌ 포지션 진입 실패: {e}")

    async def set_take_profit_order(self):
        """익절 주문 설정 (LIMIT) - DRY RUN"""
        if not self.position:
            return

        logger = self.get_logger()
        tp_price = round(self.position['target_price'], 1)
        quantity = self.position['quantity']

        # ============================================================
        # 🔇 DRY RUN MODE: 실제 주문 비활성화
        # ============================================================

        # try:
        #     if self.position['side'] == 'LONG':
        #         order = self.client.futures_create_order(
        #             symbol=self.symbol,
        #             side=SIDE_SELL,
        #             type='LIMIT',
        #             price=tp_price,
        #             quantity=quantity,
        #             timeInForce='GTC'
        #         )
        #     else:  # SHORT
        #         order = self.client.futures_create_order(
        #             symbol=self.symbol,
        #             side=SIDE_BUY,
        #             type='LIMIT',
        #             price=tp_price,
        #             quantity=quantity,
        #             timeInForce='GTC'
        #         )
        #     logger.info(f"💰 익절 주문 설정: ${tp_price:.1f} ({self.take_profit_pct*100:.1f}%)")
        # except Exception as e:
        #     logger.error(f"익절 주문 설정 실패: {e}")

        logger.info(f"🔇 [DRY RUN] 익절 LIMIT 주문: ${tp_price:.1f} ({self.take_profit_pct*100:.1f}%)")

    async def set_break_even_stop(self):
        """본절 스탑로스 설정 (진입가에 STOP_MARKET) - DRY RUN"""
        if not self.position:
            return

        logger = self.get_logger()
        entry_price = round(self.position['entry_price'], 1)

        # ============================================================
        # 🔇 DRY RUN MODE: 실제 주문 비활성화
        # ============================================================

        try:
            # 기존 주문 취소 (익절 주문 유지, 스탑 주문만 취소/재설정)
            await self.cancel_stop_orders()

            # if self.position['side'] == 'LONG':
            #     order = self.client.futures_create_order(
            #         symbol=self.symbol,
            #         side=SIDE_SELL,
            #         type='STOP_MARKET',
            #         stopPrice=entry_price,
            #         closePosition=True  # 전체 포지션 청산
            #     )
            # else:  # SHORT
            #     order = self.client.futures_create_order(
            #         symbol=self.symbol,
            #         side=SIDE_BUY,
            #         type='STOP_MARKET',
            #         stopPrice=entry_price,
            #         closePosition=True  # 전체 포지션 청산
            #     )

            logger.info(f"🔇 [DRY RUN] 본절 STOP_MARKET 주문: ${entry_price:.1f}")

        except Exception as e:
            logger.error(f"본절 스탑로스 설정 실패: {e}")

    async def cancel_stop_orders(self):
        """STOP 주문만 취소 (익절 LIMIT 주문은 유지) - DRY RUN"""
        logger = self.get_logger()

        # ============================================================
        # 🔇 DRY RUN MODE: 실제 주문 비활성화
        # ============================================================

        try:
            # # 열린 주문 조회
            # open_orders = self.client.futures_get_open_orders(symbol=self.symbol)

            # for order in open_orders:
            #     # STOP_MARKET 주문만 취소
            #     if order['type'] == 'STOP_MARKET':
            #         self.client.futures_cancel_order(
            #             symbol=self.symbol,
            #             orderId=order['orderId']
            #         )
            #         logger.info(f"STOP 주문 취소: ID {order['orderId']}")

            logger.debug(f"🔇 [DRY RUN] STOP 주문 취소 (스킵)")

        except Exception as e:
            logger.warning(f"STOP 주문 취소 실패: {e}")

    async def cancel_pending_orders(self):
        """대기 주문 취소 - DRY RUN"""
        logger = self.get_logger()

        # ============================================================
        # 🔇 DRY RUN MODE: 실제 주문 비활성화
        # ============================================================

        try:
            # self.client.futures_cancel_all_open_orders(symbol=self.symbol)
            logger.info("🔇 [DRY RUN] 대기 주문 취소 (스킵)")
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
        """바이낸스 포지션 상태 주기적 확인 (5초마다) - DRY RUN"""
        logger = self.get_logger()
        logger.info("🔇 [DRY RUN] 포지션 모니터링 비활성화 (실제 거래 없음)")

        # ============================================================
        # 🔇 DRY RUN MODE: 포지션 모니터링 비활성화
        # ============================================================

        # DRY RUN 모드에서는 실제 포지션이 없으므로 모니터링 불필요
        # 단순히 대기 상태 유지
        while True:
            try:
                await asyncio.sleep(30)
                # logger.debug("🔇 [DRY RUN] 포지션 모니터링 스킵")

            except Exception as e:
                logger = self.get_logger()
                logger.error(f"Position monitoring error: {e}")

        # 원래 코드 (주석처리)
        # while True:
        #     try:
        #         await asyncio.sleep(5)
        #
        #         if self.position is None:
        #             continue
        #
        #         # 바이낸스 실제 포지션 확인
        #         positions = self.client.futures_position_information(symbol=self.symbol)
        #
        #         has_position = False
        #         actual_pnl = 0
        #
        #         for pos in positions:
        #             position_amt = float(pos['positionAmt'])
        #             if position_amt != 0:
        #                 has_position = True
        #                 actual_pnl = float(pos['unRealizedProfit'])
        #                 break
        #
        #         # 포지션이 사라졌는데 self.position이 있으면 = 자동 청산됨
        #         if not has_position and self.position is not None:
        #             logger = self.get_logger()
        #
        #             # 손절인지 익절인지 판단
        #             if actual_pnl < 0:
        #                 # 본절인지 진짜 손실인지 확인
        #                 if abs(actual_pnl) < self.position_value * 0.002:  # 수수료 정도면 본절
        #                     reason = "BREAK_EVEN"
        #                     exit_price = self.position['entry_price']
        #                 else:
        #                     reason = "STOP_LOSS"
        #                     exit_price = self.position['entry_price'] * 0.997  # 추정값
        #             else:
        #                 reason = "TAKE_PROFIT"
        #                 exit_price = self.position['target_price']  # 익절가
        #
        #             logger.info(f"💰 {self.position['side']} {reason}, PnL: ${actual_pnl:.2f}")
        #
        #             # 자본 동기화 먼저
        #             await self.sync_capital()
        #
        #             # 거래 기록 저장
        #             await self.save_trade_record(reason, exit_price)
        #
        #             # 모든 대기 주문 취소
        #             await self.cancel_pending_orders()
        #
        #             # 포지션 초기화
        #             self.position = None
        #             self.position_side = None
        #             self.entry_price = 0
        #             self.entry_bar_closed = False
        #             self.take_profit_price = 0
        #             self.position_size = 0
        #             self.position_value = 0
        #
        #     except Exception as e:
        #         logger = self.get_logger()
        #         logger.error(f"Position monitoring error: {e}")

    async def check_candle_close(self):
        """
        새 봉 마감 감지 및 본절 스탑로스 설정
        진입 봉이 마감되면 본절 스탑로스 활성화
        """
        if self.position is None:
            return

        # 진입 봉이 이미 마감됨
        if self.entry_bar_closed:
            return

        # 현재 timestamp
        current_time = self.candle_5m.df.iloc[-1]['timestamp'] if len(self.candle_5m.df) > 0 else None
        if current_time is None:
            return

        # 진입 시간과 다른 봉이면 = 진입 봉 마감됨
        entry_time = self.position['entry_time']
        entry_candle_time = entry_time.replace(minute=(entry_time.minute // 5) * 5, second=0, microsecond=0)

        if current_time > entry_candle_time:
            logger = self.get_logger()
            logger.info(f"📊 진입 봉 마감 확인 - 본절 스탑로스 활성화")

            # 본절 스탑로스 설정
            await self.set_break_even_stop()

            # 플래그 업데이트
            self.entry_bar_closed = True
            self.position['entry_bar_closed'] = True

    async def close_position_manual(self, exit_type, exit_price):
        """수동 포지션 청산 (익절용) - DRY RUN"""
        logger = self.get_logger()

        if self.position is None:
            return

        # ============================================================
        # 🔇 DRY RUN MODE: 실제 주문 비활성화
        # ============================================================

        try:
            # 포지션 청산 주문
            if self.position_side == 'LONG':
                side = SIDE_SELL
                pnl = (exit_price - self.entry_price) * self.position_size
            else:
                side = SIDE_BUY
                pnl = (self.entry_price - exit_price) * self.position_size

            # order = self.client.futures_create_order(
            #     symbol=self.symbol,
            #     side=side,
            #     type=ORDER_TYPE_MARKET,
            #     quantity=round(self.position_size, 3)
            # )

            logger.info(f"🔇 [DRY RUN] 포지션 익절 청산: 가격=${exit_price:.2f}, PnL=${pnl:.2f}")

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
            self.take_profit_price = 0
            self.position_size = 0
            self.position_value = 0
            self.entry_bar_closed = False

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

    async def on_tick(self, trade):
        """
        틱데이터(aggTrade) 처리
        - 실시간 가격으로 BB 터치 감지하여 즉시 진입
        """
        # 틱데이터 로깅 (매번)
        tick_logger = self.log_handler.get_tick_logger()

        # 틱 데이터 파싱
        price = float(trade['p'])
        quantity = float(trade['q'])
        trade_time = datetime.fromtimestamp(trade['T'] / 1000, tz=pytz.UTC)
        event_time = datetime.fromtimestamp(trade['E'] / 1000, tz=pytz.UTC)

        # 현재 시각 (로그 수신 시간)
        receive_time = datetime.now(pytz.UTC)

        # 지연 시간 계산 (ms)
        latency_ms = (receive_time.timestamp() - event_time.timestamp()) * 1000

        # 틱 로그 기록 (상세 정보)
        tick_logger.info(
            f"Price: {price:.2f} | "
            f"Qty: {quantity:.6f} | "
            f"TradeTime: {trade_time.strftime('%H:%M:%S.%f')[:-3]} | "
            f"EventTime: {event_time.strftime('%H:%M:%S.%f')[:-3]} | "
            f"Latency: {latency_ms:.1f}ms"
        )

        if self.position is not None:
            return  # 이미 포지션 있으면 패스

        # 최신 BB 값 (마지막 마감된 봉 기준)
        latest = self.candle_5m.get_latest_indicators()
        if latest is None:
            return

        bb_upper_20_2 = latest.get('bb_upper_20_2')
        bb_lower_20_2 = latest.get('bb_lower_20_2')
        bb_upper_4_4 = latest.get('bb_upper_4_4')
        bb_lower_4_4 = latest.get('bb_lower_4_4')

        # NaN 체크
        if pd.isna(bb_upper_20_2) or pd.isna(bb_lower_20_2) or \
           pd.isna(bb_upper_4_4) or pd.isna(bb_lower_4_4):
            return

        logger = self.get_logger()

        # LONG 진입: 가격이 두 lower band 동시 터치
        if price <= bb_lower_20_2 and price <= bb_lower_4_4:
            entry_price = bb_lower_4_4
            logger.info(f"🔵 LONG 틱터치 감지! - Price: {price:.2f}, BB(20,2): {bb_lower_20_2:.2f}, BB(4,4): {bb_lower_4_4:.2f}")
            await self.open_position('LONG', entry_price)

        # SHORT 진입: 가격이 두 upper band 동시 터치
        elif price >= bb_upper_20_2 and price >= bb_upper_4_4:
            entry_price = bb_upper_4_4
            logger.info(f"🔴 SHORT 틱터치 감지! - Price: {price:.2f}, BB(20,2): {bb_upper_20_2:.2f}, BB(4,4): {bb_upper_4_4:.2f}")
            await self.open_position('SHORT', entry_price)

    async def on_5m_candle_close(self, kline):
        """5분봉 종료 시 처리"""
        logger = self.get_logger()

        # 5분봉 시간
        candle_time = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)

        logger.info(
            f"📊 5m | {candle_time.strftime('%H:%M')} | "
            f"O:{float(kline['o']):.1f} H:{float(kline['h']):.1f} "
            f"L:{float(kline['l']):.1f} C:{float(kline['c']):.1f}"
        )

        # 캔들 데이터 업데이트
        self.candle_5m.update_from_kline(kline)

        # BB 지표 계산
        self.candle_5m.calculate_indicators()

        # 새 봉 체크 (본절 활성화)
        await self.check_candle_close()

        # CSV 저장
        self.save_indicators_to_csv()



# ============================================================================
# 웹소켓 스트림 처리
# ============================================================================

async def stream_handler(strategy):
    """웹소켓 스트림 핸들러 (5분봉 + 틱데이터)"""
    logger = strategy.get_logger()

    # 스트림 URL (Config에서 가져오기)
    stream_url = Config.get_ws_stream_url()

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info("🔗 웹소켓 연결 성공 (5분봉 + 틱데이터)")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if 'data' not in data:
                        continue

                    stream_data = data['data']

                    # 5분봉 데이터
                    if 'k' in stream_data:
                        kline = stream_data['k']

                        # 캔들 종료 시에만 처리 (BB 재계산)
                        if kline['x']:
                            await strategy.on_5m_candle_close(kline)

                    # 틱데이터 (aggTrade)
                    elif 'p' in stream_data and 'q' in stream_data:
                        # 실시간 터치 감지
                        await strategy.on_tick(stream_data)

        except Exception as e:
            logger.error(f"웹소켓 에러: {e}")
            await asyncio.sleep(Config.WS_RECONNECT_DELAY)


# ============================================================================
# 메인 실행
# ============================================================================

async def main():
    """메인 실행 함수"""
    logger = daily_log_handler.get_logger()
    logger.info("=" * 80)
    logger.info("🚀 Double Bollinger Band Strategy 시작")
    logger.info("=" * 80)

    # Binance 클라이언트 생성
    client = Client(Config.API_KEY, Config.API_SECRET)

    # 전략 인스턴스 생성
    strategy = DoubleBBStrategy(client, daily_log_handler)

    # 과거 데이터 로드
    await strategy.load_historical_data()

    # 계좌 정보 업데이트
    await strategy.update_account_info()
    logger.info(f"💰 계좌 잔고: {strategy.capital:.2f} USDC")

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
        print("\n👋 프로그램 종료")

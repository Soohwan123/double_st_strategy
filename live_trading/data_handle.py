#!/usr/bin/env python3
"""
Data Handler Library
지표 계산 및 데이터 관리 모듈

이식성을 위해 전략 로직과 분리된 데이터 처리 모듈
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import os
import csv
import logging
import pytz


# =============================================================================
# Bollinger Band 설정 (기본값)
# =============================================================================

DEFAULT_BB_SETTINGS = [
    {'length': 20, 'std': 2, 'suffix': '20_2', 'source': 'Close'},  # BB(20,2) - 종가 기준
    {'length': 4, 'std': 4, 'suffix': '4_4', 'source': 'Open'}      # BB(4,4) - 시가 기준
]


# =============================================================================
# Bollinger Band 계산 함수
# =============================================================================

def calculate_bollinger_band(
    df: pd.DataFrame,
    length: int,
    std_dev: float,
    suffix: str = '',
    source: str = 'Close'
) -> pd.DataFrame:
    """
    TradingView 표준 Bollinger Band 계산

    Args:
        df: OHLC 데이터프레임 (필수 컬럼: Open, High, Low, Close, Volume)
        length: SMA 기간 (예: 20, 4)
        std_dev: 표준편차 배수 (예: 2, 4)
        suffix: 컬럼명 suffix (예: '20_2', '4_4')
        source: BB 계산에 사용할 가격 소스 ('Close' 또는 'Open')

    Returns:
        Bollinger Band 컬럼이 추가된 데이터프레임
        - bb_sma_{suffix}: 중심선 (SMA)
        - bb_upper_{suffix}: 상단 밴드
        - bb_lower_{suffix}: 하단 밴드
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


def calculate_all_bollinger_bands(
    df: pd.DataFrame,
    settings: Optional[List[Dict]] = None
) -> pd.DataFrame:
    """
    모든 Bollinger Band 지표 계산

    Args:
        df: OHLC 데이터프레임
        settings: BB 설정 리스트 (None이면 기본값 사용)
            [{'length': 20, 'std': 2, 'suffix': '20_2', 'source': 'Close'}, ...]

    Returns:
        모든 BB 컬럼이 추가된 데이터프레임
    """
    if settings is None:
        settings = DEFAULT_BB_SETTINGS

    for setting in settings:
        df = calculate_bollinger_band(
            df,
            length=setting['length'],
            std_dev=setting['std'],
            suffix=setting['suffix'],
            source=setting.get('source', 'Close')
        )

    return df


# =============================================================================
# 캔들 데이터 관리 클래스
# =============================================================================

class CandleDataManager:
    """
    캔들 데이터 관리 클래스

    실시간 웹소켓 데이터와 과거 데이터를 통합 관리

    Usage:
        manager = CandleDataManager(timeframe='5m', max_candles=500)

        # 과거 데이터 로드
        manager.load_historical(candles_list)

        # 웹소켓 kline 업데이트
        is_new = manager.update_from_kline(kline_data)

        # 지표 계산
        manager.calculate_indicators()

        # 최신 지표 조회
        latest = manager.get_latest_indicators()
    """

    def __init__(
        self,
        timeframe: str = '5m',
        max_candles: int = 500,
        bb_settings: Optional[List[Dict]] = None,
        min_candles_for_indicators: int = 20
    ):
        """
        Args:
            timeframe: 타임프레임 ('1m', '5m', '15m' 등)
            max_candles: 보관할 최대 캔들 수
            bb_settings: Bollinger Band 설정
            min_candles_for_indicators: 지표 계산에 필요한 최소 캔들 수
        """
        self.timeframe = timeframe
        self.max_candles = max_candles
        self.bb_settings = bb_settings or DEFAULT_BB_SETTINGS
        self.min_candles_for_indicators = min_candles_for_indicators

        self.candles: List[Dict] = []
        self.df = pd.DataFrame()
        self.first_update = True
        self.needs_full_recalc = False

    def load_historical(self, candles: List[Dict]) -> None:
        """
        과거 캔들 데이터 로드

        Args:
            candles: 캔들 데이터 리스트
                [{'timestamp': datetime, 'Open': float, 'High': float, ...}, ...]
        """
        self.candles = candles.copy()

        # 최대 개수 제한
        if len(self.candles) > self.max_candles:
            self.candles = self.candles[-self.max_candles:]

        self.df = pd.DataFrame(self.candles)
        self.first_update = True

    def update_from_kline(self, kline: Dict) -> bool:
        """
        웹소켓 kline 데이터 업데이트 (증분 방식)

        Args:
            kline: 웹소켓 kline 데이터
                {'t': timestamp_ms, 'o': open, 'h': high, 'l': low, 'c': close, 'v': volume}

        Returns:
            새로운 캔들이 추가되었으면 True
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
                if len(self.df) > 0:
                    for key, value in candle.items():
                        self.df.at[self.df.index[-1], key] = value
            else:
                # 다른 시간 = 새 봉 추가
                self._append_candle(candle)
                is_new_candle = True

            self.first_update = False
        else:
            # 일반 업데이트
            if self.candles and self.candles[-1]['timestamp'] == candle['timestamp']:
                # 같은 timestamp = 진행중 봉 업데이트
                self.candles[-1] = candle
                if len(self.df) > 0:
                    for key in ['Open', 'High', 'Low', 'Close', 'Volume', 'timestamp']:
                        if key in candle:
                            self.df.at[self.df.index[-1], key] = candle[key]
            else:
                # 새 봉 시작
                self._append_candle(candle)
                is_new_candle = True

        self.needs_full_recalc = is_new_candle
        return is_new_candle

    def _append_candle(self, candle: Dict) -> None:
        """캔들 추가 (내부용)"""
        self.candles.append(candle)

        # 최대 캔들 수 제한 (FIFO)
        if len(self.candles) > self.max_candles:
            self.candles.pop(0)
            self.df = self.df.iloc[1:].reset_index(drop=True)

        # DataFrame에 새 행 추가
        new_row = pd.DataFrame([candle])
        self.df = pd.concat([self.df, new_row], ignore_index=True)

    def calculate_indicators(self) -> None:
        """Bollinger Band 지표 계산"""
        if len(self.df) >= self.min_candles_for_indicators:
            self.df = calculate_all_bollinger_bands(self.df, self.bb_settings)

    def get_latest_indicators(self) -> Optional[Dict[str, Any]]:
        """
        최신 지표 값 반환

        Returns:
            지표 딕셔너리 또는 None
        """
        if len(self.df) == 0:
            return None

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

    def get_last_timestamp(self) -> Optional[datetime]:
        """마지막 캔들 타임스탬프 반환"""
        if len(self.df) > 0:
            return self.df.iloc[-1]['timestamp']
        return None


# =============================================================================
# 로그 핸들러 클래스
# =============================================================================

class DailyLogHandler:
    """
    일별 로그 파일 관리 클래스

    매일 자정(UTC)에 새로운 로그 파일 생성

    Usage:
        log_handler = DailyLogHandler('my_strategy', logs_dir='logs')
        logger = log_handler.get_logger()
        logger.info("Hello World")
    """

    def __init__(
        self,
        strategy_name: str,
        logs_dir: str = 'logs',
        log_level: int = logging.INFO
    ):
        """
        Args:
            strategy_name: 전략 이름 (로그 파일명에 사용)
            logs_dir: 로그 디렉토리 경로
            log_level: 로깅 레벨
        """
        self.strategy_name = strategy_name
        self.logs_dir = logs_dir
        self.log_level = log_level
        self.current_date = None
        self.logger = None

        os.makedirs(logs_dir, exist_ok=True)
        self.setup_logger()

    def setup_logger(self) -> None:
        """로거 설정 (날짜 변경 시 새 파일 생성)"""
        today = datetime.now(pytz.timezone('UTC')).strftime('%Y-%m-%d')

        if today != self.current_date:
            self.current_date = today
            log_filename = f'{self.logs_dir}/{self.strategy_name}_{today}.log'

            # 기존 핸들러 정리
            if self.logger:
                for handler in self.logger.handlers[:]:
                    handler.close()
                    self.logger.removeHandler(handler)

            self.logger = logging.getLogger(f'{self.strategy_name}_{today}')
            self.logger.setLevel(self.log_level)
            self.logger.handlers.clear()

            # 로그 파일 생성
            if not os.path.exists(log_filename):
                with open(log_filename, 'w') as f:
                    f.write(f"# {self.strategy_name} Log - {today}\n")

            file_handler = logging.FileHandler(log_filename)
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(file_handler)

            self.logger.info(f"📅 새로운 날짜 로그 파일 시작: {today}")

    def get_logger(self) -> logging.Logger:
        """현재 로거 반환 (날짜 변경 시 자동 갱신)"""
        self.setup_logger()
        return self.logger


# =============================================================================
# CSV 데이터 저장 클래스
# =============================================================================

class DataRecorder:
    """
    거래 및 지표 데이터 CSV 저장 클래스

    Usage:
        recorder = DataRecorder(
            trades_path='trade_results/trades.csv',
            indicators_path='live_data/indicators.csv'
        )

        # 거래 기록
        recorder.save_trade('OPEN', 'LONG', 67000.0, 0.01, 0, 1000.0)

        # 지표 기록
        recorder.save_indicator(indicator_dict)
    """

    def __init__(
        self,
        trades_path: str = 'trade_results/trades.csv',
        indicators_path: str = 'live_data/indicators.csv',
        logger: Optional[logging.Logger] = None
    ):
        """
        Args:
            trades_path: 거래 기록 CSV 경로
            indicators_path: 지표 기록 CSV 경로
            logger: 로거 (None이면 기본 로거 사용)
        """
        self.trades_path = trades_path
        self.indicators_path = indicators_path
        self.logger = logger or logging.getLogger(__name__)

        # 디렉토리 생성
        os.makedirs(os.path.dirname(trades_path), exist_ok=True)
        os.makedirs(os.path.dirname(indicators_path), exist_ok=True)

    def save_trade(
        self,
        trade_type: str,
        direction: str,
        price: float,
        size: float,
        pnl: float,
        balance: float
    ) -> None:
        """
        거래 내역 저장

        Args:
            trade_type: 거래 유형 ('OPEN', 'CLOSE', 'TAKE_PROFIT', 'STOP_LOSS', 'BREAK_EVEN')
            direction: 포지션 방향 ('LONG', 'SHORT')
            price: 거래 가격
            size: 거래 수량
            pnl: 손익 (진입 시 0)
            balance: 현재 잔고
        """
        try:
            file_exists = os.path.isfile(self.trades_path)

            with open(self.trades_path, 'a', newline='') as f:
                writer = csv.writer(f)

                if not file_exists:
                    writer.writerow([
                        'timestamp', 'type', 'direction', 'price', 'size', 'pnl', 'balance'
                    ])

                writer.writerow([
                    datetime.now(pytz.UTC).isoformat(),
                    trade_type,
                    direction,
                    price,
                    size,
                    pnl,
                    balance
                ])

        except Exception as e:
            self.logger.error(f"거래 기록 저장 실패: {e}")

    def save_indicator(self, indicator: Dict[str, Any]) -> None:
        """
        지표 데이터 저장 (append)

        Args:
            indicator: 지표 딕셔너리
        """
        try:
            row_data = {
                'timestamp': indicator.get('timestamp'),
                'Open': indicator.get('Open'),
                'High': indicator.get('High'),
                'Low': indicator.get('Low'),
                'Close': indicator.get('Close'),
                'Volume': indicator.get('Volume', 0),
                'bb_upper_20_2': indicator.get('bb_upper_20_2', np.nan),
                'bb_lower_20_2': indicator.get('bb_lower_20_2', np.nan),
                'bb_upper_4_4': indicator.get('bb_upper_4_4', np.nan),
                'bb_lower_4_4': indicator.get('bb_lower_4_4', np.nan)
            }

            file_exists = os.path.isfile(self.indicators_path)

            df_row = pd.DataFrame([row_data])
            df_row.to_csv(
                self.indicators_path,
                mode='a',
                header=not file_exists,
                index=False
            )

        except Exception as e:
            self.logger.error(f"지표 저장 실패: {e}")

    def save_historical_indicators(self, df: pd.DataFrame) -> None:
        """
        과거 지표 데이터 전체 저장 (덮어쓰기)

        Args:
            df: 지표가 포함된 데이터프레임
        """
        try:
            # 기존 파일 삭제
            if os.path.isfile(self.indicators_path):
                os.remove(self.indicators_path)

            columns = [
                'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
                'bb_upper_20_2', 'bb_lower_20_2', 'bb_upper_4_4', 'bb_lower_4_4'
            ]

            # 존재하는 컬럼만 선택
            available_cols = [c for c in columns if c in df.columns]
            df_save = df[available_cols].copy()
            df_save.to_csv(self.indicators_path, index=False)

        except Exception as e:
            self.logger.error(f"과거 지표 저장 실패: {e}")

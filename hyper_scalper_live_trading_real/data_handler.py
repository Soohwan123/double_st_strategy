#!/usr/bin/env python3
"""
Data Handler for Hyper Scalper V2
15분봉 캔들 데이터 관리 및 지표 계산 모듈

지표:
- EMA 25/100/200
- ADX 14
- ATR 14
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import pytz


class IndicatorCalculator:
    """
    TradingView 호환 지표 계산 클래스
    """

    @staticmethod
    def calculate_ema(series: pd.Series, length: int) -> pd.Series:
        """
        TradingView EMA 계산

        Args:
            series: 가격 시리즈
            length: EMA 기간

        Returns:
            EMA 시리즈
        """
        return series.ewm(span=length, adjust=False).mean()

    @staticmethod
    def calculate_rma(series: pd.Series, length: int) -> pd.Series:
        """
        TradingView RMA (Wilder's Moving Average) 계산

        Args:
            series: 가격 시리즈
            length: RMA 기간

        Returns:
            RMA 시리즈
        """
        alpha = 1.0 / length
        result = np.zeros(len(series))
        result[:] = np.nan

        if len(series) >= length:
            result[length - 1] = series.iloc[:length].mean()
            for i in range(length, len(series)):
                result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]

        return pd.Series(result, index=series.index)

    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
        """
        TradingView ATR 계산 (RMA 기반)

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            length: ATR 기간

        Returns:
            ATR 시리즈
        """
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return IndicatorCalculator.calculate_rma(tr, length)

    @staticmethod
    def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
        """
        TradingView ADX 계산

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            length: ADX 기간

        Returns:
            ADX 시리즈
        """
        # True Range
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm = pd.Series(plus_dm, index=high.index)
        minus_dm = pd.Series(minus_dm, index=high.index)

        # Smoothed with RMA
        atr = IndicatorCalculator.calculate_rma(tr, length)
        plus_di = 100 * IndicatorCalculator.calculate_rma(plus_dm, length) / atr
        minus_di = 100 * IndicatorCalculator.calculate_rma(minus_dm, length) / atr

        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = IndicatorCalculator.calculate_rma(dx, length)

        return adx


class CandleDataManager:
    """
    15분봉 캔들 데이터 관리 클래스

    과거 데이터 로드 + 실시간 업데이트 + 지표 계산

    Usage:
        manager = CandleDataManager(max_candles=300, logger=logger)

        # 과거 데이터 로드
        manager.load_historical(candles_list)

        # 웹소켓 kline 업데이트
        is_closed = manager.update_from_kline(kline_data)

        # 지표 조회
        indicators = manager.get_latest_indicators()
    """

    def __init__(
        self,
        max_candles: int = 300,
        ema_fast: int = 25,
        ema_mid: int = 100,
        ema_slow: int = 200,
        adx_length: int = 14,
        atr_length: int = 14,
        retest_lookback: int = 5,
        sl_lookback: int = 29,
        logger: Optional[logging.Logger] = None
    ):
        """
        Args:
            max_candles: 보관할 최대 캔들 수
            ema_fast: 빠른 EMA 기간
            ema_mid: 중간 EMA 기간
            ema_slow: 느린 EMA 기간
            adx_length: ADX 기간
            atr_length: ATR 기간
            retest_lookback: Retest 확인 봉 수
            sl_lookback: 손절가 계산 봉 수
            logger: 로거
        """
        self.max_candles = max_candles
        self.ema_fast = ema_fast
        self.ema_mid = ema_mid
        self.ema_slow = ema_slow
        self.adx_length = adx_length
        self.atr_length = atr_length
        self.retest_lookback = retest_lookback
        self.sl_lookback = sl_lookback
        self.logger = logger or logging.getLogger(__name__)

        self.df = pd.DataFrame()

        # 증분 EMA 계산용 이전 값 저장
        self._prev_ema_fast = None
        self._prev_ema_mid = None
        self._prev_ema_slow = None

        # EMA alpha 값 미리 계산
        self._alpha_fast = 2.0 / (ema_fast + 1)
        self._alpha_mid = 2.0 / (ema_mid + 1)
        self._alpha_slow = 2.0 / (ema_slow + 1)

    def load_historical(self, candles: List[Dict]) -> None:
        """
        과거 캔들 데이터 로드

        Args:
            candles: 캔들 데이터 리스트
                [{'timestamp': datetime, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}, ...]
        """
        if not candles:
            self.logger.warning("과거 데이터 없음")
            return

        self.df = pd.DataFrame(candles)

        # 컬럼명 소문자 통일
        self.df.columns = self.df.columns.str.lower()

        # 최대 개수 제한
        if len(self.df) > self.max_candles:
            self.df = self.df.tail(self.max_candles).reset_index(drop=True)

        # 지표 계산
        self._calculate_all_indicators()

        # 증분 계산용 이전 EMA 값 저장
        self._save_prev_ema_values()

        self.logger.info(f"과거 데이터 로드 완료: {len(self.df)}개 캔들")

    def update_from_kline(self, kline: Dict) -> bool:
        """
        웹소켓 kline 데이터 업데이트

        Args:
            kline: 웹소켓 kline 데이터
                {'t': timestamp_ms, 'o': open, 'h': high, 'l': low, 'c': close, 'v': volume, 'x': is_closed}

        Returns:
            새로운 봉이 완성되었으면 True
        """
        candle = {
            'timestamp': datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC),
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v'])
        }

        is_closed = kline.get('x', False)

        if len(self.df) == 0:
            # 첫 데이터
            self.df = pd.DataFrame([candle])
            self._calculate_all_indicators()
            return is_closed

        last_timestamp = self.df.iloc[-1]['timestamp']

        # 웹소켓 업데이트
        if last_timestamp == candle['timestamp']:
            # 진행 중인 봉 업데이트
            self._update_last_candle(candle)
            if is_closed:
                # 봉 마감: 증분 방식으로 지표 계산
                self._update_indicators_incremental()
                self._save_prev_ema_values()
        else:
            # 새 봉 시작 (FIFO: _append_candle에서 max_candles 초과 시 자동 제거)
            self._append_candle(candle)
            # 새 봉은 아직 진행 중이므로 지표 계산하지 않음
            # (봉 마감 시에만 증분 계산)

        return is_closed

    def _update_last_candle(self, candle: Dict) -> None:
        """마지막 캔들 업데이트"""
        idx = len(self.df) - 1
        for key in ['open', 'high', 'low', 'close', 'volume', 'timestamp']:
            if key in candle:
                self.df.at[idx, key] = candle[key]

    def _append_candle(self, candle: Dict) -> None:
        """캔들 추가 (FIFO)"""
        new_row = pd.DataFrame([candle])
        self.df = pd.concat([self.df, new_row], ignore_index=True)

        # 최대 캔들 수 제한
        if len(self.df) > self.max_candles:
            self.df = self.df.tail(self.max_candles).reset_index(drop=True)

    def _calculate_all_indicators(self) -> None:
        """모든 지표 계산"""
        if len(self.df) < self.ema_slow:
            return

        # EMA
        self.df['ema_fast'] = IndicatorCalculator.calculate_ema(self.df['close'], self.ema_fast)
        self.df['ema_mid'] = IndicatorCalculator.calculate_ema(self.df['close'], self.ema_mid)
        self.df['ema_slow'] = IndicatorCalculator.calculate_ema(self.df['close'], self.ema_slow)

        # ADX
        self.df['adx'] = IndicatorCalculator.calculate_adx(
            self.df['high'], self.df['low'], self.df['close'], self.adx_length
        )

        # ATR
        self.df['atr'] = IndicatorCalculator.calculate_atr(
            self.df['high'], self.df['low'], self.df['close'], self.atr_length
        )

        # Trend conditions
        self.df['bull_trend'] = (
            (self.df['close'] > self.df['ema_slow']) &
            (self.df['ema_fast'] > self.df['ema_mid']) &
            (self.df['ema_mid'] > self.df['ema_slow'])
        )
        self.df['bear_trend'] = (
            (self.df['close'] < self.df['ema_slow']) &
            (self.df['ema_fast'] < self.df['ema_mid']) &
            (self.df['ema_mid'] < self.df['ema_slow'])
        )

        # Retest logic
        self.df['low_minus_ema_fast'] = self.df['low'] - self.df['ema_fast']
        self.df['had_low_below_fast'] = self.df['low_minus_ema_fast'].rolling(
            window=self.retest_lookback
        ).min() < 0

        self.df['high_minus_ema_fast'] = self.df['high'] - self.df['ema_fast']
        self.df['had_high_above_fast'] = self.df['high_minus_ema_fast'].rolling(
            window=self.retest_lookback
        ).max() > 0

        # Reclaim
        self.df['reclaim_long'] = self.df['close'] > self.df['ema_fast']
        self.df['reclaim_short'] = self.df['close'] < self.df['ema_fast']

    def _save_prev_ema_values(self) -> None:
        """증분 계산용 이전 EMA 값 저장"""
        if len(self.df) == 0:
            return

        last = self.df.iloc[-1]
        self._prev_ema_fast = last.get('ema_fast')
        self._prev_ema_mid = last.get('ema_mid')
        self._prev_ema_slow = last.get('ema_slow')

    def _update_indicators_incremental(self) -> None:
        """
        증분 방식으로 지표 업데이트 (백테스트와 동일)
        - EMA: 이전 값 기반 증분 계산
        - ADX, ATR, 기타: 전체 재계산
        """
        # 이전 값이 없거나 NaN이면 전체 재계산
        if len(self.df) < 2 or self._prev_ema_fast is None or pd.isna(self._prev_ema_fast):
            self.logger.info("[EMA] 전체 재계산 (prev_ema 없음)")
            self._calculate_all_indicators()
            return

        idx = len(self.df) - 1
        curr_close = self.df.iloc[idx]['close']

        # EMA 증분 계산: new_ema = alpha * close + (1-alpha) * prev_ema
        new_ema_fast = self._alpha_fast * curr_close + (1 - self._alpha_fast) * self._prev_ema_fast
        new_ema_mid = self._alpha_mid * curr_close + (1 - self._alpha_mid) * self._prev_ema_mid
        new_ema_slow = self._alpha_slow * curr_close + (1 - self._alpha_slow) * self._prev_ema_slow

        self.logger.info(f"[EMA] 증분계산: prev={self._prev_ema_fast:.2f}, close={curr_close}, new={new_ema_fast:.2f}")

        self.df.at[idx, 'ema_fast'] = new_ema_fast
        self.df.at[idx, 'ema_mid'] = new_ema_mid
        self.df.at[idx, 'ema_slow'] = new_ema_slow

        # ADX, ATR: 전체 재계산 (복잡한 로직이므로)
        self.df['adx'] = IndicatorCalculator.calculate_adx(
            self.df['high'], self.df['low'], self.df['close'], self.adx_length
        )
        self.df['atr'] = IndicatorCalculator.calculate_atr(
            self.df['high'], self.df['low'], self.df['close'], self.atr_length
        )

        # Trend conditions (새 EMA 값 기반)
        self.df.at[idx, 'bull_trend'] = (
            (curr_close > new_ema_slow) and
            (new_ema_fast > new_ema_mid) and
            (new_ema_mid > new_ema_slow)
        )
        self.df.at[idx, 'bear_trend'] = (
            (curr_close < new_ema_slow) and
            (new_ema_fast < new_ema_mid) and
            (new_ema_mid < new_ema_slow)
        )

        # Retest logic (rolling 필요하므로 전체 재계산)
        self.df['low_minus_ema_fast'] = self.df['low'] - self.df['ema_fast']
        self.df['had_low_below_fast'] = self.df['low_minus_ema_fast'].rolling(
            window=self.retest_lookback
        ).min() < 0

        self.df['high_minus_ema_fast'] = self.df['high'] - self.df['ema_fast']
        self.df['had_high_above_fast'] = self.df['high_minus_ema_fast'].rolling(
            window=self.retest_lookback
        ).max() > 0

        # Reclaim
        self.df.at[idx, 'reclaim_long'] = curr_close > new_ema_fast
        self.df.at[idx, 'reclaim_short'] = curr_close < new_ema_fast

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
            'timestamp': latest.get('timestamp'),
            'open': latest.get('open'),
            'high': latest.get('high'),
            'low': latest.get('low'),
            'close': latest.get('close'),
            'ema_fast': latest.get('ema_fast', np.nan),
            'ema_mid': latest.get('ema_mid', np.nan),
            'ema_slow': latest.get('ema_slow', np.nan),
            'adx': latest.get('adx', np.nan),
            'atr': latest.get('atr', np.nan),
            'bull_trend': latest.get('bull_trend', False),
            'bear_trend': latest.get('bear_trend', False),
            'had_low_below_fast': latest.get('had_low_below_fast', False),
            'had_high_above_fast': latest.get('had_high_above_fast', False),
            'reclaim_long': latest.get('reclaim_long', False),
            'reclaim_short': latest.get('reclaim_short', False)
        }

    def get_all_indicators(self) -> Optional[pd.DataFrame]:
        """
        전체 지표 DataFrame 반환 (초기 저장용)

        Returns:
            지표가 포함된 DataFrame 또는 None
        """
        if len(self.df) == 0:
            return None

        # 필요한 컬럼만 선택
        columns = [
            'timestamp', 'open', 'high', 'low', 'close',
            'ema_fast', 'ema_mid', 'ema_slow', 'adx', 'atr',
            'bull_trend', 'bear_trend', 'had_low_below_fast',
            'had_high_above_fast', 'reclaim_long', 'reclaim_short'
        ]

        # 존재하는 컬럼만 필터
        existing_cols = [c for c in columns if c in self.df.columns]
        return self.df[existing_cols].copy()

    def check_long_signal(self, adx_threshold: float = 30.0) -> bool:
        """
        LONG 신호 체크

        조건:
        1. bull_trend: close > EMA200 AND EMA25 > EMA100 > EMA200
        2. strong_trend: ADX >= threshold
        3. had_low_below_fast: 최근 N봉 내 저가가 EMA25 아래였던 적 있음
        4. reclaim_long: 현재 종가 > EMA25

        Returns:
            LONG 신호 여부
        """
        indicators = self.get_latest_indicators()
        if indicators is None:
            return False

        if pd.isna(indicators['adx']) or pd.isna(indicators['atr']):
            return False

        return (
            indicators['bull_trend'] and
            indicators['adx'] >= adx_threshold and
            indicators['had_low_below_fast'] and
            indicators['reclaim_long']
        )

    def check_short_signal(self, adx_threshold: float = 30.0) -> bool:
        """
        SHORT 신호 체크

        조건:
        1. bear_trend: close < EMA200 AND EMA25 < EMA100 < EMA200
        2. strong_trend: ADX >= threshold
        3. had_high_above_fast: 최근 N봉 내 고가가 EMA25 위였던 적 있음
        4. reclaim_short: 현재 종가 < EMA25

        Returns:
            SHORT 신호 여부
        """
        indicators = self.get_latest_indicators()
        if indicators is None:
            return False

        if pd.isna(indicators['adx']) or pd.isna(indicators['atr']):
            return False

        return (
            indicators['bear_trend'] and
            indicators['adx'] >= adx_threshold and
            indicators['had_high_above_fast'] and
            indicators['reclaim_short']
        )

    def get_sl_price(self, direction: str) -> Optional[float]:
        """
        손절가 계산 (최근 N봉 최저가/최고가)

        Args:
            direction: 'LONG' 또는 'SHORT'

        Returns:
            손절가 또는 None
        """
        if len(self.df) < self.sl_lookback:
            return None

        lookback_data = self.df.tail(self.sl_lookback)

        if direction == 'LONG':
            return lookback_data['low'].min()
        else:
            return lookback_data['high'].max()

    def get_current_atr(self) -> Optional[float]:
        """현재 ATR 값 반환"""
        if len(self.df) == 0:
            return None
        return self.df.iloc[-1].get('atr', None)

    def get_last_close(self) -> Optional[float]:
        """마지막 종가 반환"""
        if len(self.df) == 0:
            return None
        return self.df.iloc[-1].get('close', None)

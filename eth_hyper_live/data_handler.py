#!/usr/bin/env python3
"""
Data Handler for ETH Hyper Scalper
15분봉 캔들 데이터 관리 및 지표 계산 모듈

지표:
- EMA 20/100/200
- ADX 14
- ATR 10
- Retest (dip/rally + reclaim)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import pytz


class IndicatorCalculator:
    """TradingView 호환 지표 계산 클래스"""

    @staticmethod
    def calculate_ema(series: pd.Series, length: int) -> pd.Series:
        return series.ewm(span=length, adjust=False).mean()

    @staticmethod
    def calculate_rma(series: pd.Series, length: int) -> pd.Series:
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
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return IndicatorCalculator.calculate_rma(tr, length)

    @staticmethod
    def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm = pd.Series(plus_dm, index=high.index)
        minus_dm = pd.Series(minus_dm, index=high.index)

        atr = IndicatorCalculator.calculate_rma(tr, length)
        plus_di = 100 * IndicatorCalculator.calculate_rma(plus_dm, length) / atr
        minus_di = 100 * IndicatorCalculator.calculate_rma(minus_dm, length) / atr

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = IndicatorCalculator.calculate_rma(dx, length)

        return adx


class CandleDataManager:
    """
    15분봉 캔들 데이터 관리 클래스
    EMA 정배열/역배열 + ADX + Retest 기반
    """

    def __init__(
        self,
        max_candles: int = 500,
        ema_fast: int = 20,
        ema_mid: int = 100,
        ema_slow: int = 200,
        adx_length: int = 14,
        atr_length: int = 10,
        retest_lookback: int = 15,
        sl_lookback: int = 50,
        logger: Optional[logging.Logger] = None
    ):
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
        """과거 캔들 데이터 로드"""
        if not candles:
            self.logger.warning("과거 데이터 없음")
            return

        self.df = pd.DataFrame(candles)
        self.df.columns = self.df.columns.str.lower()

        if len(self.df) > self.max_candles:
            self.df = self.df.tail(self.max_candles).reset_index(drop=True)

        self._calculate_all_indicators()
        self._save_prev_ema_values()

        self.logger.info(f"과거 데이터 로드 완료: {len(self.df)}개 캔들")

    def update_from_kline(self, kline: Dict) -> bool:
        """웹소켓 kline 데이터 업데이트"""
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
            self.df = pd.DataFrame([candle])
            self._calculate_all_indicators()
            return is_closed

        last_timestamp = self.df.iloc[-1]['timestamp']

        if last_timestamp == candle['timestamp']:
            self._update_last_candle(candle)
            if is_closed:
                self._update_indicators_incremental()
                self._save_prev_ema_values()
        else:
            self._append_candle(candle)

        return is_closed

    def _update_last_candle(self, candle: Dict) -> None:
        idx = len(self.df) - 1
        for key in ['open', 'high', 'low', 'close', 'volume', 'timestamp']:
            if key in candle:
                self.df.at[idx, key] = candle[key]

    def _append_candle(self, candle: Dict) -> None:
        new_row = pd.DataFrame([candle])
        self.df = pd.concat([self.df, new_row], ignore_index=True)

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

        # SL rolling (sl_lookback + 1 — 백테스트 iloc[idx-SL_LOOKBACK:idx+1] 과 동일)
        self.df['sl_low'] = self.df['low'].rolling(
            window=self.sl_lookback + 1, min_periods=1
        ).min()
        self.df['sl_high'] = self.df['high'].rolling(
            window=self.sl_lookback + 1, min_periods=1
        ).max()

    def _save_prev_ema_values(self) -> None:
        if len(self.df) == 0:
            return
        last = self.df.iloc[-1]
        self._prev_ema_fast = last.get('ema_fast')
        self._prev_ema_mid = last.get('ema_mid')
        self._prev_ema_slow = last.get('ema_slow')

    def _update_indicators_incremental(self) -> None:
        """증분 방식으로 지표 업데이트"""
        if len(self.df) < 2 or self._prev_ema_fast is None or pd.isna(self._prev_ema_fast):
            self.logger.info("[EMA] 전체 재계산 (prev_ema 없음)")
            self._calculate_all_indicators()
            return

        idx = len(self.df) - 1
        curr_close = self.df.iloc[idx]['close']

        # EMA 증분 계산
        new_ema_fast = self._alpha_fast * curr_close + (1 - self._alpha_fast) * self._prev_ema_fast
        new_ema_mid = self._alpha_mid * curr_close + (1 - self._alpha_mid) * self._prev_ema_mid
        new_ema_slow = self._alpha_slow * curr_close + (1 - self._alpha_slow) * self._prev_ema_slow

        self.logger.info(f"[EMA] 증분계산: prev={self._prev_ema_fast:.2f}, close={curr_close}, new={new_ema_fast:.2f}")

        self.df.at[idx, 'ema_fast'] = new_ema_fast
        self.df.at[idx, 'ema_mid'] = new_ema_mid
        self.df.at[idx, 'ema_slow'] = new_ema_slow

        # ADX, ATR: 전체 재계산
        self.df['adx'] = IndicatorCalculator.calculate_adx(
            self.df['high'], self.df['low'], self.df['close'], self.adx_length
        )
        self.df['atr'] = IndicatorCalculator.calculate_atr(
            self.df['high'], self.df['low'], self.df['close'], self.atr_length
        )

        # Trend conditions
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

        # SL rolling 재계산
        self.df['sl_low'] = self.df['low'].rolling(
            window=self.sl_lookback + 1, min_periods=1
        ).min()
        self.df['sl_high'] = self.df['high'].rolling(
            window=self.sl_lookback + 1, min_periods=1
        ).max()

    def get_latest_indicators(self) -> Optional[Dict[str, Any]]:
        """최신 지표 값 반환"""
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
        """전체 지표 DataFrame 반환 (초기 저장용)"""
        if len(self.df) == 0:
            return None

        columns = [
            'timestamp', 'open', 'high', 'low', 'close',
            'ema_fast', 'ema_mid', 'ema_slow', 'adx', 'atr',
            'bull_trend', 'bear_trend', 'had_low_below_fast',
            'had_high_above_fast', 'reclaim_long', 'reclaim_short'
        ]

        existing_cols = [c for c in columns if c in self.df.columns]
        return self.df[existing_cols].copy()

    def check_long_signal(self, adx_threshold: float = 40.0) -> bool:
        """
        LONG 신호 체크
        조건: bull_trend + ADX >= threshold + had_low_below_fast + reclaim_long
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

    def check_short_signal(self, adx_threshold: float = 40.0) -> bool:
        """
        SHORT 신호 체크
        조건: bear_trend + ADX >= threshold + had_high_above_fast + reclaim_short
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
        """손절가 계산 (sl_low/sl_high 컬럼 사용 — rolling(sl_lookback+1) 기준)"""
        if len(self.df) < self.sl_lookback:
            return None

        latest = self.df.iloc[-1]

        if direction == 'LONG':
            val = latest.get('sl_low', None)
            return val if val is not None and not pd.isna(val) else None
        else:
            val = latest.get('sl_high', None)
            return val if val is not None and not pd.isna(val) else None

    def get_current_atr(self) -> Optional[float]:
        if len(self.df) == 0:
            return None
        return self.df.iloc[-1].get('atr', None)

    def get_last_close(self) -> Optional[float]:
        if len(self.df) == 0:
            return None
        return self.df.iloc[-1].get('close', None)

#!/usr/bin/env python3
"""
FVG Retest Data Handler
- 15분봉: FVG 감지 + 큐 관리용
- 1시간봉: HTF EMA200 필터용 (별도 웹소켓 스트림으로 직접 수신)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import pytz


class FvgCandleManager:
    """15분봉 + 1시간봉 관리"""

    def __init__(
        self,
        max_candles: int = 500,
        htf_ema_len: int = 200,
        use_htf: bool = True,
        max_htf_candles: int = 500,
        logger: Optional[logging.Logger] = None
    ):
        self.max_candles = max_candles
        self.max_htf_candles = max_htf_candles
        self.htf_ema_len = htf_ema_len
        self.use_htf = use_htf
        self.logger = logger or logging.getLogger(__name__)

        # 15m 캔들
        self.df = pd.DataFrame()

        # 1h 캔들 (HTF용)
        self._htf_closes: List[float] = []
        self._htf_timestamps: List[datetime] = []
        self._prev_htf_close: float = np.nan
        self._prev_htf_ema: float = np.nan

    # =====================================================================
    # 15m 캔들 관리
    # =====================================================================

    def load_historical(self, candles: List[Dict]) -> None:
        if not candles:
            self.logger.warning("과거 15m 데이터 없음")
            return

        self.df = pd.DataFrame(candles)
        self.df.columns = self.df.columns.str.lower()

        if len(self.df) > self.max_candles:
            self.df = self.df.tail(self.max_candles).reset_index(drop=True)

        self.logger.info(f"15m 과거 데이터 로드 완료: {len(self.df)}개")

    def update_from_kline(self, kline: Dict) -> bool:
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
            return is_closed

        last_timestamp = self.df.iloc[-1]['timestamp']

        if last_timestamp == candle['timestamp']:
            idx = len(self.df) - 1
            for key in ['open', 'high', 'low', 'close', 'volume', 'timestamp']:
                if key in candle:
                    self.df.at[idx, key] = candle[key]
        else:
            new_row = pd.DataFrame([candle])
            self.df = pd.concat([self.df, new_row], ignore_index=True)
            if len(self.df) > self.max_candles:
                self.df = self.df.tail(self.max_candles).reset_index(drop=True)

        return is_closed

    # =====================================================================
    # 1h HTF 관리
    # =====================================================================

    def load_historical_htf(self, htf_candles: List[Dict]) -> None:
        """과거 1시간봉 로드 + EMA200 계산"""
        if not self.use_htf:
            return

        if not htf_candles:
            self.logger.warning("과거 1h 데이터 없음")
            return

        self._htf_closes = [float(c['close']) for c in htf_candles]
        self._htf_timestamps = [c['timestamp'] for c in htf_candles]

        # 메모리 제한
        if len(self._htf_closes) > self.max_htf_candles:
            self._htf_closes = self._htf_closes[-self.max_htf_candles:]
            self._htf_timestamps = self._htf_timestamps[-self.max_htf_candles:]

        # EMA200 계산 (직전 닫힌 1h)
        if len(self._htf_closes) >= self.htf_ema_len:
            ema = self._calc_ema_array(np.array(self._htf_closes), self.htf_ema_len)
            self._prev_htf_ema = float(ema[-1])
            self._prev_htf_close = self._htf_closes[-1]
            self.logger.info(
                f"HTF 초기화: {len(self._htf_closes)}개 1h, "
                f"직전 닫힌 1h close=${self._prev_htf_close:.4f}, EMA200=${self._prev_htf_ema:.4f}"
            )
        else:
            self.logger.warning(
                f"HTF EMA200 계산 부족 ({len(self._htf_closes)}/{self.htf_ema_len}개)"
            )

    def update_htf_kline(self, kline: Dict) -> bool:
        """1h kline 업데이트. 봉 마감 시 EMA200 재계산하고 True 반환."""
        if not self.use_htf:
            return False

        is_closed = kline.get('x', False)
        if not is_closed:
            return False

        ts = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)
        close = float(kline['c'])

        # 같은 시간대면 업데이트, 새 시간이면 append
        if self._htf_timestamps and self._htf_timestamps[-1] == ts:
            self._htf_closes[-1] = close
        else:
            self._htf_closes.append(close)
            self._htf_timestamps.append(ts)
            if len(self._htf_closes) > self.max_htf_candles:
                self._htf_closes.pop(0)
                self._htf_timestamps.pop(0)

        # EMA200 재계산 (직전 닫힌 1h)
        if len(self._htf_closes) >= self.htf_ema_len:
            ema = self._calc_ema_array(np.array(self._htf_closes), self.htf_ema_len)
            self._prev_htf_ema = float(ema[-1])
            self._prev_htf_close = self._htf_closes[-1]
            self.logger.info(
                f"[HTF] 1h 봉 마감 {ts.strftime('%H:%M')} | close=${close:.4f}, EMA200=${self._prev_htf_ema:.4f}"
            )
        return True

    @staticmethod
    def _calc_ema_array(c: np.ndarray, span: int) -> np.ndarray:
        n = len(c)
        e = np.empty(n)
        e[0] = c[0]
        k = 2.0 / (span + 1.0)
        for i in range(1, n):
            e[i] = c[i] * k + e[i - 1] * (1.0 - k)
        return e

    # =====================================================================
    # FVG 감지 + HTF 필터
    # =====================================================================

    def detect_fvg(self, min_fvg_pct: float = 0.0) -> Optional[List[Dict[str, Any]]]:
        """현재 봉에서 FVG 감지 (백테스트와 동일)"""
        if len(self.df) < 3:
            return None

        i = len(self.df) - 1
        h = self.df['high'].values
        l = self.df['low'].values
        c = self.df['close'].values

        results = []

        if l[i] > h[i - 2]:
            gap_top = float(l[i])
            gap_bot = float(h[i - 2])
            if c[i] > 0 and (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                results.append({'type': 'LONG', 'top': gap_top, 'bot': gap_bot})

        if h[i] < l[i - 2]:
            gap_top = float(l[i - 2])
            gap_bot = float(h[i])
            if c[i] > 0 and (gap_top - gap_bot) / c[i] >= min_fvg_pct:
                results.append({'type': 'SHORT', 'top': gap_top, 'bot': gap_bot})

        return results if results else None

    def get_htf_filter(self) -> Dict[str, bool]:
        """직전 닫힌 1h close vs EMA200"""
        if not self.use_htf:
            return {'bull': True, 'bear': True}
        if np.isnan(self._prev_htf_ema) or np.isnan(self._prev_htf_close):
            return {'bull': False, 'bear': False}
        return {
            'bull': self._prev_htf_close > self._prev_htf_ema,
            'bear': self._prev_htf_close < self._prev_htf_ema
        }

    def get_last_close(self) -> Optional[float]:
        if len(self.df) == 0:
            return None
        return float(self.df.iloc[-1]['close'])

    def get_candle_count(self) -> int:
        return len(self.df)

    def get_htf_status(self) -> Dict[str, Any]:
        return {
            'htf_count': len(self._htf_closes),
            'prev_htf_close': self._prev_htf_close,
            'prev_htf_ema': self._prev_htf_ema
        }

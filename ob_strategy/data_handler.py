#!/usr/bin/env python3
"""
OB Retest Data Handler (백테스트 _common_swap.py 와 동일 spec)
- 5분봉: OB 감지 + 큐 관리용
- 1시간봉: HTF EMA200 필터용
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import pytz


class ObCandleManager:
    """5분봉 + 1시간봉 관리 (FVG 의 FvgCandleManager 와 같은 구조, OB detection 만 다름)"""

    def __init__(
        self,
        max_candles: int = 1000,        # OB 는 max_wait 이 길어 (550) 더 많이 보관
        htf_ema_len: int = 200,
        use_htf: bool = True,
        max_htf_candles: int = 500,
        impulse_lookback: int = 17,
        logger: Optional[logging.Logger] = None
    ):
        self.max_candles = max_candles
        self.max_htf_candles = max_htf_candles
        self.htf_ema_len = htf_ema_len
        self.use_htf = use_htf
        self.impulse_lookback = impulse_lookback
        self.logger = logger or logging.getLogger(__name__)

        # 5m 캔들
        self.df = pd.DataFrame()

        # 1h 캔들 (HTF용)
        self._htf_closes: List[float] = []
        self._htf_timestamps: List[datetime] = []
        self._prev_htf_close: float = np.nan
        self._prev_htf_ema: float = np.nan

    # =====================================================================
    # 5m 캔들 관리
    # =====================================================================

    def load_historical(self, candles: List[Dict]) -> None:
        if not candles:
            self.logger.warning("과거 5m 데이터 없음")
            return

        self.df = pd.DataFrame(candles)
        self.df.columns = self.df.columns.str.lower()

        if len(self.df) > self.max_candles:
            self.df = self.df.tail(self.max_candles).reset_index(drop=True)

        self.logger.info(f"5m 과거 데이터 로드 완료: {len(self.df)}개")

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
    # 1h HTF 관리 (FVG 와 동일)
    # =====================================================================

    def load_historical_htf(self, htf_candles: List[Dict]) -> None:
        if not self.use_htf:
            return

        if not htf_candles:
            self.logger.warning("과거 1h 데이터 없음")
            return

        self._htf_closes = [float(c['close']) for c in htf_candles]
        self._htf_timestamps = [c['timestamp'] for c in htf_candles]

        if len(self._htf_closes) > self.max_htf_candles:
            self._htf_closes = self._htf_closes[-self.max_htf_candles:]
            self._htf_timestamps = self._htf_timestamps[-self.max_htf_candles:]

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
        if not self.use_htf:
            return False

        is_closed = kline.get('x', False)
        if not is_closed:
            return False

        ts = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)
        close = float(kline['c'])

        if self._htf_timestamps and self._htf_timestamps[-1] == ts:
            self._htf_closes[-1] = close
        else:
            self._htf_closes.append(close)
            self._htf_timestamps.append(ts)
            if len(self._htf_closes) > self.max_htf_candles:
                self._htf_closes.pop(0)
                self._htf_timestamps.pop(0)

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
    # OB 감지 (백테스트 _common_swap.py 와 100% 동일)
    # =====================================================================

    def detect_ob(self, impulse_lookback: int, impulse_min_pct: float) -> Optional[List[Dict[str, Any]]]:
        """
        현재 봉(i)에서 OB 감지. 백테스트 spec 와 동일:
          impulse_up = (c[i] - c[i-IL]) / c[i] >= impulse_min_pct → LONG OB
            ob_idx = (i-IL ~ i-1) 중 lowest low 봉
            ob_top = h[ob_idx], ob_bot = l[ob_idx]
          impulse_down 역순 → SHORT OB
        """
        if len(self.df) < impulse_lookback + 2:
            return None

        i = len(self.df) - 1
        h = self.df['high'].values
        l = self.df['low'].values
        c = self.df['close'].values

        results = []

        # LONG OB
        impulse_up = (c[i] - c[i - impulse_lookback]) / c[i] if c[i] > 0 else 0.0
        if impulse_up >= impulse_min_pct:
            ob_idx = i - impulse_lookback
            min_l = l[ob_idx]
            for k in range(i - impulse_lookback + 1, i):
                if l[k] < min_l:
                    min_l = l[k]
                    ob_idx = k
            ob_top = float(h[ob_idx])
            ob_bot = float(l[ob_idx])
            if ob_top > ob_bot:
                results.append({'type': 'LONG', 'top': ob_top, 'bot': ob_bot})

        # SHORT OB
        impulse_down = (c[i - impulse_lookback] - c[i]) / c[i] if c[i] > 0 else 0.0
        if impulse_down >= impulse_min_pct:
            ob_idx = i - impulse_lookback
            max_h = h[ob_idx]
            for k in range(i - impulse_lookback + 1, i):
                if h[k] > max_h:
                    max_h = h[k]
                    ob_idx = k
            ob_top = float(h[ob_idx])
            ob_bot = float(l[ob_idx])
            if ob_top > ob_bot:
                results.append({'type': 'SHORT', 'top': ob_top, 'bot': ob_bot})

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

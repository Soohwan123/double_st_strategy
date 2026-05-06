"""
Breakout Strategy DataHandler — LuxAlgo Trendlines with Breaks 매니저

상태:
  - 5m 봉 history (rolling, len = max(2L+2, 500))
  - ATR (Wilder/RMA, incremental update)
  - upper/lower trendline + slope
  - upos/dnos breakout state
  - prev_upos/prev_dnos (직전 봉 state)

검수 (BT _common.py 와 동일):
  - Pivot pi = (i - L) 가 [i-2L .. i] 윈도우 내 high/low 극값?
  - Slope = atr[pi] × MULT / L
  - Pivot 발견 시: upper/lower reset, slope 갱신
  - 없으면: upper -= slope_ph, lower += slope_pl 매 봉
  - up_th = upper - slope_ph × L, dn_th = lower + slope_pl × L
  - upos: 1 if c[i] > up_th, 0 if pivot reset
  - up_break: upos > prev_upos (state 0→1 변화)
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List


class BreakoutCandleManager:
    def __init__(self, length: int, mult: float, max_candles: int = 500):
        self.length = length
        self.mult = mult
        self.max_candles = max(max_candles, 2 * length + 50)

        self.df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # ATR (RMA based on TR)
        self._atr_arr: List[float] = []  # i-th element corresponds to df[i]

        # Trendline state (BT 의 main loop 변수와 1:1 매칭)
        self.upper: float = 0.0
        self.lower: float = 0.0
        self.slope_ph: float = 0.0
        self.slope_pl: float = 0.0
        self.upper_init: bool = False
        self.lower_init: bool = False
        self.upos: int = 0
        self.dnos: int = 0
        self.prev_upos: int = 0
        self.prev_dnos: int = 0

        # 마지막 봉 close 까지 처리 완료 여부 (중복 처리 방지)
        self._last_processed_ts: Optional[pd.Timestamp] = None

    def load_historical(self, klines: List[Dict[str, Any]]):
        """REST API 로 가져온 klines 로 초기화. 마지막 미완성 봉은 제외하고 호출자에서 처리."""
        rows = []
        for k in klines:
            rows.append({
                'timestamp': pd.to_datetime(k['t'] if 't' in k else k[0], unit='ms', utc=True),
                'open': float(k['o'] if 'o' in k else k[1]),
                'high': float(k['h'] if 'h' in k else k[2]),
                'low': float(k['l'] if 'l' in k else k[3]),
                'close': float(k['c'] if 'c' in k else k[4]),
                'volume': float(k['v'] if 'v' in k else k[5]),
            })
        self.df = pd.DataFrame(rows)
        self._recompute_atr_full()
        self._replay_trendline_state()

    def _recompute_atr_full(self):
        """전체 ATR 재계산 (load_historical 시점만)."""
        n = len(self.df)
        L = self.length
        self._atr_arr = [float('nan')] * n
        if n < L + 1:
            return
        h = self.df['high'].values
        l = self.df['low'].values
        c = self.df['close'].values
        tr_sum = 0.0
        for i in range(1, L + 1):
            tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            tr_sum += tr
        self._atr_arr[L] = tr_sum / L
        for i in range(L + 1, n):
            tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            self._atr_arr[i] = (self._atr_arr[i - 1] * (L - 1) + tr) / L

    def _replay_trendline_state(self):
        """과거 봉을 봉별로 순회하며 trendline state (upper/lower/upos/dnos) 재구축.
        BT 의 main loop 그대로 흉내. 단 entry 처리는 안 함 (state 만 동기화)."""
        n = len(self.df)
        L = self.length
        if n < 2 * L + 1:
            return
        h = self.df['high'].values
        l = self.df['low'].values
        c = self.df['close'].values

        self.upper = 0.0
        self.lower = 0.0
        self.slope_ph = 0.0
        self.slope_pl = 0.0
        self.upper_init = False
        self.lower_init = False
        self.upos = 0
        self.dnos = 0

        for i in range(2 * L + 1, n):
            self._update_trendline_at(i, h, l, c)
        # 주의: 마지막 _update_trendline_at 가 prev_upos = (i-1 의 upos) 로 저장된 상태로 종료.
        # 별도 override 안 함 — 다음 새 봉 시점에 _update_trendline_at 가 prev = upos 로 재저장.

    def _update_trendline_at(self, i: int, h, l, c):
        """봉 i 시점의 trendline state 갱신. BT _common.py:127-157 와 1:1 매칭."""
        L = self.length
        pi = i - L

        # pivot detection in [i-2L .. i]
        is_ph = True
        is_pl = True
        ph_val = h[pi]
        pl_val = l[pi]
        for k in range(i - 2 * L, i + 1):
            if k == pi:
                continue
            if h[k] >= ph_val:
                is_ph = False
            if l[k] <= pl_val:
                is_pl = False
            if not is_ph and not is_pl:
                break

        atr_pi = self._atr_arr[pi] if 0 <= pi < len(self._atr_arr) else float('nan')
        slope_now = atr_pi * self.mult / L if not np.isnan(atr_pi) else 0.0

        if is_ph:
            self.upper = ph_val
            self.slope_ph = slope_now
            self.upper_init = True
        elif self.upper_init:
            self.upper -= self.slope_ph

        if is_pl:
            self.lower = pl_val
            self.slope_pl = slope_now
            self.lower_init = True
        elif self.lower_init:
            self.lower += self.slope_pl

        up_th = (self.upper - self.slope_ph * L) if self.upper_init else (c[i] + 1e9)
        dn_th = (self.lower + self.slope_pl * L) if self.lower_init else -1e9

        # upos/dnos 갱신
        self.prev_upos = self.upos
        self.prev_dnos = self.dnos
        if is_ph:
            self.upos = 0
        elif c[i] > up_th:
            self.upos = 1
        if is_pl:
            self.dnos = 0
        elif c[i] < dn_th:
            self.dnos = 1

    def append_closed_kline(self, kline: Dict[str, Any]) -> bool:
        """봉 마감 (kline x=true) 시 호출. 새 봉 추가 + ATR/trendline state 갱신.

        Returns True if state 갱신 성공.
        """
        ts = pd.to_datetime(kline['t'], unit='ms', utc=True)
        if self._last_processed_ts is not None and ts <= self._last_processed_ts:
            return False  # 중복 봉 무시

        new_row = {
            'timestamp': ts,
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline.get('v', 0)),
        }
        self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

        # max_candles 초과 시 앞부분 자르기
        if len(self.df) > self.max_candles:
            cut = len(self.df) - self.max_candles
            self.df = self.df.iloc[cut:].reset_index(drop=True)
            self._atr_arr = self._atr_arr[cut:]

        # ATR incremental update (마지막 봉만)
        i = len(self.df) - 1
        L = self.length
        prev_atr_ok = (
            len(self._atr_arr) == i  # 새 봉 추가 전 길이가 i 와 일치 (직전 봉이 마지막이었음)
            and i >= L + 1
            and not np.isnan(self._atr_arr[i - 1])
        )
        if prev_atr_ok:
            h = self.df['high'].values
            l = self.df['low'].values
            c = self.df['close'].values
            tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            new_atr = (self._atr_arr[i - 1] * (L - 1) + tr) / L
            self._atr_arr.append(new_atr)
        else:
            # warmup 부족 또는 길이 불일치 — 전체 재계산
            self._recompute_atr_full()

        # Trendline state 갱신
        if len(self.df) >= 2 * L + 1:
            h = self.df['high'].values
            l = self.df['low'].values
            c = self.df['close'].values
            self._update_trendline_at(i, h, l, c)

        self._last_processed_ts = ts
        return True

    def get_breakout_signal(self) -> Optional[str]:
        """직전 봉 마감에 발생한 breakout. 'LONG' / 'SHORT' / None.

        BT _common.py:156-188 매칭:
          - up_break = upos > prev_upos
          - dn_break = dnos > prev_dnos
          - 동시 발동 시 둘 다 무시 (entry 없음)
        """
        if not (self.upper_init and self.lower_init):
            return None
        up_break = self.upos > self.prev_upos
        dn_break = self.dnos > self.prev_dnos
        if up_break and not dn_break:
            return 'LONG'
        elif dn_break and not up_break:
            return 'SHORT'
        return None

    def get_current_atr(self) -> Optional[float]:
        """현재 (마지막 닫힌) 봉의 ATR. entry 시 sl_dist 계산용."""
        if not self._atr_arr:
            return None
        a = self._atr_arr[-1]
        return None if np.isnan(a) else float(a)

    def get_last_close(self) -> Optional[float]:
        if len(self.df) == 0:
            return None
        return float(self.df['close'].iloc[-1])

    def get_candle_count(self) -> int:
        return len(self.df)

    def get_thresholds(self) -> Dict[str, Any]:
        """디버그/로그용 — 현재 trendline state."""
        L = self.length
        up_th = (self.upper - self.slope_ph * L) if self.upper_init else None
        dn_th = (self.lower + self.slope_pl * L) if self.lower_init else None
        return {
            'upper': self.upper if self.upper_init else None,
            'lower': self.lower if self.lower_init else None,
            'up_th': up_th,
            'dn_th': dn_th,
            'upos': self.upos,
            'dnos': self.dnos,
            'prev_upos': self.prev_upos,
            'prev_dnos': self.prev_dnos,
            'atr': self.get_current_atr(),
        }

    def to_dict(self) -> Dict[str, Any]:
        """state 영속화용 — trendline state + last_processed_ts."""
        return {
            'upper': self.upper,
            'lower': self.lower,
            'slope_ph': self.slope_ph,
            'slope_pl': self.slope_pl,
            'upper_init': self.upper_init,
            'lower_init': self.lower_init,
            'upos': self.upos,
            'dnos': self.dnos,
            'prev_upos': self.prev_upos,
            'prev_dnos': self.prev_dnos,
            'last_processed_ts': self._last_processed_ts.isoformat() if self._last_processed_ts is not None else None,
        }

    def from_dict(self, data: Dict[str, Any]):
        """저장된 trendline state 복원. 단 ATR 와 df 는 load_historical 로 재구축."""
        self.upper = data.get('upper', 0.0)
        self.lower = data.get('lower', 0.0)
        self.slope_ph = data.get('slope_ph', 0.0)
        self.slope_pl = data.get('slope_pl', 0.0)
        self.upper_init = data.get('upper_init', False)
        self.lower_init = data.get('lower_init', False)
        self.upos = data.get('upos', 0)
        self.dnos = data.get('dnos', 0)
        self.prev_upos = data.get('prev_upos', 0)
        self.prev_dnos = data.get('prev_dnos', 0)
        ts_str = data.get('last_processed_ts')
        self._last_processed_ts = pd.to_datetime(ts_str, utc=True) if ts_str else None

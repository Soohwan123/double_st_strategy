#!/usr/bin/env python3
"""
OB Retest Live Strategy
_common.py run_backtest()와 동일한 매매 로직

핵심 흐름:
1. 15m 봉 마감 → FVG 감지 → 큐 관리 (invalidation/timeout)
2. 포지션 없으면 → 최적 FVG 선택 → 지정가 진입 대기
3. 체결 시 → SL/TP 설정
4. 틱데이터로 TP/SL 감지
"""

import asyncio
import logging
import csv
import math
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import pytz
import pandas as pd

from config import DynamicConfig, Config, OB_DEFAULT_PARAMS
from state_manager import StateManager
from binance_library import BinanceFuturesClient
from data_handler import ObCandleManager


# =========================================================================
# FVG Queue
# =========================================================================

class ObEntry:
    """단일 FVG 엔트리"""
    __slots__ = ('top', 'bot', 'bar_idx')

    def __init__(self, top: float, bot: float, bar_idx: int):
        self.top = top
        self.bot = bot
        self.bar_idx = bar_idx


class ObQueue:
    """FVG 큐 관리 (백테스트의 long_top/bot/bar, short_top/bot/bar와 동일)"""

    def __init__(self, max_size: int = 16):
        self.max_size = max_size
        self.entries: List[ObEntry] = []

    def add(self, top: float, bot: float, bar_idx: int):
        if len(self.entries) < self.max_size:
            self.entries.append(ObEntry(top, bot, bar_idx))

    def invalidate_long(self, close: float):
        """Bullish FVG: close < bot → 무효 (백테스트 line 318)"""
        self.entries = [e for e in self.entries if close >= e.bot]

    def invalidate_short(self, close: float):
        """Bearish FVG: close > top → 무효 (백테스트 line 324)"""
        self.entries = [e for e in self.entries if close <= e.top]

    def timeout(self, current_idx: int, max_wait: int):
        """max_wait 초과 FVG 제거 (백테스트 line 318, 324)"""
        self.entries = [e for e in self.entries if (current_idx - e.bar_idx) <= max_wait]

    def get_newest(self) -> Optional[ObEntry]:
        """가장 최근 FVG 반환 (백테스트 line 347: best_bar > best_bar)"""
        if not self.entries:
            return None
        return max(self.entries, key=lambda e: e.bar_idx)

    def get_newest_before(self, current_bar_idx: int) -> Optional[ObEntry]:
        """current_bar_idx보다 이전 봉의 FVG 중 가장 최근 것.
        백테스트 `long_bar[k] < i` 조건과 동일. 이번 봉에 방금 감지된 FVG는 스킵."""
        candidates = [e for e in self.entries if e.bar_idx < current_bar_idx]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.bar_idx)

    def clear(self):
        self.entries.clear()

    def __len__(self):
        return len(self.entries)


# =========================================================================
# Position State
# =========================================================================

class ObPositionState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.direction: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_size: float = 0.0
        self.take_profit: float = 0.0
        self.stop_loss: float = 0.0
        self.leverage: float = 1.0
        self.tp_order_id: Optional[str] = None
        self.sl_order_id: Optional[str] = None
        self.liq_price: float = 0.0
        self.is_virtual: bool = False  # 시뮬레이션에서 이어받은 가상 포지션
        self.entry_order_id: Optional[int] = None
        self.entry_time_ms: int = 0
        # 대기 주문
        self.pending_order_id: Optional[str] = None
        self.pending_direction: Optional[str] = None
        self.pending_entry_price: float = 0.0
        self.pending_sl_price: float = 0.0
        self.pending_tp_price: float = 0.0
        self.pending_leverage: float = 1.0
        self.pending_size: float = 0.0

    def has_position(self) -> bool:
        return self.direction is not None and self.entry_size > 0

    def has_pending(self) -> bool:
        return self.pending_order_id is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'direction': self.direction,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'entry_size': self.entry_size,
            'take_profit': self.take_profit,
            'stop_loss': self.stop_loss,
            'leverage': self.leverage,
            'tp_order_id': self.tp_order_id,
            'sl_order_id': self.sl_order_id,
            'liq_price': self.liq_price,
            'is_virtual': self.is_virtual,
            'entry_order_id': self.entry_order_id,
            'entry_time_ms': self.entry_time_ms,
            'pending_order_id': self.pending_order_id,
            'pending_direction': self.pending_direction,
            'pending_entry_price': self.pending_entry_price,
            'pending_sl_price': self.pending_sl_price,
            'pending_tp_price': self.pending_tp_price,
            'pending_leverage': self.pending_leverage,
            'pending_size': self.pending_size,
        }

    def from_dict(self, data: Dict[str, Any]):
        self.direction = data.get('direction')
        self.entry_price = data.get('entry_price', 0.0)
        entry_time_str = data.get('entry_time')
        self.entry_time = datetime.fromisoformat(entry_time_str) if entry_time_str else None
        self.entry_size = data.get('entry_size', 0.0)
        self.take_profit = data.get('take_profit', 0.0)
        self.stop_loss = data.get('stop_loss', 0.0)
        self.leverage = data.get('leverage', 1.0)
        self.tp_order_id = data.get('tp_order_id')
        self.sl_order_id = data.get('sl_order_id')
        self.liq_price = data.get('liq_price', 0.0)
        self.is_virtual = data.get('is_virtual', False)
        self.entry_order_id = data.get('entry_order_id')
        self.entry_time_ms = data.get('entry_time_ms', 0)
        self.pending_order_id = data.get('pending_order_id')
        self.pending_direction = data.get('pending_direction')
        self.pending_entry_price = data.get('pending_entry_price', 0.0)
        self.pending_sl_price = data.get('pending_sl_price', 0.0)
        self.pending_tp_price = data.get('pending_tp_price', 0.0)
        self.pending_leverage = data.get('pending_leverage', 1.0)
        self.pending_size = data.get('pending_size', 0.0)


# =========================================================================
# Strategy
# =========================================================================

class ObStrategy:
    def __init__(self, binance: BinanceFuturesClient, symbol_type: str, logger: logging.Logger):
        self.binance = binance
        self.symbol_type = symbol_type
        self.logger = logger

        self.quote_asset = Config.get_quote_asset(symbol_type)
        self.dynamic_config = DynamicConfig(symbol_type)
        self.state_manager = StateManager(Config.get_state_path(symbol_type), logger)
        self.position = ObPositionState()

        self.candle_manager: Optional[ObCandleManager] = None
        max_q = self._get_param('MAX_OB_QUEUE', 16)
        self.long_queue = ObQueue(max_size=max_q)
        self.short_queue = ObQueue(max_size=max_q)
        self.capital: float = 0.0
        self.initialized: bool = False
        self._bar_idx: int = 0
        # 이번 봉 중 포지션 exit 발생 여부 — True면 해당 봉의 FVG 감지/invalidation/entry 스킵 (backtest `continue` 매칭)
        self._exit_this_bar: bool = False

        # TF / Strategy mode (config 로 제어 — BTC/ETH/XRP 는 기본값 유지)
        # TF: '15m' (default) or '5m' — load_historical_data 의 interval 과 log prefix 에 사용
        # STRATEGY_MODE: 'HYSTERESIS' (default, 40/60 line, BTC/ETH/XRP)
        #                'BT_LONG_FIRST' (LONG-priority, BT _common_swap.py 와 1:1 매칭, SOL bt_31)
        self.tf = str(self.dynamic_config.get('TF') or '5m')
        self.strategy_mode = str(self.dynamic_config.get('STRATEGY_MODE') or 'HYSTERESIS')

        self.trades_path = Config.get_trades_path(symbol_type)
        os.makedirs(os.path.dirname(self.trades_path), exist_ok=True)

        self._last_tick_api_time: float = 0.0
        self._tick_api_min_interval: float = 0.1

        # 양쪽 FVG 동시 valid 시 스위칭 제어 (HYSTERESIS 모드에서만)
        self._last_switch_time: float = 0.0
        self._last_eval_price: float = 0.0
        self._switch_throttle_sec: float = 5.0
        self._switch_price_threshold: float = 0.0005   # 0.05%
        self._hysteresis_low: float = 0.4              # 40% line
        self._hysteresis_high: float = 0.6             # 60% line

    def _reload_config(self):
        self.dynamic_config.reload()

    def _get_param(self, key: str, default=None):
        return self.dynamic_config.get(key, OB_DEFAULT_PARAMS.get(key, default))

    def is_dry_run(self) -> bool:
        return self._get_param('DRY_RUN', True)

    # =====================================================================
    # 초기화
    # =====================================================================

    async def initialize(self):
        self.logger.info("=" * 60)
        self.logger.info("OB Retest Strategy 초기화")
        self._reload_config()

        if self.is_dry_run():
            self.logger.info("*** DRY RUN 모드 ***")
        else:
            self.logger.info("*** LIVE 거래 모드 ***")
            self.logger.warning("*** 실제 자금으로 거래합니다! ***")
        self.logger.info("=" * 60)

        self.candle_manager = ObCandleManager(
            max_candles=500,
            htf_ema_len=self._get_param('HTF_EMA_LEN', 200),
            use_htf=self._get_param('USE_HTF', True),
            logger=self.logger
        )

        await self._init_capital()

        state = self.state_manager.load_state()
        if state:
            await self._restore_state(state)
        else:
            self.logger.info("새로운 거래 세션 시작")

        self.initialized = True

    async def _init_capital(self):
        state = self.state_manager.load_state()
        if state and 'capital' in state and state['capital'] > 0:
            self.capital = state['capital']
            self.logger.info(f"저장된 자본 복구: ${self.capital:.2f}")
            return
        self.capital = self._get_param('INITIAL_CAPITAL', 1800.0)
        self.logger.info(f"초기 자본 설정: ${self.capital:.2f}")

    async def _restore_state(self, state: Dict[str, Any]):
        self.logger.info("이전 상태 복구 중...")
        try:
            if 'capital' in state:
                self.capital = state['capital']
                self.logger.info(f"자본금 복구: ${self.capital:.2f}")
            if 'position' in state and state['position']:
                self.position.from_dict(state['position'])
                pp = Config.get_price_precision(self.symbol_type)
                if self.position.has_position():
                    self.logger.info(f"포지션 복구: {self.position.direction} @ ${self.position.entry_price:.{pp}f}")
                if self.position.has_pending():
                    self.logger.info(f"대기주문 복구: {self.position.pending_direction} @ ${self.position.pending_entry_price:.{pp}f}")
            if 'bar_idx' in state:
                self._bar_idx = state['bar_idx']
        except Exception as e:
            self.logger.error(f"상태 복구 실패 (state 손상 가능): {e} - 거래소 sync로 복구")
            self.position.reset()

        if not self.is_dry_run():
            await self._sync_with_binance()
            await self._validate_pending_order()

    async def _validate_pending_order(self):
        """Restart 후 pending order가 거래소에 실제로 존재하는지 확인"""
        if not self.position.has_pending() or self.is_dry_run():
            return

        oid = self.position.pending_order_id
        try:
            status_data = await self.binance.get_order_status(oid)
            if status_data is None:
                self.logger.warning(f"복구된 대기주문 {oid}이(가) 거래소에 없음 - 정리")
                self.position.pending_order_id = None
                self.position.pending_direction = None
                self._save_state()
                return

            status = status_data.get('status', '')
            executed_qty = float(status_data.get('executedQty', 0))

            if status == 'FILLED':
                self.logger.warning(f"복구 중 기존 주문 체결 감지: {oid}")
                avg_price = float(status_data.get('avgPrice', self.position.pending_entry_price))
                await self._on_entry_filled(avg_price, executed_qty, status_data)
            elif status == 'PARTIALLY_FILLED' and executed_qty > 0:
                # 부분 체결 중엔 포지션 가드 (SL/TP) 걸지 않고 FILLED 될 때까지 대기.
                # 중간에 가드 걸면 나머지 fill 이 orphan 포지션 됨
                # (2026-04-24 XRP 516.7 주문 중 52만 인식 → 464.7 orphan 버그 원인)
                self.logger.warning(f"복구 중 부분 체결 진행: {executed_qty} - FILLED 대기 (포지션 가드 보류)")
            elif status in ('CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'):
                self.logger.info(f"복구된 주문이 종결됨 ({status}) - 정리")
                self.position.pending_order_id = None
                self.position.pending_direction = None
                self._save_state()
            else:
                self.logger.info(f"복구된 대기주문 정상 ({status}): {oid}")
        except Exception as e:
            self.logger.error(f"대기주문 검증 실패: {e}")

    async def _sync_with_binance(self):
        if self.is_dry_run():
            return
        # 가상 포지션은 Binance에 없는 게 정상 → sync 스킵
        if self.position.is_virtual:
            return
        pos_info = await self.binance.get_position_info()
        if pos_info:
            if self.position.has_position():
                self.position.entry_price = pos_info['entry_price']
                self.position.entry_size = pos_info['size']
        else:
            if self.position.has_position():
                self.logger.warning("바이낸스 포지션 없음 - 로컬 초기화")
                self.position.reset()
        self._save_state()

    def _save_state(self):
        state = {
            'capital': self.capital,
            'position': self.position.to_dict() if (self.position.has_position() or self.position.has_pending()) else None,
            'bar_idx': self._bar_idx
        }
        self.state_manager.save_state(state)

    # =====================================================================
    # 과거 데이터 로드
    # =====================================================================

    async def load_historical_data(self):
        # 1) Main TF 봉 로드 (5m / 15m)
        self.logger.info(f"과거 {self.tf} 봉 데이터 로드 중...")
        try:
            klines = self.binance.client.futures_klines(
                symbol=self.binance.symbol, interval=self.tf, limit=501
            )
            candles = []
            for kline in klines[:-1]:
                candles.append({
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            self.candle_manager.load_historical(candles)
            self._bar_idx = len(candles)
            self.logger.info(f"{self.tf} 봉 로드 완료: {len(candles)}개")
        except Exception as e:
            self.logger.error(f"{self.tf} 데이터 로드 실패: {e}")
            raise

        # 2) 1h 봉 로드 (HTF EMA200용)
        if self._get_param('USE_HTF', True):
            try:
                self.logger.info("과거 1시간봉 데이터 로드 중 (HTF EMA200용)...")
                htf_klines = self.binance.client.futures_klines(
                    symbol=self.binance.symbol, interval='1h', limit=501
                )
                htf_candles = []
                for kline in htf_klines[:-1]:  # 마지막 미완성 봉 제외
                    htf_candles.append({
                        'timestamp': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                        'close': float(kline[4])
                    })
                self.candle_manager.load_historical_htf(htf_candles)
                self.logger.info(f"1시간봉 로드 완료: {len(htf_candles)}개")
            except Exception as e:
                self.logger.error(f"1h 데이터 로드 실패: {e}")
                raise

        htf = self.candle_manager.get_htf_filter()
        self.logger.info(f"HTF 필터: bull={htf['bull']}, bear={htf['bear']}")

        # 3) 과거 데이터로 FVG 큐 재구축 (항상 수행 — 재시작해도 queue가 즉시 백테스트 상태와 동기화)
        # 가상 포지션 takeover는 _simulate_history_queue 내부에서 position/pending 없을 때만 수행
        await self._simulate_history_queue()

    # =====================================================================
    # 과거 데이터 시뮬레이션 (백테스트 run_backtest 로직)
    # =====================================================================

    async def _simulate_history_queue(self):
        """
        과거 데이터로 FVG 큐 + 가상 포지션 시뮬레이션.
        백테스트 run_backtest와 동일한 로직으로 매 봉 순회하며:
        - FVG 감지/추가
        - Invalidation/Timeout
        - 가상 진입/청산 (실제 주문 없음)
        시작 시점에 가상 포지션 남아있으면 position에 is_virtual=True 저장.
        """
        import numpy as np

        if len(self.candle_manager.df) < 3:
            return

        df = self.candle_manager.df
        h = df['high'].values
        l = df['low'].values
        c = df['close'].values
        timestamps = df['timestamp']
        n = len(df)

        max_wait = self._get_param('MAX_WAIT', 550)
        impulse_lookback = self._get_param('IMPULSE_LOOKBACK', 17)
        impulse_min_pct = self._get_param('IMPULSE_MIN_PCT', 0.025)
        trade_dir = self._get_param('TRADE_DIRECTION', 'BOTH')
        sl_buffer = self._get_param('SL_BUFFER_PCT', 0.0025)
        rr = self._get_param('RR', 0.35)
        taker_fee = self._get_param('TAKER_FEE', 0.0005)
        max_lev = self._get_param('MAX_LEVERAGE', 90)
        risk_per_trade = self._get_param('RISK_PER_TRADE', 0.12)
        use_htf = self._get_param('USE_HTF', True)
        htf_len = self._get_param('HTF_EMA_LEN', 200)

        # 각 15m 봉 시점의 HTF 필터 사전 계산 (백테스트 build_htf_arrays와 동일)
        htf_per_bar = []
        if use_htf and self.candle_manager._htf_closes:
            htf_closes_arr = np.array(self.candle_manager._htf_closes)
            htf_times = self.candle_manager._htf_timestamps
            if len(htf_closes_arr) >= htf_len + 1:
                htf_ema_arr = self.candle_manager._calc_ema_array(htf_closes_arr, htf_len)
                hour_to_idx = {t: k for k, t in enumerate(htf_times)}
                for ts in timestamps:
                    bar_hour = ts.replace(minute=0, second=0, microsecond=0)
                    idx = hour_to_idx.get(bar_hour, -1)
                    if idx > 0 and idx >= htf_len:
                        prev_close = htf_closes_arr[idx - 1]
                        prev_ema = htf_ema_arr[idx - 1]
                        htf_per_bar.append({
                            'bull': bool(prev_close > prev_ema),
                            'bear': bool(prev_close < prev_ema)
                        })
                    else:
                        htf_per_bar.append({'bull': False, 'bear': False})
            else:
                htf_per_bar = [{'bull': False, 'bear': False}] * n
        else:
            htf_per_bar = [{'bull': True, 'bear': True}] * n

        # 가상 포지션 상태
        v_pos = None

        for i in range(impulse_lookback + 1, n):
            # 1. EXIT (가상 포지션) — 백테스트 `continue` 매칭: exit 발생 시 이 봉의 나머지 처리 스킵
            if v_pos is not None and i > v_pos['entry_idx']:
                exited = False
                if v_pos['direction'] == 'LONG':
                    if (l[i] <= v_pos['liq_price'] or
                        l[i] <= v_pos['sl_price'] or
                        h[i] >= v_pos['tp_price']):
                        v_pos = None
                        exited = True
                else:
                    if (h[i] >= v_pos['liq_price'] or
                        h[i] >= v_pos['sl_price'] or
                        l[i] <= v_pos['tp_price']):
                        v_pos = None
                        exited = True
                if exited:
                    continue

            # 2. OB 감지 (백테스트 _common_swap.py 와 동일: impulse + lookback)
            if c[i] > 0:
                impulse_up = (c[i] - c[i - impulse_lookback]) / c[i]
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
                        self.long_queue.add(ob_top, ob_bot, i)
                impulse_down = (c[i - impulse_lookback] - c[i]) / c[i]
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
                        self.short_queue.add(ob_top, ob_bot, i)

            # 3. [SWAP] Virtual entry — invalidation 보다 먼저 (BT _common_swap.py:213-307 매칭)
            #    LIMIT 진입 + close-기반 무효화 함정 회피: 같은 봉에서 fill 먼저, 무효화 나중.
            if v_pos is None:
                htf = htf_per_bar[i]

                # LONG 시도 (BT line 218-262)
                if trade_dir in ['BOTH', 'LONG'] and htf['bull']:
                    best_k = -1
                    best_bar = -1
                    for k, entry in enumerate(self.long_queue.entries):
                        if entry.bar_idx < i and l[i] <= entry.top:
                            if entry.bar_idx > best_bar:
                                best_bar = entry.bar_idx
                                best_k = k
                    if best_k >= 0:
                        e = self.long_queue.entries[best_k]
                        ep = float(e.top)
                        if ep > h[i]: ep = float(h[i])
                        if ep < l[i]: ep = float(l[i])
                        sl_edge = e.bot * (1.0 - sl_buffer)
                        sl_dist = ep - sl_edge
                        if sl_dist > 0:
                            sl_pct = sl_dist / ep
                            eff_sl = sl_pct + taker_fee * 2.0
                            lev = max(1.0, min(risk_per_trade / eff_sl, max_lev))
                            v_pos = {
                                'direction': 'LONG',
                                'entry_idx': i,
                                'entry_price': ep,
                                'sl_price': float(sl_edge),
                                'tp_price': float(ep + rr * sl_dist),
                                'liq_price': float(ep * (1.0 - 1.0 / lev)),
                                'leverage': float(lev),
                            }
                            self.long_queue.clear()
                            continue

                # SHORT 시도 (BT line 264-307)
                if trade_dir in ['BOTH', 'SHORT'] and htf['bear']:
                    best_k = -1
                    best_bar = -1
                    for k, entry in enumerate(self.short_queue.entries):
                        if entry.bar_idx < i and h[i] >= entry.bot:
                            if entry.bar_idx > best_bar:
                                best_bar = entry.bar_idx
                                best_k = k
                    if best_k >= 0:
                        e = self.short_queue.entries[best_k]
                        ep = float(e.bot)
                        if ep > h[i]: ep = float(h[i])
                        if ep < l[i]: ep = float(l[i])
                        sl_edge = e.top * (1.0 + sl_buffer)
                        sl_dist = sl_edge - ep
                        if sl_dist > 0:
                            sl_pct = sl_dist / ep
                            eff_sl = sl_pct + taker_fee * 2.0
                            lev = max(1.0, min(risk_per_trade / eff_sl, max_lev))
                            v_pos = {
                                'direction': 'SHORT',
                                'entry_idx': i,
                                'entry_price': ep,
                                'sl_price': float(sl_edge),
                                'tp_price': float(ep - rr * sl_dist),
                                'liq_price': float(ep * (1.0 + 1.0 / lev)),
                                'leverage': float(lev),
                            }
                            self.short_queue.clear()
                            continue

            # 4. [SWAP] Invalidation + Timeout — entry 뒤로 (BT _common_swap.py:309-319 매칭)
            close_v = float(c[i])
            self.long_queue.invalidate_long(close_v)
            self.short_queue.invalidate_short(close_v)
            self.long_queue.timeout(i, max_wait)
            self.short_queue.timeout(i, max_wait)

        self._bar_idx = n

        # 가상 포지션 처리: DRY/LIVE 모두 이어받아 청산까지 실거래 대기 (백테스트 semantic 100% 유지)
        pp = Config.get_price_precision(self.symbol_type)
        # 가상 포지션 takeover는 state에 복구된 position/pending이 없을 때만
        # (재시작 시 simulation 항상 돌려 큐 재구축하되, 기존 상태 덮어쓰기 방지)
        already_has_state = self.position.has_position() or self.position.has_pending()
        takeover = v_pos is not None and not already_has_state
        if takeover:
            mode = "DRY" if self.is_dry_run() else "LIVE"
            self.position.direction = v_pos['direction']
            self.position.entry_price = v_pos['entry_price']
            self.position.entry_time = datetime.now(pytz.UTC)
            self.position.entry_size = 0.001  # nominal, has_position() 판정용
            self.position.take_profit = v_pos['tp_price']
            self.position.stop_loss = v_pos['sl_price']
            self.position.liq_price = v_pos['liq_price']
            self.position.leverage = v_pos['leverage']
            self.position.is_virtual = True
            self.logger.warning(
                f"[{mode} 가상 포지션 이어받기] {v_pos['direction']} @ ${v_pos['entry_price']:.{pp}f} "
                f"| SL=${v_pos['sl_price']:.{pp}f}, TP=${v_pos['tp_price']:.{pp}f}, "
                f"LIQ=${v_pos['liq_price']:.{pp}f} | 가상 청산까지 실거래 대기"
            )
            self._save_state()
        elif v_pos is not None and already_has_state:
            self.logger.info("시뮬레이션에서 가상 포지션 발생했으나 state에 이미 복구된 포지션/pending 존재 → takeover 스킵")

        # 가상포지션 상태 표시: takeover 여부뿐 아니라 state 에 이미 있는 virtual 도 반영
        if takeover:
            pos_state = '이어받음 (신규 takeover)'
        elif self.position.is_virtual and self.position.has_position():
            pos_state = f"기존 state 유지 (is_virtual=True, {self.position.direction} @ ${self.position.entry_price:.{pp}f})"
        elif self.position.has_position():
            pos_state = f"실포지션 (state 복구)"
        elif self.position.has_pending():
            pos_state = f"pending 복구"
        else:
            pos_state = '없음'
        self.logger.info(
            f"[시뮬레이션 완료] long_queue={len(self.long_queue)}, short_queue={len(self.short_queue)}, "
            f"가상포지션={pos_state}"
        )

    # =====================================================================
    # 레버리지/가격 계산 (백테스트 line 358-380과 동일)
    # =====================================================================

    def _calculate_entry(self, fvg: ObEntry, direction: str) -> Dict[str, float]:
        """FVG 기반 진입 계산. 백테스트 execute_entry와 동일."""
        taker_fee = self._get_param('TAKER_FEE', 0.0005)
        max_lev = self._get_param('MAX_LEVERAGE', 90)
        risk = self._get_param('RISK_PER_TRADE', 0.02)
        sl_buffer = self._get_param('SL_BUFFER_PCT', 0.005)
        rr = self._get_param('RR', 1.5)

        if direction == 'LONG':
            ep = fvg.top
            sl_edge = fvg.bot * (1.0 - sl_buffer)
            sl_dist = ep - sl_edge
        else:
            ep = fvg.bot
            sl_edge = fvg.top * (1.0 + sl_buffer)
            sl_dist = sl_edge - ep

        if sl_dist <= 0:
            return None

        sl_pct = sl_dist / ep
        eff_sl = sl_pct + taker_fee * 2.0
        lev = risk / eff_sl
        lev = max(1.0, min(lev, max_lev))

        notional = self.capital * lev
        size = notional / ep
        liq = ep * (1.0 - 1.0 / lev) if direction == 'LONG' else ep * (1.0 + 1.0 / lev)

        if direction == 'LONG':
            tp = ep + rr * sl_dist
        else:
            tp = ep - rr * sl_dist

        return {
            'entry_price': ep,
            'sl_price': sl_edge,
            'tp_price': tp,
            'leverage': lev,
            'size': size,
            'liq_price': liq
        }

    # =====================================================================
    # 1h 봉 마감 처리 (HTF EMA200 업데이트)
    # =====================================================================

    async def on_htf_kline(self, kline: Dict):
        """1h kline 수신 시 HTF EMA200 업데이트"""
        if not self.initialized:
            return
        self.candle_manager.update_htf_kline(kline)

    # =====================================================================
    # 15분봉 마감 처리
    # =====================================================================

    async def on_candle_close(self, kline: Dict):
        is_closed = self.candle_manager.update_from_kline(kline)
        if not is_closed:
            return

        self._bar_idx += 1
        candle_time = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)
        close = float(kline['c'])

        pp = Config.get_price_precision(self.symbol_type)
        self.logger.info(
            f"{self.tf} | {candle_time.strftime('%H:%M')} | "
            f"O:{float(kline['o']):.{pp}f} H:{float(kline['h']):.{pp}f} "
            f"L:{float(kline['l']):.{pp}f} C:{close:.{pp}f}"
        )

        # 1. 대기주문 체결 확인
        if self.position.has_pending() and not self.position.has_position():
            await self._check_pending_fill()

        # 이번 봉 중 exit 발생 → 백테스트 `continue` 매칭: FVG 감지/invalidation/entry 스킵
        if self._exit_this_bar:
            self.logger.info(
                "[bar close] 이번 봉에 포지션 exit 발생 → FVG 감지/invalidation/entry 스킵 (backtest continue 매칭)"
            )
            self._exit_this_bar = False
            self._save_state()
            return

        # 2. OB 감지 (백테스트 _common_swap.py 와 동일: impulse 패턴 + lookback 윈도우 lowest/highest)
        impulse_lookback = self._get_param('IMPULSE_LOOKBACK', 17)
        impulse_min_pct = self._get_param('IMPULSE_MIN_PCT', 0.025)
        obs = self.candle_manager.detect_ob(impulse_lookback, impulse_min_pct)
        if obs:
            for ob in obs:
                if ob['type'] == 'LONG':
                    self.long_queue.add(ob['top'], ob['bot'], self._bar_idx)
                    self.logger.info(f"  [OB] LONG 감지: top={ob['top']:.{pp}f}, bot={ob['bot']:.{pp}f}")
                else:
                    self.short_queue.add(ob['top'], ob['bot'], self._bar_idx)
                    self.logger.info(f"  [OB] SHORT 감지: top={ob['top']:.{pp}f}, bot={ob['bot']:.{pp}f}")

        # 3. Invalidation + Timeout (백테스트 line 316-327)
        max_wait = self._get_param('MAX_WAIT', 20)
        self.long_queue.invalidate_long(close)
        self.short_queue.invalidate_short(close)
        self.long_queue.timeout(self._bar_idx, max_wait)
        self.short_queue.timeout(self._bar_idx, max_wait)

        # 4. 포지션 없으면 진입 시도
        if not self.position.has_position():
            # 이번 봉에서 고를 신규 후보를 먼저 계산
            candidate = self._compute_entry_candidate()

            # 기존 pending이 있으면 후보와 비교 (direction + entry_price 동일하면 재배치 불필요)
            if self.position.has_pending():
                if candidate and self._pending_matches(candidate):
                    pp = Config.get_price_precision(self.symbol_type)
                    self.logger.info(
                        f"[pending 유지] {self.position.pending_direction} "
                        f"@ ${self.position.pending_entry_price:.{pp}f} 동일 - 재배치 스킵"
                    )
                    self._save_state()
                    return

                cancel_ok = await self._cancel_pending()
                if not cancel_ok:
                    self.logger.warning("대기주문 취소 실패 - 새 진입 시도 보류")
                    self._save_state()
                    return

            if candidate:
                direction, calc = candidate
                await self._place_pending(calc, direction)

        self._save_state()

    async def _check_pending_fill(self):
        """대기 지정가 주문 체결 확인. CANCELLED/PARTIALLY_FILLED 처리 포함."""
        oid = self.position.pending_order_id
        if not oid:
            return

        if self.is_dry_run():
            # DRY: 마지막 봉의 high/low로 fill 판단
            last = self.candle_manager.df.iloc[-1] if len(self.candle_manager.df) > 0 else None
            if last is not None:
                if self.position.pending_direction == 'LONG' and last['low'] <= self.position.pending_entry_price:
                    await self._on_entry_filled_dry()
                    return
                elif self.position.pending_direction == 'SHORT' and last['high'] >= self.position.pending_entry_price:
                    await self._on_entry_filled_dry()
                    return
            return

        try:
            order_status = await self.binance.get_order_status(oid)
            if order_status is None:
                # 주문 자체가 거래소에 없음 → 정리
                self.logger.warning(f"대기주문 {oid} 거래소에 없음 - 상태 정리")
                self.position.pending_order_id = None
                self.position.pending_direction = None
                self._save_state()
                return

            status = order_status.get('status', '')
            executed_qty = float(order_status.get('executedQty', 0))
            orig_qty = float(order_status.get('origQty', self.position.pending_size))

            if status == 'FILLED':
                avg_price = float(order_status.get('avgPrice', self.position.pending_entry_price))
                await self._on_entry_filled(avg_price, executed_qty, order_status)
            elif status == 'PARTIALLY_FILLED' and executed_qty > 0:
                # 부분 체결 중엔 포지션 가드 (SL/TP) 걸지 않음. FILLED 될 때까지 대기.
                # (중간에 SL/TP 걸면 나머지 fill 이 orphan 포지션 됨 — 2026-04-24 XRP 516.7 중 52만 인식 버그 원인)
                self.logger.info(f"부분 체결 진행 중: {executed_qty}/{orig_qty} - FILLED 대기 (포지션 가드 보류)")
            elif status in ('CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'):
                # 거래소가 취소함 (마진 부족, price band 등)
                if executed_qty > 0:
                    avg_price = float(order_status.get('avgPrice', self.position.pending_entry_price))
                    self.logger.warning(f"취소 전 부분 체결: {executed_qty} - 부분 진입 처리")
                    await self._on_entry_filled(avg_price, executed_qty, order_status)
                else:
                    self.logger.info(f"대기주문 거래소에 의해 취소됨 ({status}): {oid}")
                    self.position.pending_order_id = None
                    self.position.pending_direction = None
                    self._save_state()
        except Exception as e:
            self.logger.warning(f"대기주문 상태 확인 실패: {e}")

    async def _on_entry_filled(self, avg_price: float, executed_qty: float, order_info: Dict):
        """LIVE: 지정가 진입 체결 처리. 포지션 확인 + SL→TP 강건 시도 + 실패 시 긴급 청산"""
        direction = self.position.pending_direction
        self.logger.info(f"[LIVE] {direction} 진입 체결 감지: ${avg_price:.4f}, 수량: {executed_qty:.6f}")

        # 1) 바이낸스 반영 대기 (15회 0.5초 = 7.5초)
        # 사이즈 판단 우선순위: order.executed_qty (이 주문의 체결량, 정확) > pos_info['size'] (계정 전체 포지션)
        # pos_info 는 entry_price 교차검증용으로만 사용.
        # (2026-04-24 XRP 버그: pos_info['size'] 가 부분체결 순간 값을 반환 → 이후 추가체결 놓침)
        actual_size = executed_qty
        actual_entry = avg_price
        position_confirmed = False
        for attempt in range(15):
            try:
                pos_info = await self.binance.get_position_info()
                if pos_info is not None:
                    # entry_price 는 pos_info (거래소 avg) 신뢰
                    actual_entry = pos_info['entry_price']
                    # size 는 order.executed_qty 유지 (pos_info['size'] 로 덮어쓰지 않음)
                    # 단, pos_info['size'] 와 executed_qty 불일치 시 경고
                    pos_size = pos_info.get('size', 0)
                    if abs(pos_size - executed_qty) > 0.001:
                        self.logger.warning(
                            f"[LIVE] 포지션 사이즈 불일치: pos_info={pos_size:.6f} vs order.executed={executed_qty:.6f} "
                            f"(order 기준 사용; 기존 포지션 잔여 또는 stale 조회 가능성)"
                        )
                    position_confirmed = True
                    self.logger.info(
                        f"[LIVE] 포지션 확인 (시도 {attempt+1}): entry=${actual_entry:.4f}, "
                        f"size={actual_size:.6f} (order 기준), pos_info size={pos_size:.6f}"
                    )
                    break
            except Exception as e:
                self.logger.warning(f"포지션 조회 실패 (시도 {attempt+1}/15): {e}")
            await asyncio.sleep(0.5)

        if not position_confirmed:
            # 포지션 확인 실패 → fill 정보로 강행 (order.executed_qty 가 authoritative 이므로 동일)
            self.logger.critical(
                f"[CRITICAL] 포지션 확인 7.5초간 불가 - fill 정보로 강행 (avg=${avg_price:.4f}, qty={executed_qty})"
            )
            actual_entry = avg_price
            actual_size = executed_qty

        # 2) SL/TP 재계산 (실제 체결가 기준)
        sl_dist = abs(actual_entry - self.position.pending_sl_price)
        rr = self._get_param('RR', 1.5)
        if direction == 'LONG':
            tp_price = actual_entry + rr * sl_dist
        else:
            tp_price = actual_entry - rr * sl_dist

        lev = self.position.pending_leverage
        if direction == 'LONG':
            liq = actual_entry * (1.0 - 1.0 / lev)
        else:
            liq = actual_entry * (1.0 + 1.0 / lev)

        self.position.direction = direction
        self.position.entry_price = actual_entry
        self.position.entry_time = datetime.now(pytz.UTC)
        self.position.entry_size = actual_size
        self.position.take_profit = tp_price
        self.position.stop_loss = self.position.pending_sl_price
        self.position.leverage = lev
        self.position.liq_price = liq
        self.position.entry_order_id = order_info.get('orderId')
        self.position.entry_time_ms = order_info.get('updateTime', int(time.time() * 1000))

        # 대기 정보 클리어
        self.position.pending_order_id = None
        self.position.pending_direction = None
        self._save_state()
        self._record_trade('ENTRY', actual_entry, actual_size, 0)
        self.logger.info(f"[LIVE] {direction} 진입! 진입가=${actual_entry:.4f}, SL=${self.position.stop_loss:.4f}, TP=${tp_price:.4f}")

        # 3) SL 먼저 설정 (1초 간격 60회 = 1분 재시도)
        sl_ok = await self._set_sl_order()
        if not sl_ok:
            self.logger.error("[LIVE] SL 1분간 설정 실패 - 긴급 시장가 청산!")
            await self._emergency_close()
            return

        # 4) TP 설정 (1초 간격 60회 = 1분 재시도)
        tp_ok = await self._set_tp_order()
        if not tp_ok:
            self.logger.error("[LIVE] TP 1분간 설정 실패 - 긴급 시장가 청산!")
            await self._emergency_close()
            return

        # 5) FVG 큐 클리어 (백테스트와 동일)
        if direction == 'LONG':
            self.long_queue.clear()
        else:
            self.short_queue.clear()

        self._save_state()
        self.logger.info(f"[LIVE] {direction} 포지션 보호 완료 (SL/TP 모두 설정)")

    async def _emergency_close(self):
        """긴급 시장가 청산 (자기 심볼 주문/포지션만 처리)"""
        # 가상 포지션은 실제 주문 없음 → reset만
        if self.position.is_virtual:
            self.logger.warning("[가상] 긴급 청산 요청 → 가상 포지션 제거")
            self.position.reset()
            self._exit_this_bar = True
            self._save_state()
            return
        try:
            await self.binance.cancel_all_orders()
            await self.binance.close_position_market(
                direction=self.position.direction,
                quantity=self.position.entry_size
            )
            self.logger.warning(f"[LIVE] 긴급 시장가 청산 완료")
            # PnL 기록
            net_pnl = self._calc_local_pnl(self.position.entry_price, 'SL')  # taker 수수료 적용
            self.capital += net_pnl
            self._record_trade('EMERGENCY', self.position.entry_price, self.position.entry_size, net_pnl)
        except Exception as e:
            self.logger.error(f"긴급 청산 실패! 수동 확인 필요: {e}")
        finally:
            self.position.reset()
            self._exit_this_bar = True
            self._save_state()

    async def _on_entry_filled_dry(self):
        """DRY: 가상 진입 체결"""
        direction = self.position.pending_direction
        ep = self.position.pending_entry_price

        lev = self.position.pending_leverage
        if direction == 'LONG':
            liq = ep * (1.0 - 1.0 / lev)
        else:
            liq = ep * (1.0 + 1.0 / lev)

        self.position.direction = direction
        self.position.entry_price = ep
        self.position.entry_time = datetime.now(pytz.UTC)
        self.position.entry_size = self.position.pending_size
        self.position.take_profit = self.position.pending_tp_price
        self.position.stop_loss = self.position.pending_sl_price
        self.position.leverage = lev
        self.position.liq_price = liq
        self.position.tp_order_id = f"DRY_TP_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.position.sl_order_id = f"DRY_SL_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.position.pending_order_id = None
        self.position.pending_direction = None

        if direction == 'LONG':
            self.long_queue.clear()
        else:
            self.short_queue.clear()

        self._save_state()
        self._record_trade('ENTRY', ep, self.position.entry_size, 0)
        pp = Config.get_price_precision(self.symbol_type)
        self.logger.info(
            f"[DRY] {direction} 진입 체결: ${ep:.{pp}f}, "
            f"TP=${self.position.take_profit:.{pp}f}, SL=${self.position.stop_loss:.{pp}f}"
        )

    async def _cancel_pending(self, max_retries: int = 60) -> bool:
        """
        대기 지정가 주문 취소. 1초 간격 60회 재시도 (1분).
        Returns:
            True: pending이 정리됨 (취소되었거나 거래소에 이미 없음)
            False: 1분간 정리 실패 OR 이미 체결됨 (caller가 처리)
        """
        oid = self.position.pending_order_id
        if not oid:
            return True

        if self.is_dry_run():
            self.position.pending_order_id = None
            self.position.pending_direction = None
            self.logger.info(f"[DRY] 대기주문 취소: {oid}")
            return True

        for attempt in range(max_retries):
            try:
                # 1) 주문 상태 확인
                status_data = await self.binance.get_order_status(oid)

                if status_data is None:
                    # 거래소에 주문 없음
                    self.position.pending_order_id = None
                    self.position.pending_direction = None
                    self.logger.info(f"대기주문 {oid} 거래소에 없음 - 상태 정리")
                    return True

                status = status_data.get('status', '')

                # 이미 취소/만료/거부됨
                if status in ('CANCELED', 'CANCELLED', 'EXPIRED', 'REJECTED'):
                    self.position.pending_order_id = None
                    self.position.pending_direction = None
                    self.logger.info(f"대기주문 이미 종결됨 ({status}): {oid}")
                    return True

                # 이미 체결됨 → caller가 fill 처리해야 함
                if status in ('FILLED', 'PARTIALLY_FILLED'):
                    self.logger.warning(f"취소 시도 중 주문 체결됨 ({status}): {oid}")
                    return False

                # NEW/PENDING_NEW → 취소 시도
                cancelled = await self.binance.cancel_order(oid)
                if cancelled:
                    self.position.pending_order_id = None
                    self.position.pending_direction = None
                    self.logger.info(f"대기주문 취소 성공 (시도 {attempt+1}): {oid}")
                    return True
            except Exception as e:
                self.logger.warning(f"대기주문 취소 시도 {attempt+1}/{max_retries} 실패: {e}")

            await asyncio.sleep(1)

        self.logger.error(f"[CRITICAL] 대기주문 1분간 취소 실패 - 수동 확인 필요: {oid}")
        return False

    async def _check_switch_pending(self, price: float):
        """
        on_tick에서 호출. 양쪽 FVG 모두 valid한 경우 히스테리시스 스위칭.
        조건: 5초 throttle + 0.05% 가격 변화 임계 + 40/60% 히스테리시스

        BT_LONG_FIRST 모드 (SOL bt_31): hysteresis 없음 — 즉시 return.
        """
        if self.strategy_mode == 'BT_LONG_FIRST':
            return
        if not self.position.has_pending() or self.position.has_position():
            return

        # 1) 시간 throttle (5초)
        now = time.monotonic()
        if now - self._last_switch_time < self._switch_throttle_sec:
            return

        # 2) 가격 변화 임계 (0.05%)
        if self._last_eval_price > 0 and price > 0:
            if abs(price - self._last_eval_price) / price < self._switch_price_threshold:
                return
        self._last_eval_price = price

        # 3) 양쪽 큐 모두 valid한지 확인
        long_pair, short_pair = self._get_best_entries()
        if long_pair is None or short_pair is None:
            return  # 한쪽만 → 스위칭 불필요

        long_entry = long_pair[0]
        short_entry = short_pair[0]

        # 비정상 케이스
        if short_entry <= long_entry:
            return

        # 4) 40/60% 히스테리시스 적용
        rng = short_entry - long_entry
        threshold_low = long_entry + rng * self._hysteresis_low
        threshold_high = long_entry + rng * self._hysteresis_high

        current_dir = self.position.pending_direction
        new_dir = None

        if current_dir == 'SHORT' and price <= threshold_low:
            new_dir = 'LONG'
        elif current_dir == 'LONG' and price >= threshold_high:
            new_dir = 'SHORT'

        if new_dir and new_dir != current_dir:
            self.logger.info(
                f"[스위칭] {current_dir} → {new_dir} | price=${price:.4f}, "
                f"range=[{long_entry:.4f}~{short_entry:.4f}], "
                f"thresh=[{threshold_low:.4f}~{threshold_high:.4f}]"
            )
            try:
                cancel_ok = await self._cancel_pending()
                if not cancel_ok:
                    self.logger.warning("스위칭: 기존 주문 취소 실패 - 다음 기회에 재시도")
                    return  # 이중 주문 방지
                if new_dir == 'LONG':
                    calc = self._calculate_entry(long_pair[1], 'LONG')
                else:
                    calc = self._calculate_entry(short_pair[1], 'SHORT')
                if calc:
                    await self._place_pending(calc, new_dir)
                self._last_switch_time = now
            except Exception as e:
                self.logger.error(f"스위칭 실패: {e}")

    def _get_best_entries(self):
        """양쪽 큐의 best (entry_price, fvg) 반환. 사용 가능하지 않으면 None"""
        trade_dir = self._get_param('TRADE_DIRECTION', 'BOTH')
        htf = self.candle_manager.get_htf_filter()

        long_pair = None
        short_pair = None

        # 방금 마감된 봉에서 감지된 FVG 도 포함해 newest 선택.
        # 백테스트는 바 i 안에서 "bar_idx < i" 조건으로 이전 봉 FVG 만 보지만,
        # 이는 바 i 의 OHLC 를 그 바 처리 중에 이미 관측 가능하다는 전제 (continuous loop).
        # Live 는 바 N 마감 "후" pending 을 올려 바 N+1 에서 체결되는 구조라,
        # 바 N 에서 방금 감지된 FVG(bar_idx=N)를 포함해야 backtest 의 "바 N+1 entry" 와 타이밍이 맞음.
        # → get_newest_before(self._bar_idx) 에서 get_newest() 로 교체하여 1봉 지연 제거.
        if trade_dir in ['BOTH', 'LONG'] and htf['bull'] and len(self.long_queue) > 0:
            best = self.long_queue.get_newest()
            if best:
                long_pair = (best.top, best)

        if trade_dir in ['BOTH', 'SHORT'] and htf['bear'] and len(self.short_queue) > 0:
            best = self.short_queue.get_newest()
            if best:
                short_pair = (best.bot, best)

        return long_pair, short_pair

    def _select_direction(self, current_price: float, long_entry: Optional[float], short_entry: Optional[float]) -> Optional[str]:
        """
        40/60% 히스테리시스로 진입 방향 결정.
        - LONG entry < SHORT entry (정상 케이스: SHORT 위, LONG 아래)
        - 가격 ≤ 40% line → LONG
        - 가격 ≥ 60% line → SHORT
        - dead zone (40~60%) → LONG 우선 (백테스트 priority)
        """
        if long_entry is None and short_entry is None:
            return None
        if long_entry is None:
            return 'SHORT'
        if short_entry is None:
            return 'LONG'

        # 비정상: SHORT 진입가가 LONG 진입가보다 낮거나 같음 → LONG 우선
        if short_entry <= long_entry:
            return 'LONG'

        rng = short_entry - long_entry
        threshold_low = long_entry + rng * self._hysteresis_low   # 40% line
        threshold_high = long_entry + rng * self._hysteresis_high  # 60% line

        if current_price <= threshold_low:
            return 'LONG'
        elif current_price >= threshold_high:
            return 'SHORT'
        else:
            return 'LONG'  # dead zone → LONG 우선

    def _compute_entry_candidate(self) -> Optional[Tuple[str, Dict]]:
        """양쪽 FVG 평가 후 단일 후보 산출 (direction, calc). 주문은 하지 않음.

        STRATEGY_MODE='BT_LONG_FIRST': BT _common_swap.py 와 동일하게 LONG 우선
            (양쪽 valid 시 항상 LONG 채택, hysteresis 없음)
        STRATEGY_MODE='HYSTERESIS' (기본): 40/60 line 으로 가까운 쪽 채택
        """
        long_pair, short_pair = self._get_best_entries()
        if long_pair is None and short_pair is None:
            return None

        # BT 매칭 모드: LONG 우선, hysteresis 없음 (_common_swap.py 의 entry block 순서)
        if self.strategy_mode == 'BT_LONG_FIRST':
            if long_pair:
                calc = self._calculate_entry(long_pair[1], 'LONG')
                return ('LONG', calc) if calc else None
            if short_pair:
                calc = self._calculate_entry(short_pair[1], 'SHORT')
                return ('SHORT', calc) if calc else None
            return None

        # 기본 (HYSTERESIS): 40/60 line
        current_price = self.candle_manager.get_last_close()
        if current_price is None:
            return None

        long_entry = long_pair[0] if long_pair else None
        short_entry = short_pair[0] if short_pair else None

        direction = self._select_direction(current_price, long_entry, short_entry)
        if direction is None:
            return None

        if direction == 'LONG' and long_pair:
            calc = self._calculate_entry(long_pair[1], 'LONG')
            return ('LONG', calc) if calc else None
        if direction == 'SHORT' and short_pair:
            calc = self._calculate_entry(short_pair[1], 'SHORT')
            return ('SHORT', calc) if calc else None
        return None

    def _pending_matches(self, candidate: Tuple[str, Dict]) -> bool:
        """기존 pending이 신규 후보와 동일한지 (direction + entry_price 기준)."""
        direction, calc = candidate
        if self.position.pending_direction != direction:
            return False
        # entry_price는 FVG 경계값(top/bot)이라 float 비교 가능하지만 안전하게 1e-9 허용
        return abs(self.position.pending_entry_price - calc['entry_price']) < 1e-9

    async def _place_pending(self, calc: Dict, direction: str):
        """지정가 진입 주문 배치"""
        ep = calc['entry_price']
        lev = calc['leverage']
        size = calc['size']

        self.logger.info(f"{'='*50}")
        self.logger.info(f"  {direction} 지정가 진입 대기")
        self.logger.info(f"  진입가: ${ep:.4f}")
        self.logger.info(f"  SL: ${calc['sl_price']:.4f}, TP: ${calc['tp_price']:.4f}")
        self.logger.info(f"  레버리지: {lev:.2f}x, 수량: {size:.6f}")
        self.logger.info(f"{'='*50}")

        if self.is_dry_run():
            self.position.pending_order_id = f"DRY_PENDING_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        else:
            # 지정가 진입 1초 간격 10회 재시도 (10초)
            order = None
            for attempt in range(10):
                try:
                    order = await self.binance.place_limit_entry(
                        direction=direction,
                        price=ep,
                        quantity=size,
                        leverage=math.ceil(lev)
                    )
                    if order:
                        self.logger.info(f"지정가 진입 주문 성공 (시도 {attempt+1})")
                        break
                except Exception as e:
                    self.logger.warning(f"지정가 진입 실패 (시도 {attempt+1}/10): {e}")
                await asyncio.sleep(1)
            if order is None:
                self.logger.error("지정가 진입 10회 실패 - 진입 취소")
                return
            self.position.pending_order_id = str(order.get('orderId', ''))

        self.position.pending_direction = direction
        self.position.pending_entry_price = ep
        self.position.pending_sl_price = calc['sl_price']
        self.position.pending_tp_price = calc['tp_price']
        self.position.pending_leverage = lev
        self.position.pending_size = size
        self._save_state()

    # =====================================================================
    # TP/SL 주문 설정
    # =====================================================================

    async def _set_tp_order(self, max_retries: int = 60) -> bool:
        """TP 주문 1초 간격 재시도. 매 시도 전 포지션 존재 확인."""
        if self.is_dry_run() or not self.position.has_position() or self.position.is_virtual:
            return True
        for attempt in range(max_retries):
            try:
                # 매 시도 전 포지션 확인 (포지션 사라지면 TP가 더 이상 필요없음)
                pos_info = await self.binance.get_position_info()
                if pos_info is None:
                    self.logger.warning(f"TP 시도 중 포지션 사라짐 - TP 설정 불필요")
                    return True

                order = await self.binance.place_limit_close(
                    direction=self.position.direction,
                    price=self.position.take_profit,
                    quantity=self.position.entry_size,
                    retry_on_reduce_only=True
                )
                if order:
                    self.position.tp_order_id = str(order.get('orderId', ''))
                    self.logger.info(f"TP 주문 설정: ${self.position.take_profit:.4f} (시도 {attempt+1})")
                    return True
            except Exception as e:
                self.logger.warning(f"TP 설정 실패 (시도 {attempt+1}/{max_retries}): {e}")
            await asyncio.sleep(1)
        return False

    async def _set_sl_order(self, max_retries: int = 60) -> bool:
        """SL 주문 1초 간격 재시도. 매 시도 전 포지션 존재 확인."""
        if self.is_dry_run() or not self.position.has_position() or self.position.is_virtual:
            return True
        for attempt in range(max_retries):
            try:
                pos_info = await self.binance.get_position_info()
                if pos_info is None:
                    self.logger.warning(f"SL 시도 중 포지션 사라짐 - SL 설정 불필요")
                    return True

                order = await self.binance.set_stop_loss(
                    direction=self.position.direction,
                    stop_price=self.position.stop_loss
                )
                if order:
                    self.position.sl_order_id = str(order.get('orderId', order.get('algoId', '')))
                    self.logger.info(f"SL 주문 설정: ${self.position.stop_loss:.4f} (시도 {attempt+1})")
                    return True
            except Exception as e:
                self.logger.warning(f"SL 설정 실패 (시도 {attempt+1}/{max_retries}): {e}")
            await asyncio.sleep(1)
        return False

    # =====================================================================
    # 틱데이터 TP/SL 감지
    # =====================================================================

    async def on_tick(self, price: float):
        if not self.initialized:
            return

        # 1) 대기 지정가 주문 체결 감지 (포지션 없을 때)
        if self.position.has_pending() and not self.position.has_position():
            pending_dir = self.position.pending_direction
            pending_ep = self.position.pending_entry_price
            # LONG: price <= ep → 체결 가능, SHORT: price >= ep
            touched = (pending_dir == 'LONG' and price <= pending_ep) or \
                      (pending_dir == 'SHORT' and price >= pending_ep)
            if touched:
                if self.is_dry_run():
                    await self._on_entry_filled_dry()
                    return
                # LIVE: throttled API 콜
                now = time.monotonic()
                if now - self._last_tick_api_time >= self._tick_api_min_interval:
                    self._last_tick_api_time = now
                    try:
                        await self._check_pending_fill()
                    except Exception as e:
                        self.logger.warning(f"틱 기반 pending 체결 확인 실패: {e}")
            else:
                # 체결 안 된 경우 → 양쪽 valid면 hysteresis 스위칭 체크
                await self._check_switch_pending(price)
            return

        if not self.position.has_position():
            return

        # 가상 포지션: 실제 주문 없이 가격만으로 청산 감지
        if self.position.is_virtual:
            direction = self.position.direction
            tp = self.position.take_profit
            sl = self.position.stop_loss
            liq = self.position.liq_price

            exit_type = None
            if liq > 0:
                if (direction == 'LONG' and price <= liq) or (direction == 'SHORT' and price >= liq):
                    exit_type = 'LIQ'
            if exit_type is None:
                if (direction == 'LONG' and price <= sl) or (direction == 'SHORT' and price >= sl):
                    exit_type = 'SL'
            if exit_type is None:
                if (direction == 'LONG' and price >= tp) or (direction == 'SHORT' and price <= tp):
                    exit_type = 'TP'

            if exit_type:
                pp = Config.get_price_precision(self.symbol_type)
                self.logger.info(
                    f"[가상 청산] {exit_type} @ ${price:.{pp}f} | {direction} 가상 포지션 제거 → 실거래 가능"
                )
                self.position.reset()
                self._exit_this_bar = True
                self._save_state()
            return

        direction = self.position.direction
        tp = self.position.take_profit
        sl = self.position.stop_loss
        liq = self.position.liq_price

        # LIQ 체크 (백테스트와 동일: LIQ > SL > TP 우선순위)
        if liq > 0:
            liq_hit = (direction == 'LONG' and price <= liq) or (direction == 'SHORT' and price >= liq)
            if liq_hit:
                self.logger.error(f"[LIQ] 청산가 도달: ${price:.4f} (liq=${liq:.4f})")
                if self.is_dry_run():
                    # DRY: capital을 0에 가깝게 (백테스트 line 174: cap=0)
                    self.capital = max(self.capital * 0.01, 0)
                    self._record_trade('LIQ', liq, self.position.entry_size, -self.capital)
                    self.position.reset()
                    self._exit_this_bar = True
                    self._save_state()
                return

        # SL 체크
        sl_reached = (direction == 'LONG' and price <= sl) or (direction == 'SHORT' and price >= sl)
        if sl_reached:
            if self.is_dry_run():
                await self.on_sl_filled(sl)
                return
            now = time.monotonic()
            if now - self._last_tick_api_time < self._tick_api_min_interval:
                return
            self._last_tick_api_time = now
            try:
                pos_info = await self.binance.get_position_info()
            except Exception:
                return
            if pos_info is None:
                await self.on_sl_filled(sl)
            elif self.position.sl_order_id:
                status = await self.binance.get_order_status(self.position.sl_order_id)
                if status and status.get('status') == 'FILLED':
                    await self.on_sl_filled(sl)
            return

        # TP
        tp_reached = (direction == 'LONG' and price >= tp) or (direction == 'SHORT' and price <= tp)
        if tp_reached:
            if self.is_dry_run():
                await self.on_tp_filled(tp)
                return
            now = time.monotonic()
            if now - self._last_tick_api_time < self._tick_api_min_interval:
                return
            self._last_tick_api_time = now
            if self.position.tp_order_id:
                status = await self.binance.get_order_status(self.position.tp_order_id)
                if status and status.get('status') == 'FILLED':
                    await self.on_tp_filled(tp)

    # =====================================================================
    # 청산 처리 (실제 PnL 조회)
    # =====================================================================

    async def _get_actual_pnl(self) -> Optional[float]:
        if self.is_dry_run() or not self.position.entry_order_id:
            return None
        try:
            result = await self.binance.get_actual_trade_pnl(
                entry_order_id=self.position.entry_order_id,
                entry_time_ms=self.position.entry_time_ms
            )
            if result:
                self.logger.info(
                    f"[실제PnL] rpnl=${result['realized_pnl']:.4f}, "
                    f"진입fee=${result['entry_commission']:.4f}, "
                    f"청산fee=${result['exit_commission']:.4f}, "
                    f"순익=${result['net_pnl']:.4f}"
                )
                return result['net_pnl']
        except Exception as e:
            self.logger.warning(f"실제 PnL 조회 실패: {e}")
        return None

    def _calc_local_pnl(self, exit_price: float, exit_type: str) -> float:
        """로컬 PnL 계산 (fallback)"""
        maker = self._get_param('MAKER_FEE', 0.0002)
        taker = self._get_param('TAKER_FEE', 0.0005)

        if self.position.direction == 'LONG':
            pnl_raw = (exit_price - self.position.entry_price) * self.position.entry_size
        else:
            pnl_raw = (self.position.entry_price - exit_price) * self.position.entry_size

        # 진입: MAKER (지정가), 청산 TP: MAKER, SL: TAKER
        entry_fee = self.position.entry_price * self.position.entry_size * maker
        if exit_type == 'TP':
            exit_fee = exit_price * self.position.entry_size * maker
        else:
            exit_fee = exit_price * self.position.entry_size * taker

        return pnl_raw - entry_fee - exit_fee

    async def on_tp_filled(self, exit_price: float):
        # 가상 포지션은 tick 경로에서 처리. 방어적으로 여기서도 차단
        if self.position.is_virtual:
            self.logger.info(f"[가상] TP 도달 @ ${exit_price:.4f} → 가상 청산")
            self.position.reset()
            self._exit_this_bar = True
            self._save_state()
            return

        mode = "[DRY]" if self.is_dry_run() else "[LIVE]"
        self.logger.info(f"{mode} TP 체결: ${exit_price:.4f}")

        if not self.is_dry_run():
            await self.binance.cancel_all_orders()

        actual = await self._get_actual_pnl()
        if actual is not None:
            net_pnl = actual
            self.logger.info(f"{mode} TP (실제): 순익=${net_pnl:.2f}")
        else:
            net_pnl = self._calc_local_pnl(exit_price, 'TP')
            self.logger.info(f"{mode} TP (로컬): 순익=${net_pnl:.2f}")

        old = self.capital
        self.capital += net_pnl
        self.logger.info(f"{mode} 자본금: ${old:.2f} → ${self.capital:.2f}")

        self._record_trade('TP', exit_price, self.position.entry_size, net_pnl)
        self.position.reset()
        self._exit_this_bar = True
        self._save_state()

    async def on_sl_filled(self, exit_price: float):
        # 가상 포지션은 tick 경로에서 처리. 방어적으로 여기서도 차단
        if self.position.is_virtual:
            self.logger.info(f"[가상] SL 도달 @ ${exit_price:.4f} → 가상 청산")
            self.position.reset()
            self._exit_this_bar = True
            self._save_state()
            return

        mode = "[DRY]" if self.is_dry_run() else "[LIVE]"
        self.logger.warning(f"{mode} SL 체결: ${exit_price:.4f}")

        if not self.is_dry_run():
            await self.binance.cancel_all_orders()

        actual = await self._get_actual_pnl()
        if actual is not None:
            net_pnl = actual
            self.logger.warning(f"{mode} SL (실제): 순익=${net_pnl:.2f}")
        else:
            net_pnl = self._calc_local_pnl(exit_price, 'SL')
            self.logger.warning(f"{mode} SL (로컬): 순익=${net_pnl:.2f}")

        old = self.capital
        self.capital += net_pnl
        self.logger.warning(f"{mode} 자본금: ${old:.2f} → ${self.capital:.2f}")

        self._record_trade('SL', exit_price, self.position.entry_size, net_pnl)
        self.position.reset()
        self._exit_this_bar = True
        self._save_state()

    # =====================================================================
    # 거래 기록
    # =====================================================================

    def _record_trade(self, trade_type: str, price: float, quantity: float, pnl: float):
        try:
            file_exists = os.path.isfile(self.trades_path)
            with open(self.trades_path, 'a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        'timestamp', 'mode', 'type', 'direction', 'price', 'quantity',
                        'take_profit', 'stop_loss', 'leverage', 'pnl', 'capital'
                    ])
                mode = 'DRY' if self.is_dry_run() else 'LIVE'
                writer.writerow([
                    datetime.now(pytz.UTC).isoformat(), mode, trade_type,
                    self.position.direction or 'N/A', price, quantity,
                    self.position.take_profit if trade_type == 'ENTRY' else '',
                    self.position.stop_loss if trade_type == 'ENTRY' else '',
                    self.position.leverage if trade_type == 'ENTRY' else '',
                    pnl, self.capital
                ])
        except Exception as e:
            self.logger.error(f"거래 기록 실패: {e}")

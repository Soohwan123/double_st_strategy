#!/usr/bin/env python3
"""
Hyper Scalper V2 Strategy
EMA 정배열/역배열 + ADX + Retest 기반 추세추종 전략

핵심 로직:
1. 15분봉 마감 시 신호 체크 → 시장가 진입
2. 동적 레버리지 (손절거리 기반)
3. 동적 익절 (ATR 기반)
4. 틱데이터로 TP/SL 체결 감지
5. 포지션 종료 시 자본금 업데이트

DRY_RUN 모드:
- DRY_RUN=true: 실제 주문 없이 시뮬레이션 (CSV 기록만)
- DRY_RUN=false: 실제 거래 모드
"""

import asyncio
import logging
import csv
import math
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
import pytz
import pandas as pd

from config import DynamicConfig, Config, HYPER_DEFAULT_PARAMS
from state_manager import StateManager
from binance_library import BinanceFuturesClient
from data_handler import CandleDataManager


class HyperPositionState:
    """포지션 상태 관리"""

    def __init__(self):
        self.reset()

    def reset(self):
        """포지션 초기화"""
        self.direction: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_size: float = 0.0
        self.take_profit: float = 0.0
        self.stop_loss: float = 0.0
        self.leverage: float = 1.0
        self.tp_order_id: Optional[str] = None
        self.sl_order_id: Optional[str] = None
        self.entry_order_id: Optional[int] = None
        self.entry_time_ms: int = 0

    def has_position(self) -> bool:
        return self.direction is not None and self.entry_size > 0

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
            'entry_order_id': self.entry_order_id,
            'entry_time_ms': self.entry_time_ms
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
        self.entry_order_id = data.get('entry_order_id')
        self.entry_time_ms = data.get('entry_time_ms', 0)


class HyperScalperStrategy:
    """
    Hyper Scalper V2 전략 클래스

    주요 기능:
    1. 15분봉 마감 시 EMA/ADX/Retest 신호 체크
    2. 신호 발생 시 시장가 진입 + TP/SL 주문 설정
    3. 틱데이터로 TP/SL 체결 감지
    4. 포지션 종료 시 자본금 업데이트

    DRY_RUN 모드:
    - 실제 주문 없이 시뮬레이션
    - CSV에 모든 거래 기록
    - 지표 계산 및 신호 체크는 동일하게 수행
    """

    def __init__(
        self,
        binance: BinanceFuturesClient,
        symbol_type: str,
        logger: logging.Logger
    ):
        """
        Args:
            binance: 바이낸스 API 클라이언트
            symbol_type: 'hyper'
            logger: 로거
        """
        self.binance = binance
        self.symbol_type = symbol_type
        self.logger = logger

        # 담보 자산 (USDC 또는 USDT)
        self.quote_asset = Config.get_quote_asset(symbol_type)

        # 동적 설정 로더
        self.dynamic_config = DynamicConfig(symbol_type)

        # 상태 관리
        self.state_manager = StateManager(
            Config.get_state_path(symbol_type),
            logger
        )
        self.position = HyperPositionState()

        # 캔들 데이터 관리
        self.candle_manager: Optional[CandleDataManager] = None

        # 자본금 (로컬 추적)
        self.capital: float = 0.0
        self.initialized: bool = False

        # 거래 기록 파일
        self.trades_path = Config.get_trades_path(symbol_type)
        os.makedirs(os.path.dirname(self.trades_path), exist_ok=True)

        # 지표 기록 파일
        self.indicators_path = f"{Config.TRADES_DIR}/indicators_{symbol_type}.csv"

        # on_tick API 호출 쓰로틀링 (초당 최대 10회)
        self._last_tick_api_time: float = 0.0
        self._tick_api_min_interval: float = 0.1  # 100ms

    # =========================================================================
    # 설정값 접근
    # =========================================================================

    def _reload_config(self):
        """동적 설정 다시 로드"""
        self.dynamic_config.reload()

    def _get_param(self, key: str, default=None):
        """파라미터 값 가져오기"""
        return self.dynamic_config.get(key, HYPER_DEFAULT_PARAMS.get(key, default))

    def is_dry_run(self) -> bool:
        """DRY RUN 모드 여부 확인"""
        return self._get_param('DRY_RUN', True)

    # =========================================================================
    # 초기화
    # =========================================================================

    async def initialize(self):
        """전략 초기화"""
        self.logger.info("=" * 60)
        self.logger.info("Hyper Scalper V2 Strategy 초기화")

        # 설정 로드
        self._reload_config()

        # 실행 모드 확인
        if self.is_dry_run():
            self.logger.info("*" * 60)
            self.logger.info("*** DRY RUN 모드 ***")
            self.logger.info("*** 실제 주문 없이 시뮬레이션만 수행합니다 ***")
            self.logger.info("*" * 60)
        else:
            self.logger.info("*** LIVE 거래 모드 ***")
            self.logger.warning("*** 실제 자금으로 거래합니다! ***")

        self.logger.info("=" * 60)

        # 캔들 데이터 매니저 생성
        self.candle_manager = CandleDataManager(
            max_candles=500,
            ema_fast=self._get_param('EMA_FAST', 25),
            ema_mid=self._get_param('EMA_MID', 100),
            ema_slow=self._get_param('EMA_SLOW', 200),
            adx_length=self._get_param('ADX_LENGTH', 14),
            atr_length=self._get_param('ATR_LENGTH', 14),
            retest_lookback=self._get_param('RETEST_LOOKBACK', 5),
            sl_lookback=self._get_param('SL_LOOKBACK', 29),
            logger=self.logger
        )

        # 자본금 초기화
        await self._init_capital()

        # 상태 복구
        state = self.state_manager.load_state()
        if state:
            await self._restore_state(state)
        else:
            self.logger.info("새로운 거래 세션 시작")

        self.initialized = True

    async def _init_capital(self):
        """자본금 초기화"""
        # state에서 복구 시도
        state = self.state_manager.load_state()
        if state and 'capital' in state and state['capital'] > 0:
            self.capital = state['capital']
            self.logger.info(f"저장된 자본 복구: ${self.capital:.2f}")
            return

        self.capital = self._get_param('INITIAL_CAPITAL', 1000.0)
        self.logger.info(f"초기 자본 설정: ${self.capital:.2f}")

    async def _restore_state(self, state: Dict[str, Any]):
        """상태 복구"""
        self.logger.info("이전 상태 복구 중...")

        # 자본금 복구
        if 'capital' in state:
            self.capital = state['capital']
            self.logger.info(f"자본금 복구: ${self.capital:.2f}")

        # 포지션 복구
        if 'position' in state and state['position']:
            self.position.from_dict(state['position'])
            self.logger.info(f"포지션 복구: {self.position.direction}")
            self.logger.info(f"진입가: ${self.position.entry_price:.2f}, 수량: {self.position.entry_size:.6f}")
            self.logger.info(f"TP: ${self.position.take_profit:.2f}, SL: ${self.position.stop_loss:.2f}")

        # LIVE 모드에서만 바이낸스 동기화
        if not self.is_dry_run():
            await self._sync_with_binance()

    async def _sync_with_binance(self):
        """바이낸스 실제 포지션과 동기화 (LIVE 모드 전용)"""
        if self.is_dry_run():
            return

        pos_info = await self.binance.get_position_info()

        if pos_info:
            self.logger.info(f"바이낸스 포지션 확인: {pos_info['side']}, 평단가 ${pos_info['entry_price']:.2f}")

            if self.position.has_position():
                # 로컬과 바이낸스 동기화
                self.position.entry_price = pos_info['entry_price']
                self.position.entry_size = pos_info['size']
        else:
            if self.position.has_position():
                self.logger.warning("바이낸스에 포지션 없음 - 로컬 포지션 초기화")
                self.position.reset()

        self._save_state()

    def _save_state(self):
        """현재 상태 저장"""
        state = {
            'capital': self.capital,
            'position': self.position.to_dict() if self.position.has_position() else None
        }
        self.state_manager.save_state(state)

    # =========================================================================
    # 과거 데이터 로드
    # =========================================================================

    async def load_historical_data(self):
        """
        과거 15분봉 데이터 로드 (500개)
        """
        self.logger.info("과거 15분봉 데이터 로드 중...")

        try:
            klines = self.binance.client.futures_klines(
                symbol=self.binance.symbol,
                interval='15m',
                limit=501  # 마지막 미완성 봉 제외용
            )

            candles = []
            # 마지막 캔들(미완성) 제외
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
            self.logger.info(f"15분봉 로드 완료: {len(candles)}개")

            # 현재 지표 상태 로깅
            indicators = self.candle_manager.get_latest_indicators()
            if indicators:
                self.logger.info(f"현재 지표: EMA25={indicators['ema_fast']:.2f}, "
                               f"EMA100={indicators['ema_mid']:.2f}, "
                               f"EMA200={indicators['ema_slow']:.2f}, "
                               f"ADX={indicators['adx']:.2f}, "
                               f"ATR={indicators['atr']:.2f}")

            # 초기 500개 지표 CSV 저장
            self._save_initial_indicators()

        except Exception as e:
            self.logger.error(f"과거 데이터 로드 실패: {e}")
            raise

    def _save_initial_indicators(self):
        """
        초기 로드된 500개 지표를 CSV에 저장
        """
        try:
            all_indicators = self.candle_manager.get_all_indicators()
            if all_indicators is None or len(all_indicators) == 0:
                self.logger.warning("초기 지표 저장 실패: 데이터 없음")
                return

            # CSV 헤더
            headers = [
                'timestamp', 'open', 'high', 'low', 'close',
                'ema_fast', 'ema_mid', 'ema_slow', 'adx', 'atr',
                'bull_trend', 'bear_trend', 'had_low_below_fast',
                'had_high_above_fast', 'reclaim_long', 'reclaim_short',
                'long_signal', 'short_signal', 'position', 'capital'
            ]

            with open(self.indicators_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)

                for _, row in all_indicators.iterrows():
                    # 신호 계산
                    adx_threshold = self._get_param('ADX_THRESHOLD', 30.0)
                    long_signal = (
                        row.get('bull_trend', False) and
                        row.get('adx', 0) >= adx_threshold and
                        row.get('had_low_below_fast', False) and
                        row.get('reclaim_long', False)
                    )
                    short_signal = (
                        row.get('bear_trend', False) and
                        row.get('adx', 0) >= adx_threshold and
                        row.get('had_high_above_fast', False) and
                        row.get('reclaim_short', False)
                    )

                    writer.writerow([
                        row['timestamp'].isoformat() if hasattr(row['timestamp'], 'isoformat') else row['timestamp'],
                        row.get('open', 0),
                        row.get('high', 0),
                        row.get('low', 0),
                        row.get('close', 0),
                        row.get('ema_fast', 0),
                        row.get('ema_mid', 0),
                        row.get('ema_slow', 0),
                        row.get('adx', 0),
                        row.get('atr', 0),
                        row.get('bull_trend', False),
                        row.get('bear_trend', False),
                        row.get('had_low_below_fast', False),
                        row.get('had_high_above_fast', False),
                        row.get('reclaim_long', False),
                        row.get('reclaim_short', False),
                        long_signal,
                        short_signal,
                        'NONE',
                        self.capital
                    ])

            self.logger.info(f"초기 지표 저장 완료: {len(all_indicators)}개 → {self.indicators_path}")

        except Exception as e:
            self.logger.error(f"초기 지표 저장 실패: {e}")

    # =========================================================================
    # 레버리지/가격 계산
    # =========================================================================

    def calculate_leverage(self, entry_price: float, stop_loss: float) -> float:
        """
        손절 거리 기반 레버리지 계산

        Args:
            entry_price: 진입가
            stop_loss: 손절가

        Returns:
            레버리지 (1 ~ MAX_LEVERAGE)
        """
        sl_distance_pct = abs(entry_price - stop_loss) / entry_price
        taker_fee = self._get_param('TAKER_FEE', 0.000275)

        # 진입 수수료 + 손절 수수료 포함
        effective_sl = sl_distance_pct + taker_fee * 2

        risk_per_trade = self._get_param('RISK_PER_TRADE', 0.07)
        max_leverage = self._get_param('MAX_LEVERAGE', 90)

        leverage = risk_per_trade / effective_sl
        leverage = min(leverage, max_leverage)
        leverage = max(leverage, 1)

        return round(leverage, 2)

    def calculate_stop_loss(self, entry_price: float, direction: str) -> float:
        """
        손절가 계산 (최근 N봉 최저/최고 + 최대 거리 캡)

        Args:
            entry_price: 진입가
            direction: 'LONG' 또는 'SHORT'

        Returns:
            손절가
        """
        sl_price = self.candle_manager.get_sl_price(direction)
        if sl_price is None:
            # 기본값: 3%
            max_sl_distance = self._get_param('MAX_SL_DISTANCE', 0.03)
            if direction == 'LONG':
                return entry_price * (1 - max_sl_distance)
            else:
                return entry_price * (1 + max_sl_distance)

        # 최대 거리 캡 적용
        max_sl_distance = self._get_param('MAX_SL_DISTANCE', 0.03)
        sl_distance = abs(entry_price - sl_price) / entry_price

        if sl_distance > max_sl_distance:
            if direction == 'LONG':
                sl_price = entry_price * (1 - max_sl_distance)
            else:
                sl_price = entry_price * (1 + max_sl_distance)

        return sl_price

    def calculate_take_profit(self, entry_price: float, direction: str, atr: float) -> float:
        """
        익절가 계산 (ATR 기반 + 수수료 보전)

        Args:
            entry_price: 진입가
            direction: 'LONG' 또는 'SHORT'
            atr: 현재 ATR 값

        Returns:
            익절가
        """
        taker_fee = self._get_param('TAKER_FEE', 0.0005)
        maker_fee = self._get_param('MAKER_FEE', 0.0002)
        fee_protection = self._get_param('FEE_PROTECTION', True)

        fee_offset = 0
        if fee_protection:
            fee_offset = entry_price * (taker_fee * 2 + maker_fee)

        if direction == 'LONG':
            tp_mult = self._get_param('TP_ATR_MULT_LONG', 4.1)
            return entry_price + atr * tp_mult + fee_offset
        else:
            tp_mult = self._get_param('TP_ATR_MULT_SHORT', 4.1)
            return entry_price - atr * tp_mult - fee_offset

    # =========================================================================
    # 진입 로직
    # =========================================================================

    async def check_entry_signal(self) -> Optional[str]:
        """
        진입 신호 체크

        Returns:
            'LONG', 'SHORT', 또는 None
        """
        if self.position.has_position():
            return None

        trade_direction = self._get_param('TRADE_DIRECTION', 'BOTH')
        adx_threshold = self._get_param('ADX_THRESHOLD', 30.0)

        # LONG 신호
        if trade_direction in ['BOTH', 'LONG']:
            if self.candle_manager.check_long_signal(adx_threshold):
                return 'LONG'

        # SHORT 신호
        if trade_direction in ['BOTH', 'SHORT']:
            if self.candle_manager.check_short_signal(adx_threshold):
                return 'SHORT'

        return None

    async def execute_entry(self, direction: str):
        """
        진입 실행 (DRY/LIVE 모드 분기)

        Args:
            direction: 'LONG' 또는 'SHORT'
        """
        self._reload_config()

        entry_price = self.candle_manager.get_last_close()
        atr = self.candle_manager.get_current_atr()

        if entry_price is None or atr is None:
            self.logger.error("진입 실패: 가격/ATR 데이터 없음")
            return

        # 손절가 계산
        stop_loss = self.calculate_stop_loss(entry_price, direction)

        # 레버리지 계산
        leverage = self.calculate_leverage(entry_price, stop_loss)

        # 익절가 계산
        take_profit = self.calculate_take_profit(entry_price, direction, atr)

        # 포지션 크기 계산
        position_value = self.capital * leverage
        entry_size = position_value / entry_price

        mode_prefix = "[DRY]" if self.is_dry_run() else "[LIVE]"

        self.logger.info(f"{'='*50}")
        self.logger.info(f"{mode_prefix} {direction} 진입 준비")
        self.logger.info(f"진입가: ${entry_price:.2f}")
        self.logger.info(f"손절가: ${stop_loss:.2f} ({abs(entry_price - stop_loss) / entry_price * 100:.2f}%)")
        self.logger.info(f"익절가: ${take_profit:.2f} ({abs(take_profit - entry_price) / entry_price * 100:.2f}%)")
        self.logger.info(f"레버리지: {leverage}x")
        self.logger.info(f"포지션 크기: {entry_size:.6f} BTC (${position_value:.2f})")
        self.logger.info(f"{'='*50}")

        actual_entry_price = entry_price
        actual_size = entry_size

        if not self.is_dry_run():
            # ========== LIVE 모드: 실제 주문 ==========
            order = await self.binance.open_market_position(
                direction=direction,
                quantity=entry_size,
                leverage=math.ceil(leverage)
            )

            if order is None:
                self.logger.error("시장가 진입 실패")
                return

            entry_order_id = order.get('orderId')
            entry_time_ms = order.get('updateTime', int(time.time() * 1000))

            await asyncio.sleep(0.5)
            pos_info = await self.binance.get_position_info()

            if pos_info:
                actual_entry_price = pos_info['entry_price']
                actual_size = pos_info['size']

                stop_loss = self.calculate_stop_loss(actual_entry_price, direction)
                take_profit = self.calculate_take_profit(actual_entry_price, direction, atr)

                self.logger.info(f"실제 체결가: ${actual_entry_price:.2f}, 수량: {actual_size:.6f}")
        else:
            entry_order_id = None
            entry_time_ms = 0
            self.logger.info(f"[DRY] 가상 진입 체결: ${actual_entry_price:.2f}, 수량: {actual_size:.6f}")

        self.position.direction = direction
        self.position.entry_price = actual_entry_price
        self.position.entry_time = datetime.now(pytz.UTC)
        self.position.entry_size = actual_size
        self.position.entry_order_id = entry_order_id
        self.position.entry_time_ms = entry_time_ms
        self.position.take_profit = take_profit
        self.position.stop_loss = stop_loss
        self.position.leverage = leverage

        if not self.is_dry_run():
            # LIVE 모드: TP/SL 주문 설정 (재시도 포함)
            tp_ok = await self._set_tp_order()
            sl_ok = await self._set_sl_order()

            if not tp_ok or not sl_ok:
                self.logger.error(f"TP/SL 주문 설정 실패! TP={tp_ok}, SL={sl_ok}")
                self.logger.error("포지션 보호 불가 - 시장가 긴급 청산 시도")
                try:
                    await self.binance.cancel_all_orders()
                    await self.binance.close_position_market(
                        direction=direction,
                        quantity=actual_size
                    )
                    self.logger.warning("긴급 시장가 청산 완료")
                    self.position.reset()
                    self._save_state()
                    return
                except Exception as e:
                    self.logger.error(f"긴급 청산도 실패! 수동 확인 필요: {e}")
        else:
            # DRY 모드: 가상 주문 ID 생성
            self.position.tp_order_id = f"DRY_TP_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.position.sl_order_id = f"DRY_SL_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.logger.info(f"[DRY] 가상 TP 설정: ${take_profit:.2f}")
            self.logger.info(f"[DRY] 가상 SL 설정: ${stop_loss:.2f}")

        # 상태 저장
        self._save_state()

        # 거래 기록
        self._record_trade('ENTRY', actual_entry_price, actual_size, 0)

        self.logger.info(f"{mode_prefix} {direction} 진입 완료!")

    async def _set_tp_order(self, max_retries: int = 3) -> bool:
        """
        익절 지정가 주문 설정 (LIVE 모드 전용)
        실패 시 재시도 (exponential backoff)

        Returns:
            성공 여부
        """
        if self.is_dry_run() or not self.position.has_position():
            return True

        for attempt in range(max_retries):
            try:
                order = await self.binance.place_limit_close(
                    direction=self.position.direction,
                    price=self.position.take_profit,
                    quantity=self.position.entry_size,
                    retry_on_reduce_only=True
                )

                if order:
                    self.position.tp_order_id = str(order.get('orderId', ''))
                    self.logger.info(f"TP 주문 설정: ${self.position.take_profit:.2f}")
                    return True
                else:
                    self.logger.warning(f"TP 주문 설정 실패 (시도 {attempt + 1}/{max_retries})")

            except Exception as e:
                self.logger.warning(f"TP 주문 설정 예외 (시도 {attempt + 1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1s, 2s
                self.logger.info(f"TP 주문 재시도 대기: {delay}초")
                await asyncio.sleep(delay)

        self.logger.error(f"TP 주문 설정 최종 실패 ({max_retries}회 시도)")
        return False

    async def _set_sl_order(self, max_retries: int = 3) -> bool:
        """
        손절 스탑 마켓 주문 설정 (LIVE 모드 전용)
        실패 시 재시도 (exponential backoff)

        Returns:
            성공 여부
        """
        if self.is_dry_run() or not self.position.has_position():
            return True

        for attempt in range(max_retries):
            try:
                order = await self.binance.set_stop_loss(
                    direction=self.position.direction,
                    stop_price=self.position.stop_loss
                )

                if order:
                    self.position.sl_order_id = str(order.get('orderId', order.get('algoId', '')))
                    self.logger.info(f"SL 주문 설정: ${self.position.stop_loss:.2f}")
                    return True
                else:
                    self.logger.warning(f"SL 주문 설정 실패 (시도 {attempt + 1}/{max_retries})")

            except Exception as e:
                self.logger.warning(f"SL 주문 설정 예외 (시도 {attempt + 1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1s, 2s
                self.logger.info(f"SL 주문 재시도 대기: {delay}초")
                await asyncio.sleep(delay)

        self.logger.error(f"SL 주문 설정 최종 실패 ({max_retries}회 시도)")
        return False

    # =========================================================================
    # 청산 로직
    # =========================================================================

    async def _get_actual_pnl(self, exit_type: str) -> float:
        """바이낸스 API에서 실제 체결 PnL 조회"""
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
            self.logger.warning(f"실제 PnL 조회 실패, 로컬 계산 사용: {e}")

        return None

    async def on_tp_filled(self, exit_price: float):
        mode_prefix = "[DRY]" if self.is_dry_run() else "[LIVE]"
        self.logger.info(f"{mode_prefix} TP 체결 감지: ${exit_price:.2f}")

        if not self.is_dry_run():
            await self.binance.cancel_all_orders()

        actual_pnl = await self._get_actual_pnl('TP')
        if actual_pnl is not None:
            net_pnl = actual_pnl
            self.logger.info(f"{mode_prefix} TP 청산 (실제): 순익=${net_pnl:.2f}")
        else:
            pnl = self._calculate_pnl(exit_price)
            fee = self._calculate_fee(exit_price, 'TP')
            net_pnl = pnl - fee
            self.logger.info(f"{mode_prefix} TP 청산 (로컬): PnL=${pnl:.2f}, 수수료=${fee:.4f}, 순익=${net_pnl:.2f}")

        old_capital = self.capital
        self.capital += net_pnl
        self.logger.info(f"{mode_prefix} 자본금 업데이트: ${old_capital:.2f} → ${self.capital:.2f}")

        self._record_trade('TP', exit_price, self.position.entry_size, net_pnl)
        self.position.reset()
        self._save_state()

    async def on_sl_filled(self, exit_price: float):
        mode_prefix = "[DRY]" if self.is_dry_run() else "[LIVE]"
        self.logger.warning(f"{mode_prefix} SL 체결 감지: ${exit_price:.2f}")

        if not self.is_dry_run():
            await self.binance.cancel_all_orders()

        actual_pnl = await self._get_actual_pnl('SL')
        if actual_pnl is not None:
            net_pnl = actual_pnl
            self.logger.warning(f"{mode_prefix} SL 청산 (실제): 순익=${net_pnl:.2f}")
        else:
            pnl = self._calculate_pnl(exit_price)
            fee = self._calculate_fee(exit_price, 'SL')
            net_pnl = pnl - fee
            self.logger.warning(f"{mode_prefix} SL 청산 (로컬): PnL=${pnl:.2f}, 수수료=${fee:.4f}, 순익=${net_pnl:.2f}")

        old_capital = self.capital
        self.capital += net_pnl
        self.logger.warning(f"{mode_prefix} 자본금 업데이트: ${old_capital:.2f} → ${self.capital:.2f}")

        self._record_trade('SL', exit_price, self.position.entry_size, net_pnl)
        self.position.reset()
        self._save_state()

    def _calculate_pnl(self, exit_price: float) -> float:
        """PnL 계산 (수수료 제외)"""
        if self.position.direction == 'LONG':
            return (exit_price - self.position.entry_price) * self.position.entry_size
        else:
            return (self.position.entry_price - exit_price) * self.position.entry_size

    def _calculate_fee(self, exit_price: float, exit_type: str) -> float:
        """수수료 계산"""
        taker_fee = self._get_param('TAKER_FEE', 0.000275)
        maker_fee = self._get_param('MAKER_FEE', 0.0)

        # 진입 수수료 (TAKER)
        entry_fee = self.position.entry_price * self.position.entry_size * taker_fee

        # 청산 수수료
        if exit_type == 'TP':
            exit_fee = exit_price * self.position.entry_size * maker_fee
        else:  # SL, LIQ
            exit_fee = exit_price * self.position.entry_size * taker_fee

        return entry_fee + exit_fee

    async def _sync_capital_with_binance(self):
        """
        바이낸스 실제 잔고로 자본금 동기화

        거래 종료 후 로컬 계산값과 실제 잔고를 비교하고,
        실제 잔고로 덮어씁니다.
        """
        if self.is_dry_run():
            # DRY 모드에서는 동기화 불필요
            return

        try:
            # 잠시 대기 (바이낸스 서버 반영 시간)
            await asyncio.sleep(0.5)

            balance = await self.binance.get_account_balance(self.quote_asset)
            actual_balance = balance['wallet_balance']

            # 차이 계산
            diff = actual_balance - self.capital

            usable_balance = actual_balance * 0.90  # 90%만 사용

            if abs(diff) > 0.01:  # $0.01 이상 차이나면 로그
                self.logger.warning(
                    f"[자본금 동기화] 로컬: ${self.capital:.2f} → "
                    f"사용가능: ${usable_balance:.2f} (실제 잔고 ${actual_balance:.2f}의 90%)"
                )
            else:
                self.logger.info(
                    f"[자본금 동기화] 사용가능: ${usable_balance:.2f} (실제 잔고 ${actual_balance:.2f}의 90%)"
                )

            # 실제 잔고의 90%로 덮어쓰기
            self.capital = usable_balance

        except Exception as e:
            self.logger.error(f"자본금 동기화 실패: {e}")

    # =========================================================================
    # 틱데이터 처리
    # =========================================================================

    async def on_tick(self, price: float):
        """
        틱데이터 처리 - TP/SL 체결 감지

        DRY 모드: 가격만으로 TP/SL 터치 판단
        LIVE 모드: 가격 터치 후 주문 상태 확인 (쓰로틀링 적용)

        Args:
            price: 현재 가격
        """
        if not self.initialized or not self.position.has_position():
            return

        direction = self.position.direction
        tp_price = self.position.take_profit
        sl_price = self.position.stop_loss

        # TP 체결 감지
        tp_reached = False
        if direction == 'LONG' and price >= tp_price:
            tp_reached = True
        elif direction == 'SHORT' and price <= tp_price:
            tp_reached = True

        if tp_reached:
            if self.is_dry_run():
                # DRY 모드: 가격 터치만으로 체결 처리
                await self.on_tp_filled(tp_price)
                return
            else:
                # LIVE 모드: API 쓰로틀링 (최대 10회/초)
                now = time.monotonic()
                if now - self._last_tick_api_time < self._tick_api_min_interval:
                    return
                self._last_tick_api_time = now

                # 주문 상태 확인
                if self.position.tp_order_id:
                    order_status = await self.binance.get_order_status(self.position.tp_order_id)

                    if order_status:
                        status = order_status.get('status')

                        if status == 'FILLED':
                            await self.on_tp_filled(tp_price)
                            return
                        elif status == 'PARTIALLY_FILLED':
                            executed_qty = float(order_status.get('executedQty', 0))
                            orig_qty = float(order_status.get('origQty', 0))
                            self.logger.info(f"TP 부분체결: {executed_qty}/{orig_qty}")
                return  # TP 가격 도달 시 SL 체크 불필요

        # SL 체결 감지
        sl_reached = False
        if direction == 'LONG' and price <= sl_price:
            sl_reached = True
        elif direction == 'SHORT' and price >= sl_price:
            sl_reached = True

        if sl_reached:
            if self.is_dry_run():
                # DRY 모드: 가격 터치만으로 체결 처리
                await self.on_sl_filled(sl_price)
                return
            else:
                # LIVE 모드: API 쓰로틀링 (최대 10회/초)
                now = time.monotonic()
                if now - self._last_tick_api_time < self._tick_api_min_interval:
                    return
                self._last_tick_api_time = now

                # 바이낸스 포지션 확인
                try:
                    pos_info = await self.binance.get_position_info()
                except Exception:
                    return  # API 실패 시 다음 tick에서 재시도

                if pos_info is None:
                    # 포지션 없음 = 이미 청산됨
                    await self.on_sl_filled(sl_price)
                elif self.position.sl_order_id:
                    # 주문 상태 확인 시도
                    order_status = await self.binance.get_order_status(self.position.sl_order_id)
                    if order_status and order_status.get('status') == 'FILLED':
                        await self.on_sl_filled(sl_price)

    # =========================================================================
    # 15분봉 처리
    # =========================================================================

    async def on_candle_close(self, kline: Dict):
        """
        15분봉 마감 시 처리

        Args:
            kline: 웹소켓 kline 데이터
        """
        # 캔들 데이터 업데이트
        is_closed = self.candle_manager.update_from_kline(kline)

        if not is_closed:
            return

        # 로그
        candle_time = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)
        self.logger.info(
            f"15m | {candle_time.strftime('%H:%M')} | "
            f"O:{float(kline['o']):.1f} H:{float(kline['h']):.1f} "
            f"L:{float(kline['l']):.1f} C:{float(kline['c']):.1f}"
        )

        # 지표 로그 및 CSV 저장
        indicators = self.candle_manager.get_latest_indicators()
        if indicators and not pd.isna(indicators['adx']):
            self.logger.info(
                f"지표: ADX={indicators['adx']:.1f}, ATR={indicators['atr']:.1f}, "
                f"Bull={indicators['bull_trend']}, Bear={indicators['bear_trend']}"
            )
            # 지표 CSV 저장
            self._record_indicators(candle_time, indicators)

        # 포지션 없으면 진입 신호 체크
        if not self.position.has_position():
            signal = await self.check_entry_signal()

            if signal:
                mode_prefix = "[DRY]" if self.is_dry_run() else "[LIVE]"
                self.logger.info(f"{mode_prefix} {signal} 신호 감지!")
                await self.execute_entry(signal)

    # =========================================================================
    # 거래 기록
    # =========================================================================

    def _record_trade(
        self,
        trade_type: str,
        price: float,
        quantity: float,
        pnl: float
    ):
        """거래 기록 CSV 저장"""
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
                    datetime.now(pytz.UTC).isoformat(),
                    mode,
                    trade_type,
                    self.position.direction or 'N/A',
                    price,
                    quantity,
                    self.position.take_profit if trade_type == 'ENTRY' else '',
                    self.position.stop_loss if trade_type == 'ENTRY' else '',
                    self.position.leverage if trade_type == 'ENTRY' else '',
                    pnl,
                    self.capital
                ])

            self.logger.info(f"거래 기록 저장: {trade_type} @ ${price:.2f}")

        except Exception as e:
            self.logger.error(f"거래 기록 저장 실패: {e}")

    def _record_indicators(self, candle_time: datetime, indicators: Dict[str, Any]):
        """
        지표 값 CSV 저장 (15분마다)

        첫 봉이면 마지막 줄 교체, 이후에는 append

        Args:
            candle_time: 캔들 시간
            indicators: 지표 딕셔너리
        """
        try:
            # 신호 체크
            adx_threshold = self._get_param('ADX_THRESHOLD', 30.0)
            long_signal = self.candle_manager.check_long_signal(adx_threshold)
            short_signal = self.candle_manager.check_short_signal(adx_threshold)

            # 현재 포지션 상태
            position_status = self.position.direction if self.position.has_position() else 'NONE'

            new_row = [
                candle_time.isoformat(),
                indicators.get('open', 0),
                indicators.get('high', 0),
                indicators.get('low', 0),
                indicators.get('close', 0),
                indicators.get('ema_fast', 0),
                indicators.get('ema_mid', 0),
                indicators.get('ema_slow', 0),
                indicators.get('adx', 0),
                indicators.get('atr', 0),
                indicators.get('bull_trend', False),
                indicators.get('bear_trend', False),
                indicators.get('had_low_below_fast', False),
                indicators.get('had_high_above_fast', False),
                indicators.get('reclaim_long', False),
                indicators.get('reclaim_short', False),
                long_signal,
                short_signal,
                position_status,
                self.capital
            ]

            # 항상 append (초기 로드 시 이미 미완성 봉 제외됨)
            with open(self.indicators_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(new_row)

        except Exception as e:
            self.logger.error(f"지표 기록 저장 실패: {e}")

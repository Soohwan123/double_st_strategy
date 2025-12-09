#!/usr/bin/env python3
"""
Grid Martingale Strategy
그리드 마틴게일 라이브 트레이딩 전략 클래스

backtest_grid_martingale_3_2_not_even.py 기반
실시간 주문 관리 및 체결 감지 로직 포함
"""

import asyncio
import logging
import csv
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
import pytz

from config import DynamicConfig, Config, DEFAULT_PARAMS
from state_manager import StateManager, PositionState, OrderState
from binance_library import BinanceFuturesClient


class GridMartingaleStrategy:
    """
    그리드 마틴게일 전략 클래스

    주요 기능:
    1. 거미줄 지정가 진입 주문
    2. 체결 감지 및 청산 주문 관리
    3. 본절(BE)/익절(TP) 로직
    4. 손절(SL) 로직
    5. 상태 스냅샷 저장/복구
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
            symbol_type: 'btc' 또는 'eth'
            logger: 로거
        """
        self.binance = binance
        self.symbol_type = symbol_type
        self.logger = logger

        # 동적 설정 로더
        self.dynamic_config = DynamicConfig(symbol_type)

        # 상태 관리
        self.state_manager = StateManager(
            Config.get_state_path(symbol_type),
            logger
        )
        self.position = PositionState()
        self.orders = OrderState()

        # 그리드 상태
        self.grid_center: Optional[float] = None
        self.capital: float = 0.0
        self.initialized: bool = False

        # 거래 기록 파일
        self.trades_path = Config.get_trades_path(symbol_type)
        os.makedirs(os.path.dirname(self.trades_path), exist_ok=True)

    # =========================================================================
    # 설정값 접근
    # =========================================================================

    def _reload_config(self):
        """동적 설정 다시 로드"""
        self.dynamic_config.reload()

    def _get_param(self, key: str, default=None):
        """파라미터 값 가져오기"""
        return self.dynamic_config.get(key, DEFAULT_PARAMS.get(key, default))

    def _get_param_list(self, key: str):
        """리스트 파라미터 값 가져오기"""
        return self.dynamic_config.get_list(key, DEFAULT_PARAMS.get(key, []))

    # =========================================================================
    # 자본 관리 (로컬 추적)
    # =========================================================================

    async def init_capital(self):
        """
        초기 자본 설정
        - state 파일에 capital이 있으면 그 값 사용 (복구)
        - 없으면 바이낸스 잔고의 40%를 초기 자본으로 설정
        """
        # state에서 capital 복구 시도
        state = self.state_manager.load_state()
        if state and 'capital' in state and state['capital'] > 0:
            self.capital = state['capital']
            self.logger.info(f"저장된 자본 복구: ${self.capital:.2f}")
            return

        # 새로 시작: 바이낸스 잔고의 40% 사용
        try:
            balance = await self.binance.get_account_balance('USDC')
            wallet_balance = balance['wallet_balance']

            # 총 잔고의 40%를 이 심볼의 운용 자본으로
            self.capital = wallet_balance * 0.4

            self.logger.info(f"초기 자본 설정: 총 잔고 ${wallet_balance:.2f} × 40% = ${self.capital:.2f}")

        except Exception as e:
            self.logger.error(f"잔고 조회 실패: {e}")
            # 실패 시 설정값의 40% 사용
            self.capital = self._get_param('INITIAL_CAPITAL', 1000.0) * 0.4
            self.logger.warning(f"기본값 사용: ${self.capital:.2f}")

    async def update_capital_from_pnl(self):
        """
        청산 후 바이낸스 API에서 realizedPnl 조회하여 capital 업데이트
        """
        try:
            pnl_data = await self.binance.get_last_closed_trade_pnl()
            net_pnl = pnl_data['net_pnl']

            old_capital = self.capital
            self.capital += net_pnl

            self.logger.info(
                f"자본 업데이트: ${old_capital:.2f} + ${net_pnl:.4f} = ${self.capital:.2f}"
            )

            # 상태 저장
            self._save_state()

        except Exception as e:
            self.logger.error(f"PnL 기반 자본 업데이트 실패: {e}")

    async def _sync_position_from_binance(self, max_retries: int = 10, retry_delay: float = 1.0):
        """
        바이낸스 API에서 실제 포지션 정보를 가져와 평단가/수량 동기화
        성공할 때까지 재시도

        Args:
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격(초)

        Returns:
            성공 여부
        """
        for attempt in range(max_retries):
            try:
                pos_info = await self.binance.get_position_info()

                if pos_info:
                    old_avg = self.position.avg_price
                    old_size = self.position.total_size

                    # 바이낸스 실제 값으로 덮어쓰기
                    self.position.avg_price = pos_info['entry_price']
                    self.position.total_size = pos_info['size']

                    self.logger.info(
                        f"포지션 동기화 성공: 평단가 ${old_avg:.2f} → ${pos_info['entry_price']:.2f}, "
                        f"수량 {old_size:.6f} → {pos_info['size']:.6f}"
                    )
                    return True
                else:
                    # 포지션이 없는 경우 (청산 완료)
                    self.logger.info("포지션 동기화: 바이낸스에 포지션 없음 (청산 완료)")
                    return True

            except Exception as e:
                self.logger.warning(f"포지션 동기화 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)

        self.logger.error(f"포지션 동기화 실패: {max_retries}회 시도 후 포기")
        return False

    # =========================================================================
    # 가격 계산
    # =========================================================================

    def get_level_price(self, level: int, direction: str) -> float:
        """
        레벨별 가격 계산 (불균등 간격)

        Args:
            level: 레벨 (0~3: 진입, 4: 손절)
            direction: 'LONG' 또는 'SHORT'

        Returns:
            해당 레벨의 가격
        """
        level_distances = self._get_param_list('LEVEL_DISTANCES')
        sl_distance = self._get_param('SL_DISTANCE', 0.05)
        max_level = self._get_param('MAX_ENTRY_LEVEL', 4)

        if level < max_level:
            distance = level_distances[level]
        else:
            distance = sl_distance

        if direction == 'LONG':
            return self.grid_center * (1 - distance)
        else:  # SHORT
            return self.grid_center * (1 + distance)

    def calculate_tp_price(self, avg_price: float, direction: str) -> float:
        """익절가 계산 (평단가 +0.5%)"""
        tp_pct = self._get_param('TP_PCT', 0.005)

        if direction == 'LONG':
            return avg_price * (1 + tp_pct)
        else:
            return avg_price * (1 - tp_pct)

    def calculate_be_price(self, avg_price: float, direction: str) -> float:
        """본절가 계산 (평단가 +0.1%)"""
        be_pct = self._get_param('BE_PCT', 0.001)

        if direction == 'LONG':
            return avg_price * (1 + be_pct)
        else:
            return avg_price * (1 - be_pct)

    def calculate_sl_price(self) -> float:
        """손절가 계산 (grid_center 기준 5%)"""
        direction = self.position.direction or 'LONG'
        return self.get_level_price(4, direction)  # Level 5 = SL

    def calculate_new_grid_center(self, level1_price: float, direction: str) -> float:
        """
        그리드 센터 역산
        BE 청산 후 새 Level 1 가격에서 grid_center 계산
        """
        level_distances = self._get_param_list('LEVEL_DISTANCES')

        if direction == 'LONG':
            return level1_price / (1 - level_distances[0])
        else:
            return level1_price / (1 + level_distances[0])

    # =========================================================================
    # 초기화 및 상태 복구
    # =========================================================================

    async def initialize(self):
        """
        전략 초기화
        - 상태 복구 또는 새로 시작
        - 자본 초기화 (로컬 추적 방식)
        """
        self.logger.info("=" * 60)
        self.logger.info("Grid Martingale Strategy 초기화")
        self.logger.info("=" * 60)

        # 자본 초기화 (state에서 복구 또는 바이낸스 잔고의 절반)
        await self.init_capital()
        self.logger.info(f"운용 자본: ${self.capital:.2f}")

        # 상태 복구 시도 (capital 제외한 나머지)
        state = self.state_manager.load_state()
        if state:
            await self._restore_state(state)
        else:
            self.logger.info("새로운 거래 세션 시작")

        self.initialized = True

    async def _restore_state(self, state: Dict[str, Any]):
        """상태 복구"""
        self.logger.info("이전 상태 복구 중...")

        # 그리드 센터
        self.grid_center = state.get('grid_center')
        self.logger.info(f"Grid Center: ${self.grid_center:.2f}" if self.grid_center else "Grid Center: None")

        # 포지션 복구
        if 'position' in state and state['position']:
            self.position.from_dict(state['position'])
            self.logger.info(f"포지션: {self.position.direction}, Level {self.position.current_level}")
            self.logger.info(f"평단가: ${self.position.avg_price:.2f}, 수량: {self.position.total_size:.6f}")

        # 주문 복구
        if 'orders' in state and state['orders']:
            self.orders.from_dict(state['orders'])
            self.logger.info(f"대기 진입 주문: {len(self.orders.pending_entry_orders)}개")

        # 바이낸스 실제 상태와 동기화
        await self._sync_with_binance()

    async def _sync_with_binance(self):
        """바이낸스 실제 상태와 동기화"""
        # 실제 포지션 확인
        pos_info = await self.binance.get_position_info()
        if pos_info:
            self.logger.info(f"바이낸스 포지션 확인: {pos_info['side']}, 평단가 ${pos_info['entry_price']:.2f}, 수량 {pos_info['size']:.6f}")

            # 포지션이 있으면 무조건 바이낸스 값으로 동기화
            if self.position.has_position():
                old_avg = self.position.avg_price
                old_size = self.position.total_size

                self.position.avg_price = pos_info['entry_price']
                self.position.total_size = pos_info['size']

                self.logger.info(
                    f"포지션 동기화: 평단가 ${old_avg:.2f} → ${pos_info['entry_price']:.2f}, "
                    f"수량 {old_size:.6f} → {pos_info['size']:.6f}"
                )
        else:
            # 바이낸스에 포지션이 없는데 로컬에 있으면 초기화
            if self.position.has_position():
                self.logger.warning("바이낸스에 포지션 없음 - 로컬 포지션 초기화")
                self.position.reset()

        # 대기 주문 확인 및 동기화
        open_orders = await self.binance.get_open_orders()
        self.logger.info(f"바이낸스 대기 주문: {len(open_orders)}개")

        # 주문 동기화: 바이낸스 실제 주문과 로컬 상태 매칭
        await self._sync_orders_with_binance(open_orders)

        # 동기화 후 상태 저장
        self._save_state()

    async def _sync_orders_with_binance(self, open_orders: List[Dict]):
        """
        바이낸스 실제 주문과 로컬 상태 동기화

        로컬에 저장된 주문 ID가 바이낸스에 없으면 제거하고,
        필요한 주문이 없으면 새로 설정
        """
        # 바이낸스에 있는 주문 ID 집합
        binance_order_ids = {str(o.get('orderId', '')) for o in open_orders}

        self.logger.info(f"주문 동기화 시작: 바이낸스 주문 {len(open_orders)}개")

        # 1. 진입 주문 동기화
        valid_entry_orders = []
        for order in self.orders.pending_entry_orders:
            if order['order_id'] in binance_order_ids:
                valid_entry_orders.append(order)
            else:
                self.logger.warning(f"진입 주문 {order['order_id']} (Level {order['level']+1})가 바이낸스에 없음 - 제거")
        self.orders.pending_entry_orders = valid_entry_orders

        # 2. TP 주문 동기화
        if self.orders.tp_order:
            if self.orders.tp_order['order_id'] not in binance_order_ids:
                self.logger.warning(f"TP 주문 {self.orders.tp_order['order_id']}가 바이낸스에 없음 - 제거")
                self.orders.tp_order = None

        # 3. BE 주문 동기화
        if self.orders.be_order:
            if self.orders.be_order['order_id'] not in binance_order_ids:
                self.logger.warning(f"BE 주문 {self.orders.be_order['order_id']}가 바이낸스에 없음 - 제거")
                self.orders.be_order = None

        # 4. SL 주문 동기화
        if self.orders.sl_order:
            if self.orders.sl_order['order_id'] not in binance_order_ids:
                self.logger.warning(f"SL 주문 {self.orders.sl_order['order_id']}가 바이낸스에 없음 - 제거")
                self.orders.sl_order = None

        # 5. 포지션이 있는데 청산 주문이 없으면 새로 설정
        if self.position.has_position():
            if self.position.current_level == 1 and not self.orders.tp_order:
                self.logger.info("TP 주문 누락 - 새로 설정")
                await self._set_tp_order()
            elif self.position.current_level >= 2 and not self.orders.be_order:
                self.logger.info("BE 주문 누락 - 새로 설정")
                await self._set_be_order()
            if self.position.current_level >= 4 and not self.orders.sl_order:
                self.logger.info("SL 주문 누락 - 새로 설정")
                await self._set_sl_order()

        # 6. 포지션이 없고 진입 주문도 없으면 그리드 재설정
        if not self.position.has_position() and len(self.orders.pending_entry_orders) == 0:
            if self.grid_center:
                self.logger.info("포지션/진입주문 없음 - 그리드 재설정")
                await self.setup_grid_orders(self.grid_center)

    # =========================================================================
    # 상태 저장
    # =========================================================================

    def _save_state(self):
        """현재 상태 저장"""
        state = {
            'grid_center': self.grid_center,
            'capital': self.capital,
            'position': self.position.to_dict() if self.position.has_position() else None,
            'orders': self.orders.to_dict()
        }
        self.state_manager.save_state(state)

    # =========================================================================
    # 거미줄 주문 설정
    # =========================================================================

    async def setup_grid_orders(self, center_price: float):
        """
        거미줄 지정가 진입 주문 설정
        grid_center 기준으로 4단계 지정가 주문
        """
        self._reload_config()

        self.grid_center = center_price
        direction = self._get_param('TRADE_DIRECTION', 'LONG')
        max_level = self._get_param('MAX_ENTRY_LEVEL', 4)
        entry_ratios = self._get_param_list('ENTRY_RATIOS')
        leverage = self._get_param('LEVERAGE_LONG', 20) if direction == 'LONG' else self._get_param('LEVERAGE_SHORT', 5)

        self.logger.info(f"거미줄 주문 설정: center=${center_price:.2f}, direction={direction}")

        # 기존 주문 취소 (완료 확인까지 반복)
        await self._cancel_all_orders_with_verify()
        self.orders.clear_all()

        # 각 레벨별 지정가 주문
        for level in range(max_level):
            level_price = self.get_level_price(level, direction)
            ratio = entry_ratios[level]
            entry_value = self.capital * ratio * leverage
            quantity = entry_value / level_price

            # 마지막 레벨(50%)은 증거금 부족 가능성 → 재시도 로직 사용
            if level == max_level - 1:
                order = await self.binance.place_limit_entry_with_retry(
                    direction=direction,
                    price=level_price,
                    base_value=entry_value,
                    leverage=leverage,
                    retry_decrement_pct=0.001,  # 0.1%씩 줄이며 재시도
                    min_ratio=0.30
                )
            else:
                order = await self.binance.place_limit_entry(
                    direction=direction,
                    price=level_price,
                    quantity=quantity,
                    leverage=leverage
                )

            if order:
                self.orders.add_entry_order(
                    order_id=str(order.get('orderId', '')),
                    level=level,
                    price=level_price,
                    quantity=quantity
                )
                self.logger.info(f"Level {level+1} 주문: ${level_price:.2f}, {quantity:.6f}")

        # 상태 저장
        self._save_state()

    async def reset_grid_after_full_close(self, new_center: float):
        """전량 청산(TP/SL) 후 그리드 재설정"""
        self.logger.info(f"그리드 재설정: new_center=${new_center:.2f}")

        # 포지션 초기화
        self.position.reset()
        self.orders.clear_all()

        # 모든 대기 주문 취소 (완료될 때까지 반복)
        await self._cancel_all_orders_with_verify()

        # 새 거미줄 주문
        await self.setup_grid_orders(new_center)

    async def _cancel_all_orders_with_verify(self, max_attempts: int = 5):
        """
        모든 대기 주문 취소 (완료 확인까지 반복)
        """
        for attempt in range(max_attempts):
            # 주문 취소
            await self.binance.cancel_all_orders()

            # 잠시 대기 후 확인
            await asyncio.sleep(0.5)

            # 대기 주문 조회
            try:
                open_orders = await self.binance.get_open_orders()
                if not open_orders or len(open_orders) == 0:
                    self.logger.info(f"모든 주문 취소 완료 (시도 {attempt + 1}회)")
                    return
                else:
                    self.logger.warning(f"아직 대기 주문 {len(open_orders)}개 남음, 재시도 중... (시도 {attempt + 1}/{max_attempts})")
            except Exception as e:
                self.logger.warning(f"주문 조회 실패: {e}")

        self.logger.error(f"주문 취소 실패: {max_attempts}회 시도 후에도 주문 남아있음")

    async def reset_grid_after_partial_close(self):
        """
        BE 청산 후 그리드 재설정
        Level 1 물량만 남긴 상태에서 Level 2~4 재설정
        """
        direction = self.position.direction

        # 1. 기존 주문 전부 취소 (완료 확인까지 반복)
        await self._cancel_all_orders_with_verify()
        self.orders.clear_all()

        # 2. 바이낸스 실제 포지션 동기화 (BE 체결 후 실제 남은 물량 확인)
        await self._sync_position_from_binance()

        # 2.1. BE 후 남은 물량 = 새로운 Level 1 물량으로 업데이트
        self.position.level1_btc_amount = self.position.total_size
        self.logger.info(f"Level 1 물량 업데이트: {self.position.level1_btc_amount:.6f}")

        # 4. 현재 상태 로깅
        self.logger.info(f"BE 후 포지션 상태: Level {self.position.current_level}, "
                        f"평단가 ${self.position.avg_price:.2f}, 수량 {self.position.total_size:.6f}")

        # 5. 그리드 재설정
        new_level1_price = self.position.avg_price  # 현재 평단가 = 새 Level 1 가격
        self.grid_center = self.calculate_new_grid_center(new_level1_price, direction)
        self.logger.info(f"BE 후 그리드 재설정: new_center=${self.grid_center:.2f}")

        # 6. Level 2~4 지정가 주문 재설정 (Level 1은 이미 체결된 상태)
        max_level = self._get_param('MAX_ENTRY_LEVEL', 4)
        entry_ratios = self._get_param_list('ENTRY_RATIOS')
        leverage = self._get_param('LEVERAGE_LONG', 20) if direction == 'LONG' else self._get_param('LEVERAGE_SHORT', 5)

        for level in range(1, max_level):  # Level 1~3 (인덱스 기준)
            level_price = self.get_level_price(level, direction)
            ratio = entry_ratios[level]
            entry_value = self.capital * ratio * leverage

            if level == max_level - 1:
                order = await self.binance.place_limit_entry_with_retry(
                    direction=direction,
                    price=level_price,
                    base_value=entry_value,
                    leverage=leverage
                )
            else:
                order = await self.binance.place_limit_entry(
                    direction=direction,
                    price=level_price,
                    quantity=entry_value / level_price,
                    leverage=leverage
                )

            if order:
                self.orders.add_entry_order(
                    order_id=str(order.get('orderId', '')),
                    level=level,
                    price=level_price,
                    quantity=entry_value / level_price
                )
                self.logger.info(f"Level {level+1} 주문 재설정: ${level_price:.2f}")

        # 7. TP 주문 설정 (Level 1만 있으므로)
        await self._set_tp_order()

        # 8. 상태 저장
        self._save_state()

    # =========================================================================
    # 청산 주문 관리
    # =========================================================================

    async def _set_tp_order(self):
        """익절(TP) 주문 설정 - Level 1만 체결된 상태, 바이낸스 실제 포지션 기준"""
        if not self.position.has_position():
            return

        # 1. 바이낸스 실제 포지션 조회 (실패 시 재시도)
        pos_info = await self.binance.get_position_info_with_retry()
        if not pos_info:
            self.logger.error("TP 주문 실패: 포지션 조회 불가")
            return

        actual_size = pos_info['size']
        tp_price = self.calculate_tp_price(pos_info['entry_price'], self.position.direction)

        self.logger.info(f"TP 주문 준비: 바이낸스 포지션 {actual_size:.6f}, 평단가 ${pos_info['entry_price']:.2f}")

        # 2. 전량 청산 주문 (실패 시 0.1%씩 줄이며 재시도)
        order = await self.binance.place_limit_close(
            direction=self.position.direction,
            price=tp_price,
            quantity=actual_size,
            retry_on_reduce_only=True
        )

        if order:
            self.orders.set_tp_order(
                order_id=str(order.get('orderId', '')),
                price=tp_price,
                quantity=actual_size
            )
            self.logger.info(f"TP 주문 설정: ${tp_price:.2f}, 수량: {actual_size:.6f}")

    async def _set_be_order(self):
        """본절(BE) 주문 설정 - Level 2+ 체결된 상태, 바이낸스 실제 포지션에서 Level 1 제외"""
        if not self.position.has_position():
            return

        # 1. 바이낸스 실제 포지션 조회 (실패 시 재시도)
        pos_info = await self.binance.get_position_info_with_retry()
        if not pos_info:
            self.logger.error("BE 주문 실패: 포지션 조회 불가")
            return

        actual_size = pos_info['size']
        be_price = self.calculate_be_price(pos_info['entry_price'], self.position.direction)

        # 2. 덜어낼 물량 = 바이낸스 실제 포지션 - Level 1 물량
        close_amount = actual_size - self.position.level1_btc_amount

        self.logger.info(f"BE 주문 준비: 바이낸스 포지션 {actual_size:.6f}, Level1 {self.position.level1_btc_amount:.6f}, 덜어내기 {close_amount:.6f}")

        if close_amount <= 0:
            self.logger.warning(f"BE 주문 스킵: 덜어낼 물량 없음")
            return

        # 3. 덜어내기 청산 주문 (실패 시 0.1%씩 줄이며 재시도)
        order = await self.binance.place_limit_close(
            direction=self.position.direction,
            price=be_price,
            quantity=close_amount,
            retry_on_reduce_only=True
        )

        if order:
            self.orders.set_be_order(
                order_id=str(order.get('orderId', '')),
                price=be_price,
                quantity=close_amount
            )
            self.logger.info(f"BE 주문 설정: ${be_price:.2f}, 덜어내기 수량: {close_amount:.6f} (Level1 {self.position.level1_btc_amount:.6f} 유지)")

    async def _set_sl_order(self):
        """손절(SL) 주문 설정 - Level 4 체결 후"""
        if not self.position.has_position():
            return

        sl_price = self.calculate_sl_price()

        order = await self.binance.set_stop_loss(
            direction=self.position.direction,
            stop_price=sl_price
        )

        if order:
            self.orders.set_sl_order(
                order_id=str(order.get('orderId', '')),
                price=sl_price
            )
            self.logger.info(f"SL 주문 설정: ${sl_price:.2f}")

    async def _update_close_orders(self):
        """
        레벨 변경에 따른 청산 주문 업데이트

        - Level 1: TP 주문
        - Level 2~3: BE 주문
        - Level 4: BE + SL 주문
        """
        # 기존 TP/BE 주문 취소
        if self.orders.tp_order:
            await self.binance.cancel_order(self.orders.tp_order['order_id'])
            self.orders.tp_order = None

        if self.orders.be_order:
            await self.binance.cancel_order(self.orders.be_order['order_id'])
            self.orders.be_order = None

        level = self.position.current_level

        if level == 1:
            # Level 1만: TP 주문
            await self._set_tp_order()
        elif level >= 2:
            # Level 2+: BE 주문
            await self._set_be_order()

            if level >= 4:
                # Level 4: SL도 설정
                await self._set_sl_order()

    # =========================================================================
    # 체결 처리
    # =========================================================================

    async def on_entry_filled(self, level: int, price: float, quantity: float):
        """
        진입 주문 체결 시 처리

        Args:
            level: 체결된 레벨 (0~3)
            price: 체결 가격
            quantity: 체결 수량
        """
        direction = self._get_param('TRADE_DIRECTION', 'LONG')

        # 첫 진입이면 포지션 방향 설정
        if not self.position.has_position():
            self.position.direction = direction
            self.logger.info(f"첫 진입: {direction}")

        # 진입 추가 (로컬 계산)
        self.position.add_entry(price, quantity, level)
        self.orders.remove_entry_order(level)

        # 바이낸스 API에서 실제 평단가/수량 동기화
        await self._sync_position_from_binance()

        self.logger.info(
            f"Level {level+1} 체결: ${price:.2f}, "
            f"평단가: ${self.position.avg_price:.2f}, "
            f"총 수량: {self.position.total_size:.6f}"
        )

        # 청산 주문 업데이트
        await self._update_close_orders()

        # 상태 저장
        self._save_state()

        # 거래 기록
        self._record_trade('ENTRY', level + 1, price, quantity, 0)

    async def on_tp_filled(self, price: float):
        """TP 체결 시 처리 (Level 1 전량 익절)"""
        self.logger.info(f"TP 체결 감지: ${price:.2f}")

        # 1. 바이낸스 포지션 동기화 (성공할 때까지 재시도)
        await self._sync_position_from_binance()

        # 2. PnL 계산 (동기화된 값 기준)
        pnl = self._calculate_pnl(price)
        self.logger.info(f"TP 체결: ${price:.2f}, 예상 PnL: ${pnl:.2f}")

        # 3. 거래 기록
        self._record_trade('TP', self.position.current_level, price, self.position.total_size, pnl)

        # 4. 바이낸스 API에서 실제 PnL 조회하여 자본 업데이트
        await self.update_capital_from_pnl()

        # 5. 그리드 재설정 (익절가가 새 center)
        await self.reset_grid_after_full_close(price)

    async def on_be_filled(self, price: float):
        """BE 체결 시 처리 (Level 2+ 덜어내기)"""
        self.logger.info(f"BE 체결 감지: ${price:.2f}")

        # 1. 바이낸스 포지션 동기화 (성공할 때까지 재시도)
        await self._sync_position_from_binance()

        # 2. 덜어낸 물량의 PnL 계산 (동기화된 값 기준)
        close_amount = self.position.total_size - self.position.level1_btc_amount
        if self.position.direction == 'LONG':
            pnl = (price - self.position.avg_price) * close_amount
        else:
            pnl = (self.position.avg_price - price) * close_amount

        self.logger.info(f"BE 체결: ${price:.2f}, 덜어내기 수량: {close_amount:.6f}, 예상 PnL: ${pnl:.2f}")

        # 3. 거래 기록
        self._record_trade('PARTIAL_BE', self.position.current_level, price, close_amount, pnl)

        # 4. 바이낸스 API에서 실제 PnL 조회하여 자본 업데이트
        await self.update_capital_from_pnl()

        # 5. Level 1 물량만 남기고 그리드 재설정
        self.position.total_size = self.position.level1_btc_amount
        self.position.entries = [{'price': self.position.avg_price, 'btc_amount': self.position.level1_btc_amount, 'level': 0}]
        self.position.current_level = 1
        self.position.level_prices = [self.position.avg_price, None, None, None]

        # 6. 새 그리드 설정
        await self.reset_grid_after_partial_close()

    async def on_sl_filled(self, price: float):
        """SL 체결 시 처리"""
        self.logger.info(f"SL 체결 감지: ${price:.2f}")

        # 1. 바이낸스 포지션 동기화 (성공할 때까지 재시도)
        await self._sync_position_from_binance()

        # 2. PnL 계산 (동기화된 값 기준)
        pnl = self._calculate_pnl(price)
        self.logger.info(f"SL 체결: ${price:.2f}, 예상 PnL: ${pnl:.2f}")

        # 3. 거래 기록
        self._record_trade('SL', self.position.current_level, price, self.position.total_size, pnl)

        # 4. 바이낸스 API에서 실제 PnL 조회하여 자본 업데이트
        await self.update_capital_from_pnl()

        # 5. 그리드 재설정 (손절가가 새 center)
        await self.reset_grid_after_full_close(price)

    def _calculate_pnl(self, exit_price: float) -> float:
        """PnL 계산"""
        if not self.position.has_position():
            return 0.0

        if self.position.direction == 'LONG':
            return (exit_price - self.position.avg_price) * self.position.total_size
        else:
            return (self.position.avg_price - exit_price) * self.position.total_size

    # =========================================================================
    # 틱데이터 처리
    # =========================================================================

    async def on_tick(self, price: float):
        """
        틱데이터 처리 - 체결 감지

        Args:
            price: 현재 가격
        """
        if not self.initialized:
            return

        direction = self._get_param('TRADE_DIRECTION', 'LONG')

        # 1. 진입 주문 체결 감지
        for order in list(self.orders.pending_entry_orders):
            level = order['level']
            order_price = order['price']

            filled = False
            if direction == 'LONG' and price < order_price:
                filled = True
            elif direction == 'SHORT' and price > order_price:
                filled = True

            if filled:
                await self.on_entry_filled(level, order_price, order['quantity'])

        # 2. TP 체결 감지
        if self.orders.tp_order:
            tp_price = self.orders.tp_order['price']
            if direction == 'LONG' and price > tp_price:
                await self.on_tp_filled(tp_price)
            elif direction == 'SHORT' and price < tp_price:
                await self.on_tp_filled(tp_price)

        # 3. BE 체결 감지
        if self.orders.be_order:
            be_price = self.orders.be_order['price']
            if direction == 'LONG' and price > be_price:
                await self.on_be_filled(be_price)
            elif direction == 'SHORT' and price < be_price:
                await self.on_be_filled(be_price)

        # 4. SL 체결 감지
        if self.orders.sl_order:
            sl_price = self.orders.sl_order['price']
            if direction == 'LONG' and price < sl_price:
                await self.on_sl_filled(sl_price)
            elif direction == 'SHORT' and price > sl_price:
                await self.on_sl_filled(sl_price)

        # 5. 그리드 범위 이탈 체크 (포지션 없을 때만)
        await self._check_grid_range(price)

    # =========================================================================
    # 그리드 범위 체크
    # =========================================================================

    async def _check_grid_range(self, current_price: float):
        """
        포지션 없을 때 그리드 범위 이탈 체크

        백테스트와 동일하게:
        - LONG 전략: 가격이 위로 범위 이탈 시 그리드 재설정
        - SHORT 전략: 가격이 아래로 범위 이탈 시 그리드 재설정
        - BOTH: 양방향 진입 가능하므로 재설정 안 함
        """
        # 포지션 있으면 체크 안 함
        if self.position.has_position():
            return

        # 그리드 센터 없으면 체크 안 함
        if self.grid_center is None:
            return

        direction = self._get_param('TRADE_DIRECTION', 'LONG')
        grid_range_pct = self._get_param('GRID_RANGE_PCT', 0.04)
        half_range = grid_range_pct / 2

        upper_bound = self.grid_center * (1 + half_range)
        lower_bound = self.grid_center * (1 - half_range)

        need_reset = False

        if direction == 'LONG' and current_price > upper_bound:
            # LONG 전략: 가격이 위로 벗어남 → 진입 기회 놓침, 재설정
            need_reset = True
            self.logger.info(
                f"그리드 범위 상향 이탈: ${current_price:.2f} > ${upper_bound:.2f} "
                f"(center=${self.grid_center:.2f}, range=±{half_range*100:.1f}%)"
            )
        elif direction == 'SHORT' and current_price < lower_bound:
            # SHORT 전략: 가격이 아래로 벗어남 → 진입 기회 놓침, 재설정
            need_reset = True
            self.logger.info(
                f"그리드 범위 하향 이탈: ${current_price:.2f} < ${lower_bound:.2f} "
                f"(center=${self.grid_center:.2f}, range=±{half_range*100:.1f}%)"
            )
        # BOTH일 때는 재설정 안 함 (양방향 진입 가능)

        if need_reset:
            # 기존 주문 취소하고 새 그리드 설정
            await self.binance.cancel_all_orders()
            self.orders.clear_all()
            await self.setup_grid_orders(current_price)

    # =========================================================================
    # 거래 기록
    # =========================================================================

    def _record_trade(
        self,
        trade_type: str,
        level: int,
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
                        'timestamp', 'type', 'direction', 'level', 'price',
                        'quantity', 'avg_price', 'pnl', 'grid_center', 'capital'
                    ])

                writer.writerow([
                    datetime.now(pytz.UTC).isoformat(),
                    trade_type,
                    self.position.direction or self._get_param('TRADE_DIRECTION', 'LONG'),
                    level,
                    price,
                    quantity,
                    self.position.avg_price,
                    pnl,
                    self.grid_center,
                    self.capital
                ])

        except Exception as e:
            self.logger.error(f"거래 기록 저장 실패: {e}")

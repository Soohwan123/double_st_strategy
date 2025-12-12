#!/usr/bin/env python3
"""
Binance Futures API Library (Extended for Grid Martingale)
바이낸스 선물 거래 API 래퍼 클래스

지정가 진입 주문, 증거금 부족 재시도 등 그리드 마틴게일 전략에 필요한 기능 추가
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any, Callable
import logging
import pytz

from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *


class BinanceFuturesClient:
    """
    바이낸스 선물 거래 API 클라이언트 (Grid Martingale 확장)

    Usage:
        client = Client(api_key, api_secret)
        binance = BinanceFuturesClient(client, symbol='BTCUSDC', logger=my_logger)

        # 지정가 진입 주문 (거미줄)
        order = await binance.place_limit_entry(
            direction='LONG',
            price=94000.0,
            quantity=0.01
        )

        # 지정가 청산 (익절/본절)
        order = await binance.place_limit_close(
            direction='LONG',
            price=95000.0,
            quantity=0.01
        )

        # 증거금 부족 시 수량 줄여가며 재시도
        order = await binance.place_limit_entry_with_retry(
            direction='LONG',
            price=94000.0,
            base_quantity=0.05,
            retry_decrement_pct=0.01
        )
    """

    def __init__(
        self,
        client: Client,
        symbol: str,
        logger: Optional[logging.Logger] = None,
        dry_run: bool = False,
        price_precision: int = 1,
        qty_precision: int = 3
    ):
        """
        Args:
            client: python-binance Client 인스턴스
            symbol: 거래 심볼 (예: 'BTCUSDC')
            logger: 로깅용 로거 (None이면 기본 로거 사용)
            dry_run: True면 실제 주문 없이 로그만 출력
            price_precision: 가격 소수점 자릿수
            qty_precision: 수량 소수점 자릿수
        """
        self.client = client
        self.symbol = symbol
        self.logger = logger or logging.getLogger(__name__)
        self.dry_run = dry_run
        self.price_precision = price_precision
        self.qty_precision = qty_precision

    def _round_price(self, price: float) -> float:
        """가격 반올림"""
        return round(price, self.price_precision)

    def _round_qty(self, qty: float) -> float:
        """수량 반올림"""
        return round(qty, self.qty_precision)

    # =========================================================================
    # 계좌 관련
    # =========================================================================

    async def get_account_balance(self, asset: str = 'USDC') -> Dict[str, float]:
        """
        계좌 잔고 조회

        Args:
            asset: 조회할 자산 (예: 'USDC', 'USDT')

        Returns:
            {'wallet_balance': float, 'available_balance': float}
        """
        try:
            account = self.client.futures_account()

            for a in account['assets']:
                if a['asset'] == asset:
                    return {
                        'wallet_balance': float(a['walletBalance']),
                        'available_balance': float(a['availableBalance'])
                    }

            return {'wallet_balance': 0.0, 'available_balance': 0.0}

        except BinanceAPIException as e:
            self.logger.error(f"계좌 정보 조회 실패: {e}")
            raise

    async def get_position_info(self) -> Optional[Dict[str, Any]]:
        """
        현재 포지션 정보 조회

        Returns:
            포지션 정보 딕셔너리 또는 None (포지션 없음)
            {
                'side': 'LONG' or 'SHORT',
                'size': float,
                'entry_price': float,
                'unrealized_pnl': float
            }
        """
        try:
            positions = self.client.futures_position_information(symbol=self.symbol)

            for pos in positions:
                position_amt = float(pos['positionAmt'])
                if position_amt != 0:
                    return {
                        'side': 'LONG' if position_amt > 0 else 'SHORT',
                        'size': abs(position_amt),
                        'entry_price': float(pos['entryPrice']),
                        'unrealized_pnl': float(pos['unRealizedProfit'])
                    }

            return None

        except BinanceAPIException as e:
            self.logger.error(f"포지션 정보 조회 실패: {e}")
            raise

    async def get_position_info_with_retry(self, max_retries: int = 10, delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        포지션 정보 조회 (실패 시 재시도)

        Args:
            max_retries: 최대 재시도 횟수
            delay: 재시도 간 대기 시간 (초)

        Returns:
            포지션 정보 또는 None
        """
        for attempt in range(max_retries):
            try:
                return await self.get_position_info()
            except Exception as e:
                self.logger.warning(f"포지션 조회 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    self.logger.error(f"포지션 조회 최대 재시도 초과")
                    return None

    # =========================================================================
    # 레버리지/마진 설정
    # =========================================================================

    async def set_leverage(self, leverage: int) -> bool:
        """
        레버리지 설정

        Args:
            leverage: 레버리지 배수 (1-125)

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.info(f"[DRY RUN] Leverage: {leverage}x")
            return True

        try:
            self.client.futures_change_leverage(
                symbol=self.symbol,
                leverage=leverage
            )
            self.logger.info(f"Leverage 설정: {leverage}x")
            return True

        except BinanceAPIException as e:
            self.logger.error(f"레버리지 설정 실패: {e}")
            return False

    async def set_margin_type(self, margin_type: str = 'ISOLATED') -> bool:
        """
        마진 타입 설정

        Args:
            margin_type: 'ISOLATED' 또는 'CROSSED'

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.info(f"[DRY RUN] Margin mode: {margin_type}")
            return True

        try:
            self.client.futures_change_margin_type(
                symbol=self.symbol,
                marginType=margin_type
            )
            self.logger.info(f"Margin mode 설정: {margin_type}")
            return True

        except BinanceAPIException as e:
            if 'No need to change margin type' in str(e):
                return True
            self.logger.warning(f"Margin type 설정: {e}")
            return False

    # =========================================================================
    # 지정가 진입 주문 (NEW)
    # =========================================================================

    async def place_limit_entry(
        self,
        direction: str,
        price: float,
        quantity: float,
        leverage: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        지정가 진입 주문

        Args:
            direction: 'LONG' 또는 'SHORT'
            price: 진입 가격
            quantity: 주문 수량
            leverage: 레버리지

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_BUY if direction == 'LONG' else SIDE_SELL
        price = self._round_price(price)
        quantity = self._round_qty(quantity)

        if quantity < 0.001:
            self.logger.warning(f"주문 취소: 수량 너무 작음 ({quantity})")
            return None

        # 마진/레버리지 설정
        await self.set_margin_type('ISOLATED')
        await self.set_leverage(leverage)

        if self.dry_run:
            order_id = f"DRYRUN_ENTRY_{int(datetime.now(pytz.UTC).timestamp() * 1000)}"
            self.logger.info(f"[DRY RUN] LIMIT Entry: {direction} {quantity} @ ${price}")
            return {'orderId': order_id, 'status': 'DRY_RUN', 'price': price, 'quantity': quantity}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type='LIMIT',
                price=price,
                quantity=quantity,
                timeInForce='GTC'
            )
            self.logger.info(f"LIMIT Entry 주문: {direction} {quantity} @ ${price}, ID: {order['orderId']}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"지정가 진입 주문 실패: {e}")
            return None

    async def place_limit_entry_with_retry(
        self,
        direction: str,
        price: float,
        base_value: float,
        leverage: int,
        retry_decrement_pct: float = 0.001,
        min_ratio: float = 0.30
    ) -> Optional[Dict[str, Any]]:
        """
        증거금 부족 시 수량 줄여가며 재시도하는 지정가 진입

        Args:
            direction: 'LONG' 또는 'SHORT'
            price: 진입 가격
            base_value: 기본 진입 금액 (USDT)
            leverage: 레버리지
            retry_decrement_pct: 재시도 시 줄이는 비율 (0.1%)
            min_ratio: 최소 비율 (30% 이하로는 안 줄임)

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_BUY if direction == 'LONG' else SIDE_SELL
        price = self._round_price(price)

        current_value = base_value
        original_value = base_value
        min_value = original_value * min_ratio

        # 마진/레버리지 설정 (한 번만)
        await self.set_margin_type('ISOLATED')
        await self.set_leverage(leverage)

        if self.dry_run:
            quantity = self._round_qty(current_value / price)
            order_id = f"DRYRUN_ENTRY_{int(datetime.now(pytz.UTC).timestamp() * 1000)}"
            self.logger.info(f"[DRY RUN] LIMIT Entry with retry: {direction} {quantity} @ ${price}")
            return {'orderId': order_id, 'status': 'DRY_RUN', 'price': price, 'quantity': quantity}

        attempt = 0
        while current_value >= min_value:
            quantity = self._round_qty(current_value / price)
            attempt += 1

            if quantity < 0.001:
                self.logger.warning(f"주문 취소: 수량 너무 작음 ({quantity})")
                return None

            try:
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=side,
                    type='LIMIT',
                    price=price,
                    quantity=quantity,
                    timeInForce='GTC'
                )

                if current_value < original_value:
                    used_pct = (current_value / original_value) * 100
                    self.logger.warning(
                        f"증거금 부족으로 {used_pct:.1f}%로 주문 성공 "
                        f"(시도 {attempt}회, {original_value:.2f} -> {current_value:.2f} USDT)"
                    )
                self.logger.info(f"LIMIT Entry 주문: {direction} {quantity} @ ${price}, ID: {order['orderId']}")
                return order

            except BinanceAPIException as e:
                error_msg = str(e)
                if 'Margin is insufficient' in error_msg or 'insufficient' in error_msg.lower():
                    # 증거금 부족 - 1%씩 줄여서 재시도
                    current_value -= original_value * retry_decrement_pct
                    self.logger.warning(
                        f"증거금 부족 (시도 {attempt}), 재시도: {current_value:.2f} USDT "
                        f"({current_value/original_value*100:.1f}%)"
                    )
                    continue
                else:
                    self.logger.error(f"주문 실패: {e}")
                    return None

        self.logger.error(
            f"증거금 부족: 최소 비율({min_ratio*100:.0f}%)까지 줄였으나 실패 "
            f"(시도 {attempt}회)"
        )
        return None

    # =========================================================================
    # 지정가 청산 주문 (익절/본절)
    # =========================================================================

    async def place_limit_close(
        self,
        direction: str,
        price: float,
        quantity: float,
        retry_on_reduce_only: bool = False,
        retry_decrement_pct: float = 0.001,
        min_ratio: float = 0.50
    ) -> Optional[Dict[str, Any]]:
        """
        지정가 청산 주문 (익절/본절)

        Args:
            direction: 포지션 방향 ('LONG' 또는 'SHORT')
            price: 청산 가격
            quantity: 주문 수량
            retry_on_reduce_only: ReduceOnly 실패 시 재시도 여부
            retry_decrement_pct: 재시도 시 줄이는 비율 (0.1%)
            min_ratio: 최소 비율 (50% 이하로는 안 줄임)

        Returns:
            주문 정보 또는 None
        """
        # 포지션 청산은 반대 방향
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        price = self._round_price(price)
        original_quantity = quantity
        current_quantity = quantity
        min_quantity = original_quantity * min_ratio

        if self.dry_run:
            self.logger.info(f"[DRY RUN] LIMIT Close: {direction} {self._round_qty(quantity)} @ ${price}")
            return {'orderId': 'DRY_RUN_CLOSE', 'status': 'DRY_RUN'}

        attempt = 0
        while current_quantity >= min_quantity:
            rounded_qty = self._round_qty(current_quantity)
            attempt += 1

            try:
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=side,
                    type='LIMIT',
                    price=price,
                    quantity=rounded_qty,
                    timeInForce='GTC',
                    reduceOnly=True
                )

                if current_quantity < original_quantity:
                    used_pct = (current_quantity / original_quantity) * 100
                    self.logger.warning(
                        f"ReduceOnly 수량 조정으로 주문 성공: {used_pct:.1f}% "
                        f"(시도 {attempt}회, {original_quantity:.6f} -> {rounded_qty:.6f})"
                    )
                self.logger.info(f"LIMIT Close 주문: {direction} {rounded_qty} @ ${price}, ID: {order['orderId']}")
                return order

            except BinanceAPIException as e:
                error_msg = str(e)
                if retry_on_reduce_only and ('ReduceOnly' in error_msg or 'rejected' in error_msg.lower()):
                    # ReduceOnly 거부 - 0.1%씩 줄여서 재시도
                    current_quantity -= original_quantity * retry_decrement_pct
                    self.logger.warning(
                        f"ReduceOnly 거부 (시도 {attempt}), 재시도: {self._round_qty(current_quantity):.6f} "
                        f"({current_quantity/original_quantity*100:.1f}%)"
                    )
                    continue
                else:
                    self.logger.error(f"지정가 청산 주문 실패: {e}")
                    return None

        self.logger.error(
            f"ReduceOnly 주문 실패: 최소 비율({min_ratio*100:.0f}%)까지 줄였으나 실패 "
            f"(시도 {attempt}회)"
        )
        return None

    # =========================================================================
    # 스탑 마켓 (손절)
    # =========================================================================

    async def set_stop_loss(
        self,
        direction: str,
        stop_price: float,
        quantity: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        손절 주문 설정 (STOP_MARKET via Algo Order API)

        2025-12-09부터 바이낸스는 조건부 주문을 Algo Order API로 이전
        POST /fapi/v1/algoOrder 사용

        Args:
            direction: 포지션 방향 ('LONG' 또는 'SHORT')
            stop_price: 손절 가격
            quantity: 수량 (None이면 전체 포지션)

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        stop_price = self._round_price(stop_price)

        if self.dry_run:
            self.logger.info(f"[DRY RUN] STOP_MARKET: ${stop_price}")
            return {'orderId': 'DRY_RUN_SL', 'status': 'DRY_RUN'}

        try:
            # Algo Order API 파라미터
            params = {
                'symbol': self.symbol,
                'side': side,
                'type': 'STOP_MARKET',
                'triggerPrice': str(stop_price),
                'closePosition': 'true',
                'algoType': 'CONDITIONAL'
            }

            # Algo Order API 호출 (POST /fapi/v1/algoOrder)
            order = self.client._request_futures_api('post', 'algoOrder', signed=True, data=params)
            algo_id = order.get('algoId', 'N/A')
            self.logger.info(f"STOP_MARKET 주문 (Algo): ${stop_price}, AlgoID: {algo_id}")

            # 기존 코드와 호환성을 위해 orderId 필드 추가
            order['orderId'] = algo_id
            return order

        except BinanceAPIException as e:
            self.logger.error(f"손절 주문 설정 실패: {e}")
            return None

    # =========================================================================
    # 시장가 주문
    # =========================================================================

    async def open_market_position(
        self,
        direction: str,
        quantity: float,
        leverage: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        시장가 포지션 진입

        Args:
            direction: 'LONG' 또는 'SHORT'
            quantity: 주문 수량
            leverage: 레버리지

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_BUY if direction == 'LONG' else SIDE_SELL
        quantity = self._round_qty(quantity)

        if quantity < 0.001:
            self.logger.warning(f"주문 취소: 수량 너무 작음 ({quantity})")
            return None

        # 마진/레버리지 설정
        await self.set_margin_type('ISOLATED')
        await self.set_leverage(leverage)

        if self.dry_run:
            order_id = f"DRYRUN_{int(datetime.now(pytz.UTC).timestamp() * 1000)}"
            self.logger.info(f"[DRY RUN] Market Order: {direction} {quantity}")
            return {'orderId': order_id, 'status': 'DRY_RUN'}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            self.logger.info(f"Market Order 체결: {direction} {quantity}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"시장가 주문 실패: {e}")
            return None

    async def close_position_market(
        self,
        direction: str,
        quantity: float
    ) -> Optional[Dict[str, Any]]:
        """
        시장가 포지션 청산

        Args:
            direction: 현재 포지션 방향 ('LONG' 또는 'SHORT')
            quantity: 청산 수량

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        quantity = self._round_qty(quantity)

        if self.dry_run:
            self.logger.info(f"[DRY RUN] 포지션 청산: {direction} {quantity}")
            return {'orderId': 'DRY_RUN_CLOSE', 'status': 'DRY_RUN'}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            self.logger.info(f"포지션 청산 완료: {direction} {quantity}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"포지션 청산 실패: {e}")
            return None

    # =========================================================================
    # 주문 관리
    # =========================================================================

    async def cancel_order(self, order_id: str) -> bool:
        """
        특정 주문 취소

        Args:
            order_id: 주문 ID

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.debug(f"[DRY RUN] 주문 취소: {order_id}")
            return True

        try:
            self.client.futures_cancel_order(
                symbol=self.symbol,
                orderId=order_id
            )
            self.logger.info(f"주문 취소: {order_id}")
            return True

        except BinanceAPIException as e:
            if 'Unknown order' in str(e):
                # 이미 체결되었거나 취소된 주문
                return True
            self.logger.warning(f"주문 취소 실패: {e}")
            return False

    async def cancel_all_orders(self) -> bool:
        """
        모든 대기 주문 취소

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.info("[DRY RUN] 모든 대기 주문 취소")
            return True

        try:
            self.client.futures_cancel_all_open_orders(symbol=self.symbol)
            self.logger.info("모든 대기 주문 취소 완료")
            return True

        except BinanceAPIException as e:
            self.logger.warning(f"주문 취소 실패: {e}")
            return False

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        대기 중인 주문 목록 조회

        Returns:
            주문 목록
        """
        try:
            return self.client.futures_get_open_orders(symbol=self.symbol)
        except BinanceAPIException as e:
            self.logger.error(f"주문 목록 조회 실패: {e}")
            return []

    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        주문 상태 조회

        Args:
            order_id: 주문 ID

        Returns:
            주문 정보 또는 None
        """
        try:
            return self.client.futures_get_order(
                symbol=self.symbol,
                orderId=order_id
            )
        except BinanceAPIException as e:
            self.logger.error(f"주문 조회 실패: {e}")
            return None

    # =========================================================================
    # 1분봉 데이터 (초기 설정용)
    # =========================================================================

    def get_latest_1m_close(self) -> Optional[float]:
        """
        최신 완성된 1분봉의 close 가격

        Returns:
            close 가격 또는 None
        """
        try:
            klines = self.client.futures_klines(
                symbol=self.symbol,
                interval='1m',
                limit=2  # 현재 진행 중인 봉 + 마지막 완성 봉
            )

            if len(klines) >= 2:
                # 마지막에서 두 번째 = 완성된 봉
                return float(klines[-2][4])  # Close price

            return None

        except BinanceAPIException as e:
            self.logger.error(f"1분봉 데이터 조회 실패: {e}")
            return None

    # =========================================================================
    # 현재가 조회
    # =========================================================================

    async def get_current_price(self) -> Optional[float]:
        """
        현재가 조회

        Returns:
            현재가 또는 None
        """
        try:
            ticker = self.client.futures_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            self.logger.error(f"현재가 조회 실패: {e}")
            return None

    # =========================================================================
    # 거래 PnL 조회
    # =========================================================================

    async def get_recent_trade_pnl(self, order_id: Optional[str] = None, limit: int = 10) -> Dict[str, float]:
        """
        최근 거래의 실현 PnL 및 수수료 조회

        Args:
            order_id: 특정 주문 ID (None이면 최근 거래)
            limit: 조회할 거래 수

        Returns:
            {'realized_pnl': float, 'commission': float, 'net_pnl': float}
        """
        try:
            trades = self.client.futures_account_trades(
                symbol=self.symbol,
                limit=limit
            )

            if not trades:
                return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

            # 특정 주문 ID로 필터링
            if order_id:
                trades = [t for t in trades if str(t.get('orderId')) == str(order_id)]

            # 합산
            total_pnl = sum(float(t.get('realizedPnl', 0)) for t in trades)
            total_commission = sum(float(t.get('commission', 0)) for t in trades)
            net_pnl = total_pnl - total_commission

            self.logger.debug(f"거래 PnL 조회: pnl=${total_pnl:.4f}, 수수료=${total_commission:.4f}, 순익=${net_pnl:.4f}")

            return {
                'realized_pnl': total_pnl,
                'commission': total_commission,
                'net_pnl': net_pnl
            }

        except BinanceAPIException as e:
            self.logger.error(f"거래 PnL 조회 실패: {e}")
            return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

    async def get_last_closed_trade_pnl(self) -> Dict[str, float]:
        """
        마지막 청산 거래의 PnL 조회
        (reduceOnly=True 또는 포지션 축소 거래)

        Returns:
            {'realized_pnl': float, 'commission': float, 'net_pnl': float}
        """
        try:
            trades = self.client.futures_account_trades(
                symbol=self.symbol,
                limit=20
            )

            if not trades:
                return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

            # realizedPnl이 0이 아닌 거래들 (청산 거래)
            close_trades = [t for t in trades if float(t.get('realizedPnl', 0)) != 0]

            if not close_trades:
                return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

            # 가장 최근 청산 거래
            last_trade = close_trades[-1]
            realized_pnl = float(last_trade.get('realizedPnl', 0))
            commission = float(last_trade.get('commission', 0))
            net_pnl = realized_pnl - commission

            self.logger.info(f"마지막 청산 PnL: pnl=${realized_pnl:.4f}, 수수료=${commission:.4f}, 순익=${net_pnl:.4f}")

            return {
                'realized_pnl': realized_pnl,
                'commission': commission,
                'net_pnl': net_pnl
            }

        except BinanceAPIException as e:
            self.logger.error(f"마지막 청산 PnL 조회 실패: {e}")
            return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

    async def get_order_pnl(self, order_id) -> Dict[str, float]:
        """
        특정 주문번호의 PnL 조회

        Args:
            order_id: 조회할 주문 ID (int 또는 str)

        Returns:
            {'realized_pnl': float, 'commission': float, 'net_pnl': float}
        """
        try:
            # order_id를 정수로 변환 (문자열일 수 있음)
            order_id_int = int(order_id) if order_id else None
            if not order_id_int:
                self.logger.warning("유효하지 않은 주문번호")
                return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

            trades = self.client.futures_account_trades(
                symbol=self.symbol,
                limit=100
            )

            # 해당 주문번호의 trade들 필터링 (한 주문이 여러 체결로 나뉠 수 있음)
            order_trades = [t for t in trades if t.get('orderId') == order_id_int]

            if not order_trades:
                self.logger.warning(f"주문 {order_id}의 체결 내역을 찾을 수 없음")
                return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

            # 모든 체결의 PnL 합산
            total_pnl = sum(float(t.get('realizedPnl', 0)) for t in order_trades)
            total_commission = sum(float(t.get('commission', 0)) for t in order_trades)
            net_pnl = total_pnl - total_commission

            self.logger.info(
                f"주문 {order_id} PnL: pnl=${total_pnl:.4f}, 수수료=${total_commission:.4f}, 순익=${net_pnl:.4f}"
            )

            return {
                'realized_pnl': total_pnl,
                'commission': total_commission,
                'net_pnl': net_pnl
            }

        except BinanceAPIException as e:
            self.logger.error(f"주문 PnL 조회 실패: {e}")
            return {'realized_pnl': 0.0, 'commission': 0.0, 'net_pnl': 0.0}

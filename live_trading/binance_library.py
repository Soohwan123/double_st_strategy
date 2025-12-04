#!/usr/bin/env python3
"""
Binance Futures API Library
바이낸스 선물 거래 API 래퍼 클래스

이식성을 위해 전략 로직과 분리된 순수 API 호출 모듈
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
    바이낸스 선물 거래 API 클라이언트

    Usage:
        client = Client(api_key, api_secret)
        binance = BinanceFuturesClient(client, symbol='BTCUSDC', logger=my_logger)

        # 계좌 정보
        balance = await binance.get_account_balance('USDC')

        # 포지션 진입
        order = await binance.open_market_position(
            direction='LONG',
            quantity=0.001,
            leverage=10
        )

        # 익절 주문
        await binance.set_take_profit_limit(
            direction='LONG',
            price=67500.0,
            quantity=0.001
        )

        # 본절 스탑
        await binance.set_stop_market(
            direction='LONG',
            stop_price=67000.0
        )
    """

    def __init__(
        self,
        client: Client,
        symbol: str,
        logger: Optional[logging.Logger] = None,
        dry_run: bool = True
    ):
        """
        Args:
            client: python-binance Client 인스턴스
            symbol: 거래 심볼 (예: 'BTCUSDC')
            logger: 로깅용 로거 (None이면 기본 로거 사용)
            dry_run: True면 실제 주문 없이 로그만 출력
        """
        self.client = client
        self.symbol = symbol
        self.logger = logger or logging.getLogger(__name__)
        self.dry_run = dry_run

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
                'unrealized_pnl': float,
                'leverage': int
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
                        'unrealized_pnl': float(pos['unRealizedProfit']),
                        'leverage': int(pos['leverage'])
                    }

            return None

        except BinanceAPIException as e:
            self.logger.error(f"포지션 정보 조회 실패: {e}")
            raise

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
            self.logger.info(f"🔇 [DRY RUN] Leverage: {leverage}x")
            return True

        try:
            self.client.futures_change_leverage(
                symbol=self.symbol,
                leverage=leverage
            )
            self.logger.info(f"✔ Leverage: {leverage}x")
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
            self.logger.info(f"🔇 [DRY RUN] Margin mode: {margin_type}")
            return True

        try:
            self.client.futures_change_margin_type(
                symbol=self.symbol,
                marginType=margin_type
            )
            self.logger.info(f"✔ Margin mode: {margin_type}")
            return True

        except BinanceAPIException as e:
            if 'No need to change margin type' in str(e):
                return True
            self.logger.warning(f"Margin type 설정: {e}")
            return False

    # =========================================================================
    # 주문 실행
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
            leverage: 레버리지 (기본 10배)

        Returns:
            주문 정보 딕셔너리 또는 None
        """
        side = SIDE_BUY if direction == 'LONG' else SIDE_SELL
        quantity = round(quantity, 3)

        if quantity < 0.001:
            self.logger.warning(f"⚠️ 주문 취소: 수량 너무 작음 ({quantity})")
            return None

        # 마진/레버리지 설정
        await self.set_margin_type('ISOLATED')
        await self.set_leverage(leverage)

        if self.dry_run:
            order_id = f"DRYRUN_{int(datetime.now(pytz.UTC).timestamp() * 1000)}"
            self.logger.info(f"🔇 [DRY RUN] Market Order: {direction} {quantity:.4f}")
            return {'orderId': order_id, 'status': 'DRY_RUN'}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            self.logger.info(f"✅ Market Order 체결: {direction} {quantity:.4f}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"시장가 주문 실패: {e}")
            return None

    async def set_take_profit_limit(
        self,
        direction: str,
        price: float,
        quantity: float
    ) -> Optional[Dict[str, Any]]:
        """
        익절 지정가 주문 설정

        Args:
            direction: 포지션 방향 ('LONG' 또는 'SHORT')
            price: 익절 가격
            quantity: 주문 수량

        Returns:
            주문 정보 또는 None
        """
        # 포지션 청산은 반대 방향
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        price = round(price, 1)
        quantity = round(quantity, 3)

        if self.dry_run:
            self.logger.info(f"🔇 [DRY RUN] 익절 LIMIT 주문: ${price:.1f}")
            return {'orderId': 'DRY_RUN_TP', 'status': 'DRY_RUN'}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type='LIMIT',
                price=price,
                quantity=quantity,
                timeInForce='GTC'
            )
            self.logger.info(f"💰 익절 주문 설정: ${price:.1f}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"익절 주문 설정 실패: {e}")
            return None

    async def set_stop_market(
        self,
        direction: str,
        stop_price: float,
        close_position: bool = True,
        quantity: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        스탑 마켓 주문 설정

        Args:
            direction: 포지션 방향 ('LONG' 또는 'SHORT')
            stop_price: 스탑 가격
            close_position: True면 전체 포지션 청산
            quantity: close_position=False일 때 수량

        Returns:
            주문 정보 또는 None
        """
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        stop_price = round(stop_price, 1)

        if self.dry_run:
            self.logger.info(f"🔇 [DRY RUN] STOP_MARKET 주문: ${stop_price:.1f}")
            return {'orderId': 'DRY_RUN_SL', 'status': 'DRY_RUN'}

        try:
            order_params = {
                'symbol': self.symbol,
                'side': side,
                'type': 'STOP_MARKET',
                'stopPrice': stop_price
            }

            if close_position:
                order_params['closePosition'] = True
            else:
                order_params['quantity'] = round(quantity, 3)

            order = self.client.futures_create_order(**order_params)
            self.logger.info(f"🛑 STOP_MARKET 주문 설정: ${stop_price:.1f}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"스탑 주문 설정 실패: {e}")
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
        # 포지션 청산은 반대 방향
        side = SIDE_SELL if direction == 'LONG' else SIDE_BUY
        quantity = round(quantity, 3)

        if self.dry_run:
            self.logger.info(f"🔇 [DRY RUN] 포지션 청산: {direction} {quantity:.4f}")
            return {'orderId': 'DRY_RUN_CLOSE', 'status': 'DRY_RUN'}

        try:
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            self.logger.info(f"✅ 포지션 청산 완료: {direction} {quantity:.4f}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"포지션 청산 실패: {e}")
            return None

    # =========================================================================
    # 주문 취소
    # =========================================================================

    async def cancel_all_orders(self) -> bool:
        """
        모든 대기 주문 취소

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.info("🔇 [DRY RUN] 대기 주문 취소 (스킵)")
            return True

        try:
            self.client.futures_cancel_all_open_orders(symbol=self.symbol)
            self.logger.info("✅ 모든 대기 주문 취소 완료")
            return True

        except BinanceAPIException as e:
            self.logger.warning(f"주문 취소 실패: {e}")
            return False

    async def cancel_stop_orders(self) -> bool:
        """
        STOP_MARKET 주문만 취소 (LIMIT 익절 주문은 유지)

        Returns:
            성공 여부
        """
        if self.dry_run:
            self.logger.debug("🔇 [DRY RUN] STOP 주문 취소 (스킵)")
            return True

        try:
            open_orders = self.client.futures_get_open_orders(symbol=self.symbol)

            for order in open_orders:
                if order['type'] == 'STOP_MARKET':
                    self.client.futures_cancel_order(
                        symbol=self.symbol,
                        orderId=order['orderId']
                    )
                    self.logger.info(f"STOP 주문 취소: ID {order['orderId']}")

            return True

        except BinanceAPIException as e:
            self.logger.warning(f"STOP 주문 취소 실패: {e}")
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

    # =========================================================================
    # 과거 데이터 로드
    # =========================================================================

    def get_historical_klines(
        self,
        interval: str = '5m',
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """
        과거 캔들 데이터 로드

        Args:
            interval: 캔들 간격 ('1m', '5m', '15m', '1h' 등)
            limit: 가져올 캔들 수

        Returns:
            캔들 데이터 리스트
            [{'timestamp': datetime, 'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float}, ...]
        """
        try:
            klines = self.client.futures_klines(
                symbol=self.symbol,
                interval=interval,
                limit=limit + 1  # 마지막 미완성 봉 제외용
            )

            candles = []
            # 마지막 캔들(미완성) 제외
            for kline in klines[:-1]:
                candles.append({
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000, tz=pytz.UTC),
                    'Open': float(kline[1]),
                    'High': float(kline[2]),
                    'Low': float(kline[3]),
                    'Close': float(kline[4]),
                    'Volume': float(kline[5])
                })

            self.logger.info(f"✅ {interval}봉 로드 완료: {len(candles)}개")
            return candles

        except BinanceAPIException as e:
            self.logger.error(f"과거 데이터 로드 실패: {e}")
            return []

    # =========================================================================
    # 포지션 모니터링
    # =========================================================================

    async def monitor_position_status(
        self,
        interval_seconds: int = 5,
        on_position_closed: Optional[Callable[[str, float], None]] = None
    ):
        """
        포지션 상태 모니터링 (비동기 루프)

        Args:
            interval_seconds: 체크 간격 (초)
            on_position_closed: 포지션 청산 시 콜백 함수
                - 첫 번째 인자: 청산 이유 ('TAKE_PROFIT', 'STOP_LOSS', 'BREAK_EVEN')
                - 두 번째 인자: 실현 PnL
        """
        if self.dry_run:
            self.logger.info("🔇 [DRY RUN] 포지션 모니터링 비활성화")
            while True:
                await asyncio.sleep(30)
            return

        last_position = None

        while True:
            try:
                await asyncio.sleep(interval_seconds)

                current_position = await self.get_position_info()

                # 포지션이 있었는데 없어졌으면 = 청산됨
                if last_position is not None and current_position is None:
                    # 마지막 PnL 정보로 청산 이유 추정
                    pnl = last_position.get('unrealized_pnl', 0)

                    if pnl > 0:
                        reason = 'TAKE_PROFIT'
                    elif abs(pnl) < last_position.get('size', 0) * 0.002:
                        reason = 'BREAK_EVEN'
                    else:
                        reason = 'STOP_LOSS'

                    self.logger.info(f"💰 포지션 청산 감지: {reason}, PnL: ${pnl:.2f}")

                    if on_position_closed:
                        on_position_closed(reason, pnl)

                last_position = current_position

            except Exception as e:
                self.logger.error(f"포지션 모니터링 에러: {e}")

#!/usr/bin/env python3
"""
Double Bollinger Band Strategy 실시간 자동매매 프로그램
Binance Futures BTCUSDC Perpetual 거래용
5분봉 기준 BB(20,2) + BB(4,4) 동시 터치 전략
"""

import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime
import os
from typing import Optional
import websockets
import websockets.exceptions
from binance.client import Client
from binance.enums import *
import pytz

from config import Config

# 분리된 모듈 import
from binance_library import BinanceFuturesClient
from data_handle import (
    CandleDataManager,
    DailyLogHandler,
    DataRecorder,
    DEFAULT_BB_SETTINGS
)


# =============================================================================
# 로깅 및 디렉토리 설정
# =============================================================================

os.makedirs(Config.LOGS_DIR, exist_ok=True)
os.makedirs('trade_results', exist_ok=True)
os.makedirs('live_data', exist_ok=True)

# 전역 로그 핸들러 생성
daily_log_handler = DailyLogHandler('double_st_strategy_btcusdc', Config.LOGS_DIR)
logger = daily_log_handler.get_logger()


# =============================================================================
# Double Bollinger Band 전략
# =============================================================================

class DoubleBBStrategy:
    """Double Bollinger Band 실시간 트레이딩 전략"""

    def __init__(self, client: Client, log_handler: DailyLogHandler):
        self.log_handler = log_handler

        # 바이낸스 API 클라이언트 (분리된 모듈)
        self.binance = BinanceFuturesClient(
            client=client,
            symbol=Config.SYMBOL,
            logger=self.get_logger(),
            dry_run=True  # DRY RUN 모드
        )

        # 캔들 데이터 관리 (분리된 모듈)
        self.candle_5m = CandleDataManager(
            timeframe='5m',
            max_candles=Config.MAX_5M_CANDLES,
            bb_settings=DEFAULT_BB_SETTINGS,
            min_candles_for_indicators=Config.MIN_CANDLES_FOR_INDICATORS
        )

        # 데이터 기록 (분리된 모듈)
        self.recorder = DataRecorder(
            trades_path=Config.TRADES_CSV_PATH,
            indicators_path=Config.LIVE_INDICATOR_CSV,
            logger=self.get_logger()
        )

        # 포지션 상태
        self.position = None
        self.position_side = None  # 'LONG' or 'SHORT'
        self.entry_price = 0
        self.entry_bar_closed = False
        self.take_profit_price = 0
        self.position_size = 0
        self.position_value = 0

        # 타임프레임 동기화
        self.last_candle_time = {'5m': None}

        # 설정 (Config에서 가져오기)
        self.symbol = Config.SYMBOL
        self.leverage = Config.LEVERAGE
        self.position_size_pct = Config.POSITION_SIZE_PCT
        self.take_profit_pct = Config.TAKE_PROFIT_PCT
        self.fee_rate = Config.FEE_RATE

        # 잔고 정보
        self.usdc_balance = 0
        self.capital = 0

    def get_logger(self):
        """일별 로거 반환"""
        return self.log_handler.get_logger()

    # =========================================================================
    # 데이터 로드 및 저장
    # =========================================================================

    async def load_historical_data(self):
        """과거 데이터 로드 및 초기 지표 계산"""
        logger = self.get_logger()
        logger.info("📊 과거 데이터 로드 시작...")

        try:
            # 5분봉 데이터 로드 (binance_library 사용)
            candles = self.binance.get_historical_klines(
                interval='5m',
                limit=Config.MAX_5M_CANDLES
            )

            # 캔들 데이터 매니저에 로드
            self.candle_5m.load_historical(candles)
            self.candle_5m.calculate_indicators()

            logger.info(f"✅ 5분봉 로드 완료: {len(self.candle_5m.df)}개")

            # 초기 last_candle_time 설정
            self.last_candle_time['5m'] = self.candle_5m.get_last_timestamp()
            logger.info(f"✅ 초기 타임프레임 설정: 5m={self.last_candle_time['5m']}")

            # 과거 데이터 CSV 저장
            logger.info("📝 과거 데이터 CSV 저장 시작...")
            self.recorder.save_historical_indicators(self.candle_5m.df)
            logger.info(f"✅ 과거 데이터 CSV 저장 완료: {len(self.candle_5m.df)}개 행")

        except Exception as e:
            logger.error(f"❌ 과거 데이터 로드 실패: {e}")
            raise

    def save_indicators_to_csv(self):
        """현재 지표를 CSV에 저장"""
        latest = self.candle_5m.get_latest_indicators()
        if latest:
            # Volume 추가
            if len(self.candle_5m.df) > 0:
                latest['Volume'] = self.candle_5m.df.iloc[-1].get('Volume', 0)
            self.recorder.save_indicator(latest)

    # =========================================================================
    # 계좌 정보
    # =========================================================================

    async def update_account_info(self):
        """계좌 정보 업데이트"""
        try:
            balance = await self.binance.get_account_balance('USDC')
            self.usdc_balance = balance['wallet_balance']
            self.capital = balance['available_balance']
        except Exception as e:
            logger = self.get_logger()
            logger.error(f"계좌 정보 업데이트 실패: {e}")

    async def sync_capital(self):
        """자본 동기화"""
        await self.update_account_info()

    # =========================================================================
    # 포지션 관리
    # =========================================================================

    async def open_position(self, direction: str, entry_price: float):
        """
        포지션 진입
        - 레버리지 10배 고정
        - 익절: 진입가의 0.3%
        - 본절 스탑로스: 다음 봉부터 진입가에 설정
        """
        logger = self.get_logger()

        try:
            # 잔고 확인
            if self.capital <= 0:
                logger.warning(f"⚠️ 진입 취소: 잔고 부족 (${self.capital:.2f})")
                return

            # 포지션 가치 계산 (자본의 100% * 레버리지)
            position_value = self.capital * self.position_size_pct * self.leverage

            # 포지션 크기 계산 (BTC 수량)
            position_size = position_value / entry_price

            # 주문 수량 계산 (소수점 3자리)
            quantity = round(position_size, 3)
            if quantity < 0.001:
                logger.warning(f"⚠️ 진입 취소: 수량 너무 작음 ({quantity})")
                return

            # 익절가 계산 (0.3%)
            if direction == 'LONG':
                take_profit_price = entry_price * (1 + self.take_profit_pct)
            else:
                take_profit_price = entry_price * (1 - self.take_profit_pct)

            # 시장가 주문 실행 (binance_library 사용)
            order = await self.binance.open_market_position(
                direction=direction,
                quantity=quantity,
                leverage=self.leverage
            )

            if order is None:
                return

            # 포지션 정보 저장
            self.position = {
                'side': direction,
                'entry_price': entry_price,
                'entry_time': datetime.now(pytz.UTC),
                'entry_bar_closed': False,
                'target_price': take_profit_price,
                'quantity': quantity,
                'position_value': position_value,
                'leverage': self.leverage,
                'order_id': order.get('orderId', 'UNKNOWN')
            }

            # 하위 호환성 유지
            self.position_side = direction
            self.entry_price = entry_price
            self.take_profit_price = take_profit_price
            self.position_size = quantity
            self.position_value = position_value
            self.entry_bar_closed = False

            # 익절 주문 설정
            await self.set_take_profit_order()

            entry_msg = f"✅ {direction} 진입 완료\n"
            entry_msg += f"   진입가: ${entry_price:.2f}\n"
            entry_msg += f"   수량: {quantity:.4f} BTC\n"
            entry_msg += f"   익절: ${take_profit_price:.2f} ({self.take_profit_pct*100:.1f}%)\n"
            entry_msg += f"   본절: 다음 봉부터 진입가에 활성화\n"
            entry_msg += f"   레버리지: {self.leverage}x"

            logger.info(entry_msg)
            print(entry_msg)

            # CSV 기록
            self.recorder.save_trade('OPEN', direction, entry_price, quantity, 0, self.capital)

        except Exception as e:
            logger.error(f"❌ 포지션 진입 실패: {e}")

    async def set_take_profit_order(self):
        """익절 주문 설정 (LIMIT)"""
        if not self.position:
            return

        await self.binance.set_take_profit_limit(
            direction=self.position['side'],
            price=self.position['target_price'],
            quantity=self.position['quantity']
        )

    async def set_break_even_stop(self):
        """본절 스탑로스 설정 (진입가에 STOP_MARKET)"""
        if not self.position:
            return

        logger = self.get_logger()

        try:
            # 기존 STOP 주문 취소
            await self.binance.cancel_stop_orders()

            # 본절 스탑 설정
            await self.binance.set_stop_market(
                direction=self.position['side'],
                stop_price=self.position['entry_price'],
                close_position=True
            )

        except Exception as e:
            logger.error(f"본절 스탑로스 설정 실패: {e}")

    async def cancel_pending_orders(self):
        """대기 주문 취소"""
        await self.binance.cancel_all_orders()

    async def check_candle_close(self):
        """
        새 봉 마감 감지 및 본절 스탑로스 설정
        진입 봉이 마감되면 본절 스탑로스 활성화
        """
        if self.position is None:
            return

        if self.entry_bar_closed:
            return

        current_time = self.candle_5m.get_last_timestamp()
        if current_time is None:
            return

        # 진입 시간과 다른 봉이면 = 진입 봉 마감됨
        entry_time = self.position['entry_time']
        entry_candle_time = entry_time.replace(
            minute=(entry_time.minute // 5) * 5,
            second=0,
            microsecond=0
        )

        if current_time > entry_candle_time:
            logger = self.get_logger()
            logger.info("📊 진입 봉 마감 확인 - 본절 스탑로스 활성화")

            await self.set_break_even_stop()

            self.entry_bar_closed = True
            self.position['entry_bar_closed'] = True

    async def close_position_manual(self, exit_type: str, exit_price: float):
        """수동 포지션 청산"""
        logger = self.get_logger()

        if self.position is None:
            return

        try:
            # PnL 계산
            if self.position_side == 'LONG':
                pnl = (exit_price - self.entry_price) * self.position_size
            else:
                pnl = (self.entry_price - exit_price) * self.position_size

            # 시장가 청산
            await self.binance.close_position_market(
                direction=self.position_side,
                quantity=self.position_size
            )

            logger.info(f"포지션 청산: {exit_type}, PnL=${pnl:.2f}")

            # 자본 동기화
            await self.sync_capital()

            # 거래 기록
            self.recorder.save_trade(
                exit_type, self.position_side, exit_price,
                self.position_size, pnl, self.capital
            )

            # 대기 주문 취소
            await self.cancel_pending_orders()

            # 포지션 초기화
            self._reset_position()

        except Exception as e:
            logger.error(f"❌ 포지션 청산 실패: {e}")

    def _reset_position(self):
        """포지션 상태 초기화"""
        self.position = None
        self.position_side = None
        self.entry_price = 0
        self.take_profit_price = 0
        self.position_size = 0
        self.position_value = 0
        self.entry_bar_closed = False

    # =========================================================================
    # 포지션 모니터링
    # =========================================================================

    async def monitor_positions(self):
        """바이낸스 포지션 상태 주기적 확인"""
        logger = self.get_logger()

        if self.binance.dry_run:
            logger.info("🔇 [DRY RUN] 포지션 모니터링 비활성화 (실제 거래 없음)")
            while True:
                await asyncio.sleep(30)
            return

        # 실제 거래 모드 - binance_library의 모니터링 사용
        def on_position_closed(reason: str, pnl: float):
            """포지션 청산 콜백"""
            asyncio.create_task(self._handle_position_closed(reason, pnl))

        await self.binance.monitor_position_status(
            interval_seconds=5,
            on_position_closed=on_position_closed
        )

    async def _handle_position_closed(self, reason: str, pnl: float):
        """포지션 청산 처리"""
        if self.position is None:
            return

        logger = self.get_logger()
        logger.info(f"💰 {self.position['side']} {reason}, PnL: ${pnl:.2f}")

        # 청산 가격 추정
        if reason == 'TAKE_PROFIT':
            exit_price = self.position['target_price']
        else:
            exit_price = self.position['entry_price']

        # 자본 동기화
        await self.sync_capital()

        # 거래 기록
        self.recorder.save_trade(
            reason, self.position['side'], exit_price,
            self.position['quantity'], pnl, self.capital
        )

        # 대기 주문 취소
        await self.cancel_pending_orders()

        # 포지션 초기화
        self._reset_position()

    # =========================================================================
    # 틱데이터 및 캔들 처리
    # =========================================================================

    async def on_tick(self, trade: dict):
        """
        틱데이터(aggTrade) 처리
        - 실시간 가격으로 BB 터치 감지하여 즉시 진입
        """
        if self.position is not None:
            return  # 이미 포지션 있으면 패스

        # 현재 가격
        price = float(trade['p'])

        # 최신 BB 값 (마지막 마감된 봉 기준)
        latest = self.candle_5m.get_latest_indicators()
        if latest is None:
            return

        bb_upper_20_2 = latest.get('bb_upper_20_2')
        bb_lower_20_2 = latest.get('bb_lower_20_2')
        bb_upper_4_4 = latest.get('bb_upper_4_4')
        bb_lower_4_4 = latest.get('bb_lower_4_4')

        # NaN 체크
        if pd.isna(bb_upper_20_2) or pd.isna(bb_lower_20_2) or \
           pd.isna(bb_upper_4_4) or pd.isna(bb_lower_4_4):
            return

        logger = self.get_logger()

        # LONG 진입: 가격이 두 lower band 동시 터치
        if price <= bb_lower_20_2 and price <= bb_lower_4_4:
            # 더 낮은 값에 진입 (롱일 때 더 유리)
            entry_price = min(bb_lower_20_2, bb_lower_4_4)
            logger.info(
                f"🔵 LONG 틱터치 감지! - Price: {price:.2f}, "
                f"BB(20,2): {bb_lower_20_2:.2f}, BB(4,4): {bb_lower_4_4:.2f}, "
                f"진입가: {entry_price:.2f}"
            )
            await self.open_position('LONG', entry_price)

        # SHORT 진입: 가격이 두 upper band 동시 터치
        elif price >= bb_upper_20_2 and price >= bb_upper_4_4:
            # 더 높은 값에 진입 (숏일 때 더 유리)
            entry_price = max(bb_upper_20_2, bb_upper_4_4)
            logger.info(
                f"🔴 SHORT 틱터치 감지! - Price: {price:.2f}, "
                f"BB(20,2): {bb_upper_20_2:.2f}, BB(4,4): {bb_upper_4_4:.2f}, "
                f"진입가: {entry_price:.2f}"
            )
            await self.open_position('SHORT', entry_price)

    async def on_5m_candle_close(self, kline: dict):
        """5분봉 종료 시 처리"""
        logger = self.get_logger()

        # 5분봉 시간
        candle_time = datetime.fromtimestamp(kline['t'] / 1000, tz=pytz.UTC)

        logger.info(
            f"📊 5m | {candle_time.strftime('%H:%M')} | "
            f"O:{float(kline['o']):.1f} H:{float(kline['h']):.1f} "
            f"L:{float(kline['l']):.1f} C:{float(kline['c']):.1f}"
        )

        # 캔들 데이터 업데이트
        self.candle_5m.update_from_kline(kline)

        # BB 지표 계산
        self.candle_5m.calculate_indicators()

        # 새 봉 체크 (본절 활성화)
        await self.check_candle_close()

        # CSV 저장
        self.save_indicators_to_csv()


# =============================================================================
# 웹소켓 스트림 처리
# =============================================================================

async def stream_handler(strategy: DoubleBBStrategy):
    """웹소켓 스트림 핸들러 (5분봉 + 틱데이터)"""
    logger = strategy.get_logger()

    # 스트림 URL (Config에서 가져오기)
    stream_url = Config.get_ws_stream_url()

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info("🔗 웹소켓 연결 성공 (5분봉 + 틱데이터)")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if 'data' not in data:
                        continue

                    stream_data = data['data']

                    # 5분봉 데이터
                    if 'k' in stream_data:
                        kline = stream_data['k']

                        # 캔들 종료 시에만 처리 (BB 재계산)
                        if kline['x']:
                            await strategy.on_5m_candle_close(kline)

                    # 틱데이터 (aggTrade)
                    elif 'p' in stream_data and 'q' in stream_data:
                        # 실시간 터치 감지
                        await strategy.on_tick(stream_data)

        except Exception as e:
            logger.error(f"웹소켓 에러: {e}")
            await asyncio.sleep(Config.WS_RECONNECT_DELAY)


# =============================================================================
# 메인 실행
# =============================================================================

async def main():
    """메인 실행 함수"""
    logger = daily_log_handler.get_logger()
    logger.info("=" * 80)
    logger.info("🚀 Double Bollinger Band Strategy 시작")
    logger.info("=" * 80)

    # Binance 클라이언트 생성
    client = Client(Config.API_KEY, Config.API_SECRET)

    # 전략 인스턴스 생성
    strategy = DoubleBBStrategy(client, daily_log_handler)

    # 과거 데이터 로드
    await strategy.load_historical_data()

    # 계좌 정보 업데이트
    await strategy.update_account_info()
    logger.info(f"💰 계좌 잔고: {strategy.capital:.2f} USDC")

    # 포지션 모니터링 태스크 시작
    monitor_task = asyncio.create_task(strategy.monitor_positions())
    logger.info("🔍 포지션 모니터링 시작 (5초 간격)")

    # 웹소켓 스트림 시작
    try:
        await stream_handler(strategy)
    finally:
        # 정리 작업
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 프로그램 종료")

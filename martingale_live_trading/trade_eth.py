#!/usr/bin/env python3
"""
ETHUSDC Grid Martingale Live Trading
ETH 전용 실시간 자동매매 프로그램

실행: python trade_eth.py
"""

import asyncio
import json
import os
import sys
import logging
from datetime import datetime
import pytz
import websockets
import websockets.exceptions
from binance.client import Client

from config import Config, DynamicConfig
from binance_library import BinanceFuturesClient
from grid_strategy import GridMartingaleStrategy


# =============================================================================
# 상수
# =============================================================================

SYMBOL_TYPE = 'eth'
SYMBOL = Config.get_symbol(SYMBOL_TYPE)  # 'ETHUSDC'


# =============================================================================
# 로깅 설정
# =============================================================================

class DailyLogHandler:
    """일별 로그 파일 관리"""

    def __init__(self, prefix: str, logs_dir: str = 'logs'):
        self.prefix = prefix
        self.logs_dir = logs_dir
        self.current_date = None
        self.logger = None
        os.makedirs(logs_dir, exist_ok=True)
        self.setup_logger()

    def setup_logger(self):
        """로거 설정"""
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')

        if today != self.current_date:
            self.current_date = today
            log_filename = f'{self.logs_dir}/{self.prefix}_{today}.log'

            if self.logger:
                for handler in self.logger.handlers[:]:
                    handler.close()
                    self.logger.removeHandler(handler)

            self.logger = logging.getLogger(f'{self.prefix}_{today}')
            self.logger.setLevel(logging.INFO)
            self.logger.handlers.clear()

            # 파일 핸들러
            file_handler = logging.FileHandler(log_filename)
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(file_handler)

            # 콘솔 핸들러
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """로거 반환"""
        self.setup_logger()
        return self.logger


# 전역 로그 핸들러
log_handler = DailyLogHandler(Config.get_log_prefix(SYMBOL_TYPE), Config.LOGS_DIR)


# =============================================================================
# 웹소켓 핸들러
# =============================================================================

async def websocket_handler(strategy: GridMartingaleStrategy):
    """
    웹소켓 스트림 핸들러

    1. 첫 1분봉 완성 시 grid_center 설정 + 거미줄 주문
    2. 이후 틱데이터로 체결 감지
    """
    logger = log_handler.get_logger()
    stream_url = Config.get_ws_stream_url(SYMBOL_TYPE)

    first_candle_received = False

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info(f"웹소켓 연결: {SYMBOL}")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if 'data' not in data:
                        continue

                    stream_data = data['data']

                    # 1분봉 데이터
                    if 'k' in stream_data:
                        kline = stream_data['k']

                        # 캔들 종료 시
                        if kline['x'] and not first_candle_received:
                            close_price = float(kline['c'])
                            logger.info(f"첫 1분봉 완성: Close=${close_price:.2f}")

                            # 상태 복구되지 않은 경우에만 새 그리드 설정
                            if strategy.grid_center is None:
                                await strategy.setup_grid_orders(close_price)

                            first_candle_received = True

                    # 틱데이터 (aggTrade)
                    elif 'p' in stream_data and 'q' in stream_data:
                        if first_candle_received or strategy.grid_center is not None:
                            price = float(stream_data['p'])
                            await strategy.on_tick(price)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("웹소켓 연결 종료, 재연결 중...")
            await asyncio.sleep(Config.WS_RECONNECT_DELAY)

        except Exception as e:
            logger.error(f"웹소켓 에러: {e}")
            await asyncio.sleep(Config.WS_RECONNECT_DELAY)


# =============================================================================
# 포지션 동기화 태스크
# =============================================================================

async def position_sync_task(strategy: GridMartingaleStrategy, interval: int = 30):
    """
    바이낸스 포지션과 주기적 동기화
    예상치 못한 청산 감지
    """
    logger = log_handler.get_logger()

    while True:
        try:
            await asyncio.sleep(interval)

            # 바이낸스 실제 포지션 확인
            pos_info = await strategy.binance.get_position_info()

            if strategy.position.has_position() and pos_info is None:
                # 로컬에는 포지션 있는데 바이낸스에는 없음 = 예상치 못한 청산
                logger.warning("예상치 못한 포지션 청산 감지!")

                # 현재가로 그리드 재설정
                current_price = await strategy.binance.get_current_price()
                if current_price:
                    await strategy.reset_grid_after_full_close(current_price)

        except Exception as e:
            logger.error(f"포지션 동기화 에러: {e}")


# =============================================================================
# 설정 리로드 태스크
# =============================================================================

async def config_reload_task(strategy: GridMartingaleStrategy, interval: int = 60):
    """
    동적 설정 주기적 리로드
    config_eth.txt 변경 감지
    """
    logger = log_handler.get_logger()

    while True:
        try:
            await asyncio.sleep(interval)

            if strategy.dynamic_config.reload():
                logger.info("설정 파일 변경 감지, 리로드 완료")

        except Exception as e:
            logger.error(f"설정 리로드 에러: {e}")


# =============================================================================
# 메인
# =============================================================================

async def main():
    """메인 실행 함수"""
    logger = log_handler.get_logger()

    logger.info("=" * 70)
    logger.info(f"ETHUSDC Grid Martingale Live Trading 시작")
    logger.info("=" * 70)

    # 설정 검증
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        sys.exit(1)

    # Binance 클라이언트 생성
    client = Client(Config.API_KEY, Config.API_SECRET)

    # API 래퍼 생성
    binance = BinanceFuturesClient(
        client=client,
        symbol=SYMBOL,
        logger=logger,
        dry_run=False,  # 실거래 모드
        price_precision=Config.get_price_precision(SYMBOL_TYPE),
        qty_precision=Config.get_qty_precision(SYMBOL_TYPE)
    )

    # 전략 인스턴스 생성
    strategy = GridMartingaleStrategy(
        binance=binance,
        symbol_type=SYMBOL_TYPE,
        logger=logger
    )

    # 초기화
    await strategy.initialize()

    # 태스크 시작
    tasks = [
        asyncio.create_task(websocket_handler(strategy)),
        asyncio.create_task(position_sync_task(strategy, interval=30)),
        asyncio.create_task(config_reload_task(strategy, interval=60))
    ]

    logger.info("모든 태스크 시작 완료")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("태스크 취소됨")
    finally:
        # 정리
        for task in tasks:
            task.cancel()

        logger.info("프로그램 종료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n프로그램 종료 (Ctrl+C)")

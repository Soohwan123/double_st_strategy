#!/usr/bin/env python3
"""
BTCUSDC Grid Martingale Live Trading
BTC 전용 실시간 자동매매 프로그램

실행: python trade_btc.py
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

SYMBOL_TYPE = 'btc'
SYMBOL = Config.get_symbol(SYMBOL_TYPE)  # 'BTCUSDC'


# =============================================================================
# 로깅 설정
# =============================================================================

class DailyRotatingLogger:
    """
    일별 로그 파일 자동 교체 로거

    매 로그 출력 시 날짜를 체크하여 자동으로 새 파일 생성
    """

    def __init__(self, prefix: str, logs_dir: str = 'logs'):
        self.prefix = prefix
        self.logs_dir = logs_dir
        self.current_date = None
        self.file_handler = None
        self._logger = logging.getLogger(f'{prefix}_daily')
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False  # 중복 로깅 방지
        os.makedirs(logs_dir, exist_ok=True)

        # 콘솔 핸들러 (한 번만 추가)
        if not any(isinstance(h, logging.StreamHandler) for h in self._logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self._logger.addHandler(console_handler)

        self._update_file_handler()

    def _update_file_handler(self):
        """날짜 변경 시 파일 핸들러 교체"""
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')

        if today != self.current_date:
            self.current_date = today
            log_filename = f'{self.logs_dir}/{self.prefix}_{today}.log'

            # 기존 파일 핸들러 제거
            if self.file_handler:
                self._logger.removeHandler(self.file_handler)
                self.file_handler.close()

            # 새 파일 핸들러 추가
            self.file_handler = logging.FileHandler(log_filename)
            self.file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self._logger.addHandler(self.file_handler)

            self._logger.info(f"=== 로그 파일 시작: {log_filename} ===")

    def _check_date(self):
        """날짜 체크 후 필요 시 핸들러 교체"""
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')
        if today != self.current_date:
            self._update_file_handler()

    def info(self, msg, *args, **kwargs):
        self._check_date()
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._check_date()
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._check_date()
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._check_date()
        self._logger.debug(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._check_date()
        self._logger.exception(msg, *args, **kwargs)


# 하위 호환성을 위한 래퍼
class DailyLogHandler:
    """일별 로그 파일 관리 (하위 호환성)"""

    def __init__(self, prefix: str, logs_dir: str = 'logs'):
        self.daily_logger = DailyRotatingLogger(prefix, logs_dir)

    def get_logger(self) -> DailyRotatingLogger:
        """로거 반환"""
        return self.daily_logger


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
    config_btc.txt 변경 감지
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
    logger.info(f"BTCUSDC Grid Martingale Live Trading 시작")
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
        asyncio.create_task(config_reload_task(strategy, interval=60)),
        asyncio.create_task(strategy.order_verify_worker())  # 주문 검증 워커
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

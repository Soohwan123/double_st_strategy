#!/usr/bin/env python3
"""
Hyper Scalper V2 Live Trading
BTC/USDT 15분봉 추세추종 자동매매 프로그램

실행: python trade_hyper.py
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
from hyper_strategy import HyperScalperStrategy


# =============================================================================
# 상수
# =============================================================================

SYMBOL_TYPE = 'hyper'
SYMBOL = Config.get_symbol(SYMBOL_TYPE)  # 'BTCUSDT'


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
        self._logger.propagate = False
        os.makedirs(logs_dir, exist_ok=True)

        # 콘솔 핸들러
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

            if self.file_handler:
                self._logger.removeHandler(self.file_handler)
                self.file_handler.close()

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


# 전역 로그 핸들러
log_handler = DailyRotatingLogger(Config.get_log_prefix(SYMBOL_TYPE), Config.LOGS_DIR)


# =============================================================================
# 웹소켓 핸들러
# =============================================================================

async def websocket_handler(strategy: HyperScalperStrategy):
    """
    웹소켓 스트림 핸들러 (15분봉 + aggTrade)

    1. 15분봉 마감 시 신호 체크 → 진입
    2. 틱데이터로 TP/SL 체결 감지
    """
    logger = log_handler
    stream_url = Config.get_ws_stream_url_15m(SYMBOL_TYPE)

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info(f"웹소켓 연결: {SYMBOL} (15분봉)")

                while True:
                    message = await ws.recv()
                    data = json.loads(message)

                    if 'data' not in data:
                        continue

                    stream_data = data['data']

                    # 15분봉 데이터
                    if 'k' in stream_data:
                        kline = stream_data['k']
                        await strategy.on_candle_close(kline)

                    # 틱데이터 (aggTrade)
                    elif 'p' in stream_data and 'q' in stream_data:
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

async def position_sync_task(strategy: HyperScalperStrategy, interval: int = 30):
    """
    바이낸스 포지션과 주기적 동기화
    예상치 못한 청산 감지
    """
    logger = log_handler

    while True:
        try:
            await asyncio.sleep(interval)

            # 바이낸스 실제 포지션 확인
            pos_info = await strategy.binance.get_position_info()

            if strategy.position.has_position() and pos_info is None:
                # 로컬에는 포지션 있는데 바이낸스에는 없음
                logger.warning("예상치 못한 포지션 청산 감지!")

                # 마지막 거래 PnL 조회 시도
                pnl_data = await strategy.binance.get_last_closed_trade_pnl()

                if pnl_data and pnl_data['net_pnl'] != 0:
                    net_pnl = pnl_data['net_pnl']
                    old_capital = strategy.capital
                    strategy.capital += net_pnl
                    logger.warning(f"자본금 업데이트: ${old_capital:.2f} → ${strategy.capital:.2f} (PnL: ${net_pnl:.2f})")

                # 포지션 초기화
                strategy.position.reset()
                strategy._save_state()

        except Exception as e:
            logger.error(f"포지션 동기화 에러: {e}")


# =============================================================================
# 설정 리로드 태스크
# =============================================================================

async def config_reload_task(strategy: HyperScalperStrategy, interval: int = 60):
    """
    동적 설정 주기적 리로드
    config_hyper.txt 변경 감지
    """
    logger = log_handler

    while True:
        try:
            await asyncio.sleep(interval)

            if strategy.dynamic_config.reload():
                logger.info("설정 파일 변경 감지, 리로드 완료")

        except Exception as e:
            logger.error(f"설정 리로드 에러: {e}")


# =============================================================================
# 상태 로깅 태스크
# =============================================================================

async def status_log_task(strategy: HyperScalperStrategy, interval: int = 300):
    """
    주기적 상태 로깅 (5분마다)
    """
    logger = log_handler

    while True:
        try:
            await asyncio.sleep(interval)

            # 현재 상태 로깅
            if strategy.position.has_position():
                current_price = await strategy.binance.get_current_price()
                if current_price:
                    unrealized_pnl = strategy._calculate_pnl(current_price)
                    logger.info(
                        f"[상태] 포지션: {strategy.position.direction}, "
                        f"진입가: ${strategy.position.entry_price:.2f}, "
                        f"현재가: ${current_price:.2f}, "
                        f"미실현PnL: ${unrealized_pnl:.2f}"
                    )
            else:
                logger.info(f"[상태] 포지션 없음, 자본금: ${strategy.capital:.2f}")

            # 지표 상태
            indicators = strategy.candle_manager.get_latest_indicators()
            if indicators:
                logger.info(
                    f"[지표] ADX={indicators['adx']:.1f}, "
                    f"Bull={indicators['bull_trend']}, Bear={indicators['bear_trend']}"
                )

        except Exception as e:
            logger.error(f"상태 로깅 에러: {e}")


# =============================================================================
# 메인
# =============================================================================

async def main():
    """메인 실행 함수"""
    logger = log_handler

    logger.info("=" * 70)
    logger.info("Hyper Scalper V2 Live Trading 시작")
    logger.info(f"심볼: {SYMBOL}, 타임프레임: 15m")
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
    strategy = HyperScalperStrategy(
        binance=binance,
        symbol_type=SYMBOL_TYPE,
        logger=logger
    )

    # 초기화
    await strategy.initialize()

    # 과거 데이터 로드
    await strategy.load_historical_data()

    # 태스크 시작
    tasks = [
        asyncio.create_task(websocket_handler(strategy)),
        asyncio.create_task(position_sync_task(strategy, interval=30)),
        asyncio.create_task(config_reload_task(strategy, interval=60)),
        asyncio.create_task(status_log_task(strategy, interval=300))
    ]

    logger.info("모든 태스크 시작 완료")
    logger.info(f"초기 자본금: ${strategy.capital:.2f}")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("태스크 취소됨")
    finally:
        for task in tasks:
            task.cancel()

        logger.info("프로그램 종료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n프로그램 종료 (Ctrl+C)")

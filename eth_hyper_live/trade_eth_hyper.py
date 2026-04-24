#!/usr/bin/env python3
"""
ETH Hyper Scalper Live Trading
ETH/USDT 15분봉 추세추종 자동매매 프로그램

실행: python trade_eth_hyper.py
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
import sys as _sys
_sys.path.insert(0, '/home/double_st_strategy/price_feed')
from ipc_client import IPCSubscriber

from config import Config, DynamicConfig
from binance_library import BinanceFuturesClient
from eth_hyper_strategy import EthHyperStrategy


# =============================================================================
# 상수
# =============================================================================

SYMBOL_TYPE = 'eth_hyper'
SYMBOL = Config.get_symbol(SYMBOL_TYPE)


# =============================================================================
# 로깅 설정
# =============================================================================

class DailyRotatingLogger:
    """일별 로그 파일 자동 교체 로거"""

    def __init__(self, prefix: str, logs_dir: str = 'logs'):
        self.prefix = prefix
        self.logs_dir = logs_dir
        self.current_date = None
        self.file_handler = None
        self._logger = logging.getLogger(f'{prefix}_daily')
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        os.makedirs(logs_dir, exist_ok=True)

        if not any(isinstance(h, logging.StreamHandler) for h in self._logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self._logger.addHandler(console_handler)

        self._update_file_handler()

    def _update_file_handler(self):
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


# === WebSocket 끊김/재연결 Telegram 알림 (한번씩만 전송) ===
_TG_TOKEN = "8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
_TG_CHAT_ID = "8084935783"

def _send_telegram_alert(text: str):
    """Fire-and-forget Telegram 알림 (blocking 방지)"""
    import threading, urllib.request, urllib.parse, socket as _sk
    host = _sk.gethostname()
    msg = text + " | Host: " + host
    def _send():
        try:
            url = "https://api.telegram.org/bot" + _TG_TOKEN + "/sendMessage"
            data = urllib.parse.urlencode({"chat_id": _TG_CHAT_ID, "text": msg}).encode()
            urllib.request.urlopen(url, data=data, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


log_handler = DailyRotatingLogger(Config.get_log_prefix(SYMBOL_TYPE), Config.LOGS_DIR)


# =============================================================================
# 웹소켓 핸들러
# =============================================================================


# =============================================================================
# IPC Subscriber (price_feed 로부터 시세 수신) — websocket_handler 를 대체
# =============================================================================

async def ipc_subscriber_task(strategy):
    """price_feed 의 ZMQ PUB 에서 ETHUSDT 시세 수신 → strategy 에 전달"""
    subscriber = IPCSubscriber(
        symbol="ETHUSDT",
        on_kline_15m=strategy.on_candle_close,
        on_kline_1h=None,
        on_tick=strategy.on_tick,
        logger=log_handler,
        send_alert=_send_telegram_alert,
    )
    await subscriber.run()


async def websocket_handler(strategy: EthHyperStrategy):
    """웹소켓 스트림 핸들러 (15분봉 + aggTrade)"""
    logger = log_handler
    stream_url = Config.get_ws_stream_url_15m(SYMBOL_TYPE)
    RECV_TIMEOUT = 90  # 90초 무수신 시 heartbeat 실패로 간주 → 강제 재연결 (aggTrade 시장 조용할때 1-2분 공백 가능)
    ws_alerted_down = False  # Telegram 중복 알림 방지 (재연결 시 False 로 리셋)
    backoff_delay = 5  # Reconnect 간격. 실패 시 exponential, 성공 시 리셋

    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info(f"웹소켓 연결: {SYMBOL} (15분봉)")
                backoff_delay = 5  # 성공 연결 시 backoff 초기화
                if ws_alerted_down:
                    _send_telegram_alert("🟢 [" + SYMBOL_TYPE + "] WebSocket 재연결 복구")
                    ws_alerted_down = False
                while True:
                    message = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                    data = json.loads(message)

                    if 'data' not in data:
                        continue

                    stream_data = data['data']

                    if 'k' in stream_data:
                        kline = stream_data['k']
                        await strategy.on_candle_close(kline)

                    elif 'p' in stream_data and 'q' in stream_data:
                        price = float(stream_data['p'])
                        await strategy.on_tick(price)

        except asyncio.TimeoutError:
            logger.warning(f"웹소켓 {RECV_TIMEOUT}s 무수신 - heartbeat 실패, 강제 재연결")
            if not ws_alerted_down:
                _send_telegram_alert("🔴 [" + SYMBOL_TYPE + "] WebSocket heartbeat 실패 (90s 무수신)")
                ws_alerted_down = True
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, 300)  # 5→10→20→40→80→160→300 (max 5분)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("웹소켓 연결 종료, 재연결 중...")
            if not ws_alerted_down:
                _send_telegram_alert("🔴 [" + SYMBOL_TYPE + "] WebSocket 연결 종료")
                ws_alerted_down = True
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, 300)  # 5→10→20→40→80→160→300 (max 5분)

        except Exception as e:
            logger.error(f"웹소켓 에러: {e}")
            if not ws_alerted_down:
                _send_telegram_alert("🔴 [" + SYMBOL_TYPE + "] WebSocket 에러: " + str(e))
                ws_alerted_down = True
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, 300)  # 5→10→20→40→80→160→300 (max 5분)


# =============================================================================
# 포지션 동기화 태스크
# =============================================================================

async def position_sync_task(strategy: EthHyperStrategy, interval: int = 30):
    logger = log_handler

    while True:
        try:
            await asyncio.sleep(interval)

            # DRY 모드: binance 조회 불필요
            if strategy.is_dry_run():
                continue

            pos_info = await strategy.binance.get_position_info()

            if strategy.position.has_position() and pos_info is None:
                logger.warning("포지션 사라짐 감지! TP/SL 주문 상태 확인 중...")

                exit_type = None
                exit_price = None

                # TP 주문 체결 확인
                if strategy.position.tp_order_id:
                    try:
                        tp_status = await strategy.binance.get_order_status(strategy.position.tp_order_id)
                        if tp_status and tp_status.get('status') == 'FILLED':
                            exit_type = 'TP'
                            exit_price = strategy.position.take_profit
                            logger.info(f"TP 주문 체결 확인: ID={strategy.position.tp_order_id}")
                    except Exception as e:
                        logger.warning(f"TP 주문 상태 조회 실패: {e}")

                # SL 주문 체결 확인
                if exit_type is None and strategy.position.sl_order_id:
                    try:
                        sl_status = await strategy.binance.get_order_status(strategy.position.sl_order_id)
                        if sl_status and sl_status.get('status') == 'FILLED':
                            exit_type = 'SL'
                            exit_price = strategy.position.stop_loss
                            logger.info(f"SL 주문 체결 확인: ID={strategy.position.sl_order_id}")
                    except Exception as e:
                        logger.warning(f"SL 주문 상태 조회 실패: {e}")

                # TP/SL 확인 성공 시 해당 핸들러 호출
                if exit_type == 'TP' and exit_price:
                    await strategy.on_tp_filled(exit_price)
                elif exit_type == 'SL' and exit_price:
                    await strategy.on_sl_filled(exit_price)
                else:
                    # 둘 다 확인 안 되면 fallback (API PnL 조회)
                    logger.warning("TP/SL 주문 상태 확인 불가 — fallback PnL 조회")
                    pnl_data = await strategy.binance.get_last_closed_trade_pnl()

                    if pnl_data and pnl_data['net_pnl'] != 0:
                        net_pnl = pnl_data['net_pnl']
                        old_capital = strategy.capital
                        strategy.capital += net_pnl
                        logger.warning(f"자본금 업데이트: ${old_capital:.2f} → ${strategy.capital:.2f} (PnL: ${net_pnl:.2f})")

                    strategy.position.reset()
                    strategy._save_state()

        except Exception as e:
            logger.error(f"포지션 동기화 에러: {e}")


# =============================================================================
# 설정 리로드 태스크
# =============================================================================

async def config_reload_task(strategy: EthHyperStrategy, interval: int = 60):
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

async def status_log_task(strategy: EthHyperStrategy, interval: int = 300):
    logger = log_handler

    while True:
        try:
            await asyncio.sleep(interval)

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
    logger = log_handler

    logger.info("=" * 70)
    logger.info("ETH Hyper Scalper Live Trading 시작")
    logger.info(f"심볼: {SYMBOL}, 타임프레임: 15m")
    logger.info("=" * 70)

    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        sys.exit(1)

    client = Client(Config.API_KEY, Config.API_SECRET)

    binance = BinanceFuturesClient(
        client=client,
        symbol=SYMBOL,
        logger=logger,
        dry_run=False,
        price_precision=Config.get_price_precision(SYMBOL_TYPE),
        qty_precision=Config.get_qty_precision(SYMBOL_TYPE)
    )

    strategy = EthHyperStrategy(
        binance=binance,
        symbol_type=SYMBOL_TYPE,
        logger=logger
    )

    await strategy.initialize()
    await strategy.load_historical_data()

    tasks = [
        asyncio.create_task(ipc_subscriber_task(strategy)),
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

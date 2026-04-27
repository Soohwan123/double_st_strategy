#!/usr/bin/env python3
"""OB Retest Live Trading — SOLUSDT 5m bt_09 (hyper_v2 sub account)"""

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
from ob_strategy import ObStrategy

SYMBOL_TYPE = 'ob_sol'
SYMBOL = Config.get_symbol(SYMBOL_TYPE)


class DailyRotatingLogger:
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
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self._logger.addHandler(ch)
        self._update_file_handler()

    def _update_file_handler(self):
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')
        if today != self.current_date:
            self.current_date = today
            fn = f'{self.logs_dir}/{self.prefix}_{today}.log'
            if self.file_handler:
                self._logger.removeHandler(self.file_handler)
                self.file_handler.close()
            self.file_handler = logging.FileHandler(fn)
            self.file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self._logger.addHandler(self.file_handler)
            self._logger.info(f"=== 로그 파일 시작: {fn} ===")

    def _check_date(self):
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')
        if today != self.current_date:
            self._update_file_handler()

    def info(self, msg, *a, **kw): self._check_date(); self._logger.info(msg, *a, **kw)
    def warning(self, msg, *a, **kw): self._check_date(); self._logger.warning(msg, *a, **kw)
    def error(self, msg, *a, **kw): self._check_date(); self._logger.error(msg, *a, **kw)
    def debug(self, msg, *a, **kw): self._check_date(); self._logger.debug(msg, *a, **kw)
    def exception(self, msg, *a, **kw): self._check_date(); self._logger.exception(msg, *a, **kw)


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
# IPC Subscriber (price_feed 로부터 시세 수신) — websocket_handler 를 대체
# =============================================================================

async def ipc_subscriber_task(strategy):
    """price_feed 의 ZMQ PUB 에서 SOLUSDT 시세 수신 → strategy 에 전달.

    bt_09 OB swap (5m, HTF on): kline_5m + trade 만 구독, kline_1h 구독 X.
    """
    subscriber = IPCSubscriber(
        symbol="SOLUSDT",
        on_kline_main=strategy.on_candle_close,   # 5m kline
        on_kline_1h=strategy.on_htf_kline,         # HTF 1h EMA200 (bt_09 use_htf=True)
        on_tick=strategy.on_tick,
        kline_interval='5m',                       # bt_09 = 5m
        logger=log_handler,
        send_alert=_send_telegram_alert,
    )
    await subscriber.run()


async def websocket_handler(strategy: ObStrategy):
    logger = log_handler
    stream_url = Config.get_ws_stream_url_15m(SYMBOL_TYPE)
    RECV_TIMEOUT = 90  # 90초 무수신 시 heartbeat 실패로 간주 → 강제 재연결 (aggTrade 시장 조용할때 1-2분 공백 가능)
    ws_alerted_down = False  # Telegram 중복 알림 방지 (재연결 시 False 로 리셋)
    backoff_delay = 5  # Reconnect 간격. 실패 시 exponential, 성공 시 리셋
    while True:
        try:
            async with websockets.connect(stream_url) as ws:
                logger.info(f"웹소켓 연결: {SYMBOL} (15m + 1h + aggTrade)")
                backoff_delay = 5  # 성공 연결 시 backoff 초기화
                if ws_alerted_down:
                    _send_telegram_alert("🟢 [" + SYMBOL_TYPE + "] WebSocket 재연결 복구")
                    ws_alerted_down = False
                while True:
                    message = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                    data = json.loads(message)
                    if 'data' not in data:
                        continue
                    stream_name = data.get('stream', '')
                    stream_data = data['data']
                    if 'k' in stream_data:
                        kline = stream_data['k']
                        interval = kline.get('i', '')
                        if interval == '1h':
                            await strategy.on_htf_kline(kline)
                        else:  # 15m
                            await strategy.on_candle_close(kline)
                    elif 'p' in stream_data and 'q' in stream_data:
                        await strategy.on_tick(float(stream_data['p']))
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


async def position_sync_task(strategy: ObStrategy, interval: int = 30):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)

            if strategy.is_dry_run():
                continue

            if strategy.position.is_virtual:
                continue

            pos_info = await strategy.binance.get_position_info()

            if strategy.position.has_position() and pos_info is None:
                logger.warning("포지션 사라짐 감지! TP/SL 주문 상태 확인 중...")
                exit_type = None
                exit_price = None

                if strategy.position.tp_order_id:
                    try:
                        tp_st = await strategy.binance.get_order_status(strategy.position.tp_order_id)
                        if tp_st and tp_st.get('status') == 'FILLED':
                            exit_type = 'TP'
                            exit_price = strategy.position.take_profit
                    except Exception as e:
                        logger.warning(f"TP 조회 실패: {e}")

                if exit_type is None and strategy.position.sl_order_id:
                    try:
                        sl_st = await strategy.binance.get_order_status(strategy.position.sl_order_id)
                        if sl_st and sl_st.get('status') == 'FILLED':
                            exit_type = 'SL'
                            exit_price = strategy.position.stop_loss
                    except Exception as e:
                        logger.warning(f"SL 조회 실패: {e}")

                if exit_type == 'TP' and exit_price:
                    await strategy.on_tp_filled(exit_price)
                elif exit_type == 'SL' and exit_price:
                    await strategy.on_sl_filled(exit_price)
                else:
                    logger.warning("TP/SL 확인 불가 — fallback PnL 조회")
                    pnl_data = await strategy.binance.get_last_closed_trade_pnl()
                    if pnl_data and pnl_data['net_pnl'] != 0:
                        net_pnl = pnl_data['net_pnl']
                        old = strategy.capital
                        strategy.capital += net_pnl
                        logger.warning(f"자본금: ${old:.2f} → ${strategy.capital:.2f} (PnL: ${net_pnl:.2f})")
                    strategy.position.reset()
                    strategy._save_state()

            if strategy.position.has_pending() and not strategy.position.has_position():
                await strategy._check_pending_fill()

        except Exception as e:
            logger.error(f"포지션 동기화 에러: {e}")


async def config_reload_task(strategy: ObStrategy, interval: int = 60):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)
            if strategy.dynamic_config.reload():
                logger.info("설정 파일 변경 감지, 리로드 완료")
        except Exception as e:
            logger.error(f"설정 리로드 에러: {e}")


async def status_log_task(strategy: ObStrategy, interval: int = 300):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)
            pp = Config.get_price_precision(SYMBOL_TYPE)
            if strategy.position.has_position():
                tag = "[가상]" if strategy.position.is_virtual else "[실제]"
                price = await strategy.binance.get_current_price()
                if price:
                    if strategy.position.direction == 'LONG':
                        upnl = (price - strategy.position.entry_price) * strategy.position.entry_size
                    else:
                        upnl = (strategy.position.entry_price - price) * strategy.position.entry_size
                    notional = strategy.position.entry_price * strategy.position.entry_size
                    roi = (upnl / notional * 100) if notional > 0 else 0.0
                    logger.info(f"[상태] {tag} {strategy.position.direction} @ ${strategy.position.entry_price:.{pp}f}, 현재=${price:.{pp}f}, TP=${strategy.position.take_profit:.{pp}f}, SL=${strategy.position.stop_loss:.{pp}f}, uPnL=${upnl:+.2f} ({roi:+.2f}%)")
            elif strategy.position.has_pending():
                logger.info(f"[상태] 대기중: {strategy.position.pending_direction} @ ${strategy.position.pending_entry_price:.{pp}f}, 자본=${strategy.capital:.2f}")
            else:
                logger.info(f"[상태] 포지션 없음, 자본=${strategy.capital:.2f}, LONG큐={len(strategy.long_queue)}, SHORT큐={len(strategy.short_queue)}")

            htf = strategy.candle_manager.get_htf_filter()
            logger.info(f"[HTF] bull={htf['bull']}, bear={htf['bear']}")
        except Exception as e:
            logger.error(f"상태 로깅 에러: {e}")


async def main():
    logger = log_handler
    logger.info("=" * 70)
    logger.info(f"FVG Retest Live Trading 시작 ({SYMBOL})")
    logger.info("=" * 70)

    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        sys.exit(1)

    client = Client(Config.API_KEY, Config.API_SECRET)
    binance = BinanceFuturesClient(
        client=client, symbol=SYMBOL, logger=logger,
        dry_run=False,
        price_precision=Config.get_price_precision(SYMBOL_TYPE),
        qty_precision=Config.get_qty_precision(SYMBOL_TYPE)
    )

    strategy = ObStrategy(binance=binance, symbol_type=SYMBOL_TYPE, logger=logger)
    await strategy.initialize()
    await strategy.load_historical_data()

    tasks = [
        asyncio.create_task(ipc_subscriber_task(strategy)),
        asyncio.create_task(position_sync_task(strategy, interval=30)),
        asyncio.create_task(config_reload_task(strategy, interval=60)),
        asyncio.create_task(status_log_task(strategy, interval=300))
    ]

    logger.info(f"모든 태스크 시작, 초기 자본금: ${strategy.capital:.2f}")

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

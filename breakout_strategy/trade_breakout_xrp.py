#!/usr/bin/env python3
"""Breakout Live Trading — XRPUSDT 5m bt_03 v4 best (Hyper 부계정)"""

import asyncio
import json
import os
import sys
import logging
from datetime import datetime
import pytz
from binance.client import Client
import sys as _sys
_sys.path.insert(0, '/home/double_st_strategy/price_feed')
from ipc_client import IPCSubscriber

from config import Config, DynamicConfig
from binance_library import BinanceFuturesClient
from breakout_strategy import BreakoutStrategy

SYMBOL_TYPE = 'breakout_xrp'
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


_TG_TOKEN = "8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
_TG_CHAT_ID = "8084935783"

def _send_telegram_alert(text: str):
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


async def ipc_subscriber_task(strategy):
    """price_feed 의 ZMQ PUB 에서 XRPUSDT 시세 수신.
    bt_03 v4 best: kline_5m + trade. HTF 안 씀.
    """
    subscriber = IPCSubscriber(
        symbol=SYMBOL,
        on_kline_main=strategy.on_candle_close,
        on_kline_1h=None,
        on_tick=strategy.on_tick,
        kline_interval='5m',
        logger=log_handler,
        send_alert=_send_telegram_alert,
    )
    await subscriber.run()


async def position_sync_task(strategy: BreakoutStrategy, interval: int = 30):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)
            if strategy.is_dry_run():
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
                    logger.warning("TP/SL 확인 불가 — actual PnL 조회 (entry_order_id + startTime, XRPUSDT 만)")
                    pnl_data = None
                    if strategy.position.entry_order_id and strategy.position.entry_time_ms:
                        pnl_data = await strategy.binance.get_actual_trade_pnl(
                            entry_order_id=strategy.position.entry_order_id,
                            entry_time_ms=strategy.position.entry_time_ms,
                        )
                    if pnl_data and pnl_data.get('net_pnl', 0) != 0:
                        net_pnl = pnl_data['net_pnl']
                        old = strategy.capital
                        strategy.capital += net_pnl
                        if net_pnl > 0:
                            fb_reason = 'TP'
                            fb_exit_price = strategy.position.take_profit
                        else:
                            fb_reason = 'SL'
                            fb_exit_price = strategy.position.stop_loss
                        strategy._record_trade(fb_exit_price, fb_reason, net_pnl)
                        logger.warning(
                            f"[actual PnL] rpnl=${pnl_data['realized_pnl']:.2f} "
                            f"ent_fee=${pnl_data['entry_commission']:.2f} "
                            f"ext_fee=${pnl_data['exit_commission']:.2f} → net=${net_pnl:.2f}"
                        )
                        logger.warning(f"자본금: ${old:.2f} → ${strategy.capital:.2f} ({fb_reason} 기록)")
                    else:
                        logger.error(f"actual PnL 조회 실패 — 자본금 update 안 함 (entry_order_id={strategy.position.entry_order_id}, entry_time_ms={strategy.position.entry_time_ms})")
                    strategy.position.reset()
                    strategy._save_state()
        except Exception as e:
            logger.error(f"포지션 동기화 에러: {e}")


async def config_reload_task(strategy: BreakoutStrategy, interval: int = 60):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)
            if strategy.dynamic_config.reload():
                logger.info("설정 파일 변경 감지, 리로드 완료")
        except Exception as e:
            logger.error(f"설정 리로드 에러: {e}")


async def status_log_task(strategy: BreakoutStrategy, interval: int = 300):
    logger = log_handler
    while True:
        try:
            await asyncio.sleep(interval)
            pp = Config.get_price_precision(SYMBOL_TYPE)
            if strategy.position.has_position():
                price = await strategy.binance.get_current_price()
                if price:
                    if strategy.position.direction == 'LONG':
                        upnl = (price - strategy.position.entry_price) * strategy.position.entry_size
                    else:
                        upnl = (strategy.position.entry_price - price) * strategy.position.entry_size
                    notional = strategy.position.entry_price * strategy.position.entry_size
                    roi = (upnl / notional * 100) if notional > 0 else 0.0
                    logger.info(
                        f"[상태] {strategy.position.direction} @ ${strategy.position.entry_price:.{pp}f}, "
                        f"현재=${price:.{pp}f}, TP=${strategy.position.take_profit:.{pp}f}, "
                        f"SL=${strategy.position.stop_loss:.{pp}f}, uPnL=${upnl:+.2f} ({roi:+.2f}%)"
                    )
            else:
                logger.info(f"[상태] 포지션 없음, 자본=${strategy.capital:.2f}, candles={strategy.candle_manager.get_candle_count()}")
            th = strategy.candle_manager.get_thresholds()
            logger.info(
                f"[Trendline] upper={th['upper']}, lower={th['lower']}, "
                f"upos={th['upos']}, dnos={th['dnos']}, atr={th['atr']}"
            )
        except Exception as e:
            logger.error(f"상태 로깅 에러: {e}")


async def main():
    logger = log_handler
    logger.info("=" * 70)
    logger.info(f"Breakout Live Trading 시작 ({SYMBOL}) — bt_03 v4 best")
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
    strategy = BreakoutStrategy(binance=binance, symbol_type=SYMBOL_TYPE, logger=logger)
    await strategy.initialize()
    await strategy.load_historical_data()
    tasks = [
        asyncio.create_task(ipc_subscriber_task(strategy)),
        asyncio.create_task(position_sync_task(strategy, interval=30)),
        asyncio.create_task(config_reload_task(strategy, interval=60)),
        asyncio.create_task(status_log_task(strategy, interval=300)),
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

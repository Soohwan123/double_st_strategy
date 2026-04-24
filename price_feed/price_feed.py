#!/usr/bin/env python3
"""
Unified Binance price feed (Hybrid: WS trade + REST kline polling).

Binance 의 **kline / aggTrade / markPrice** 스트림이 silent drop 상황 (2026-04-24,
여러 IP 에서 재현됨, trade 만 정상) 에 대응하기 위해:

- **WS**: `trade` 스트림만 구독 (틱 price 용, 현재 정상 작동)
- **REST**: 각 (symbol, interval) 쌍에 대해 바 마감 경계에서 polling.
  - 경계 직후 +0s, +5s, +10s 에 최대 3회 시도
  - 중복 방지: `last_published_open_time` 체크
  - 닫힌 바를 WS kline 메시지와 **동일 포맷** (`k` 오브젝트) 으로 변환해 ZMQ publish

전략들은 WS/REST 여부 모르고 동일 방식으로 ipc_client 에서 수신.

ZMQ Topic:
  "{SYMBOL}.kline_15m" / "{SYMBOL}.kline_1h" / "{SYMBOL}.trade"
Payload:
  Binance 'k' 오브젝트 JSON (kline) or raw trade JSON
"""
import asyncio
import json
import logging
import os
import socket as _sk
import threading
import urllib.parse
import urllib.request
from datetime import datetime

import pytz
import websockets
import websockets.exceptions
import zmq
import zmq.asyncio


# =============================================================================
# 설정
# =============================================================================

SYMBOLS = ["BTCUSDT", "BTCUSDC", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVALS = [("15m", 900), ("1h", 3600)]  # (interval_str, seconds)
PUB_ADDR = "tcp://127.0.0.1:5555"
WS_RECV_TIMEOUT = 90
LOGS_DIR = "/home/double_st_strategy/price_feed/logs"

# REST polling 재시도 offset (바 마감 이후 초 단위)
REST_POLL_OFFSETS = [0, 5, 10]

# Telegram
_TG_TOKEN = "8585666858:AAG2nhq8IEDbjWxoQCLAcOpUjCwiSEdSFF4"
_TG_CHAT_ID = "8084935783"


# =============================================================================
# Telegram
# =============================================================================

def _send_telegram_alert(text: str):
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


# =============================================================================
# Logger
# =============================================================================

class DailyRotatingLogger:
    def __init__(self, prefix: str, logs_dir: str):
        self.prefix = prefix
        self.logs_dir = logs_dir
        self.current_date = None
        self.file_handler = None
        self._logger = logging.getLogger(f"{prefix}_daily")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        os.makedirs(logs_dir, exist_ok=True)
        if not any(isinstance(h, logging.StreamHandler) for h in self._logger.handlers):
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self._logger.addHandler(ch)
        self._update_file_handler()

    def _update_file_handler(self):
        today = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
        if today != self.current_date:
            self.current_date = today
            fn = f"{self.logs_dir}/price_feed_{today}.log"
            if self.file_handler:
                self._logger.removeHandler(self.file_handler)
                self.file_handler.close()
            self.file_handler = logging.FileHandler(fn)
            self.file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self._logger.addHandler(self.file_handler)
            self._logger.info(f"=== 로그 파일 시작: {fn} ===")

    def _check(self):
        today = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
        if today != self.current_date:
            self._update_file_handler()

    def info(self, msg, *a, **kw): self._check(); self._logger.info(msg, *a, **kw)
    def warning(self, msg, *a, **kw): self._check(); self._logger.warning(msg, *a, **kw)
    def error(self, msg, *a, **kw): self._check(); self._logger.error(msg, *a, **kw)


logger = DailyRotatingLogger("price_feed", LOGS_DIR)


# =============================================================================
# 공유 state: 중복 publish 방지용
# =============================================================================

# key: (symbol, interval) → 마지막 publish 한 bar 의 open_time(ms)
last_published_bar = {}


# =============================================================================
# WS trade stream 루프
# =============================================================================

def build_trade_ws_url(symbols):
    parts = [f"{s.lower()}@trade" for s in symbols]
    return "wss://fstream.binance.com/stream?streams=" + "/".join(parts)


async def ws_trade_loop(pub):
    ws_url = build_trade_ws_url(SYMBOLS)
    logger.info(f"WS trade streams: {len(SYMBOLS)} symbols")

    ws_alerted_down = False
    backoff = 5
    msg_count = 0
    last_stats = asyncio.get_event_loop().time()

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("WS 연결 완료 (trade streams)")
                backoff = 5
                if ws_alerted_down:
                    _send_telegram_alert("🟢 [price_feed] WS trade 재연결 복구")
                    ws_alerted_down = False

                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_RECV_TIMEOUT)
                    data = json.loads(raw)
                    if "data" not in data or "stream" not in data:
                        continue
                    stream_name = data["stream"]
                    inner = data["data"]
                    try:
                        sym_part, stype = stream_name.split("@")
                        symbol = sym_part.upper()
                    except Exception:
                        continue

                    if stype == "trade":
                        topic = f"{symbol}.trade".encode()
                        payload = json.dumps(inner).encode()
                        await pub.send_multipart([topic, payload])
                        msg_count += 1

                    now = asyncio.get_event_loop().time()
                    if now - last_stats >= 300:
                        logger.info(f"[WS STATS] 지난 5분간 trade {msg_count} 메시지")
                        msg_count = 0
                        last_stats = now

        except asyncio.TimeoutError:
            logger.warning(f"WS {WS_RECV_TIMEOUT}s 무수신 - 재연결")
            if not ws_alerted_down:
                _send_telegram_alert(f"🔴 [price_feed] WS trade heartbeat 실패 ({WS_RECV_TIMEOUT}s)")
                ws_alerted_down = True
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WS 연결 종료, 재연결")
            if not ws_alerted_down:
                _send_telegram_alert("🔴 [price_feed] WS trade 연결 종료")
                ws_alerted_down = True
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except Exception as e:
            logger.error(f"WS 에러: {e}")
            if not ws_alerted_down:
                _send_telegram_alert(f"🔴 [price_feed] WS 에러: {e}")
                ws_alerted_down = True
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)


# =============================================================================
# REST kline polling
# =============================================================================

def _fetch_klines_sync(symbol: str, interval: str, limit: int = 2):
    """동기 HTTP fetch (asyncio.to_thread 에서 호출)"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def kline_array_to_k_obj(arr, interval, symbol):
    """
    Binance REST kline array → WS 'k' 오브젝트 포맷 변환.
    전략들이 `kline['x']`, `kline['t']`, `kline['o']` 등 access 해야 하므로 동일 필드 생성.
    """
    return {
        "t": arr[0],           # open_time (ms)
        "T": arr[6],           # close_time (ms)
        "s": symbol,
        "i": interval,
        "o": arr[1],           # open (string)
        "h": arr[2],           # high
        "l": arr[3],           # low
        "c": arr[4],           # close
        "v": arr[5],           # volume
        "x": True,             # closed (REST 로 가져온 닫힌 바)
        "q": arr[7] if len(arr) > 7 else "0",   # quote asset vol
        "n": arr[8] if len(arr) > 8 else 0,     # number of trades
        "V": arr[9] if len(arr) > 9 else "0",
        "Q": arr[10] if len(arr) > 10 else "0",
    }


async def poll_kline_loop(symbol: str, interval: str, interval_seconds: int, pub):
    """
    각 (symbol, interval) 마다 독립 태스크.
    매 bar 마감 시각에 ±0s, +5s, +10s 간격으로 REST polling.
    """
    key = (symbol, interval)
    topic_str = f"{symbol}.kline_{interval}"
    topic = topic_str.encode()

    logger.info(f"[REST POLL] 태스크 시작: {symbol} {interval}")

    while True:
        try:
            # 다음 bar close 시각 계산 (UTC 기준 interval 경계)
            now = asyncio.get_event_loop().time()
            now_real = int(__import__('time').time())
            next_close = ((now_real // interval_seconds) + 1) * interval_seconds
            wait = max(0, next_close - now_real)
            await asyncio.sleep(wait)  # bar close 시각까지 대기

            # 3회 재시도 (+0s, +5s, +10s)
            published_this_round = False
            for offset in REST_POLL_OFFSETS:
                if offset > 0:
                    await asyncio.sleep(5)
                if published_this_round:
                    break

                try:
                    # REST fetch (blocking → thread 에서)
                    klines = await asyncio.to_thread(_fetch_klines_sync, symbol, interval, 2)
                    if not klines or len(klines) < 1:
                        continue

                    # 가장 최근 닫힌 bar 찾기
                    # Binance 는 limit=2 로 요청 시 [이전 닫힌 바, 현재 진행 중 바] 반환
                    # close_time 이 now_real*1000 보다 작으면 닫힌 바
                    now_ms = int(__import__('time').time() * 1000)
                    closed_bar = None
                    for kline_arr in reversed(klines):
                        if kline_arr[6] < now_ms:  # close_time < now → 닫힘
                            closed_bar = kline_arr
                            break
                    if closed_bar is None:
                        continue

                    open_time = closed_bar[0]
                    last_ot = last_published_bar.get(key, 0)
                    if open_time <= last_ot:
                        # 이미 publish 한 바
                        published_this_round = True
                        break

                    # Publish
                    kline_obj = kline_array_to_k_obj(closed_bar, interval, symbol)
                    await pub.send_multipart([topic, json.dumps(kline_obj).encode()])
                    last_published_bar[key] = open_time
                    published_this_round = True

                    bar_ts = datetime.fromtimestamp(open_time / 1000, tz=pytz.UTC).strftime("%H:%M")
                    logger.info(
                        f"[REST BAR] {symbol} {interval} {bar_ts} "
                        f"O={closed_bar[1]} H={closed_bar[2]} L={closed_bar[3]} C={closed_bar[4]} "
                        f"(attempt {offset}s)"
                    )

                except Exception as e:
                    logger.warning(f"REST poll 실패 {symbol} {interval}: {e}")

            if not published_this_round:
                logger.error(
                    f"[REST BAR MISS] {symbol} {interval} — 3회 재시도 모두 실패 (새 bar 없음 or HTTP 에러)"
                )

        except Exception as e:
            logger.error(f"poll_kline_loop 에러 {symbol} {interval}: {e}")
            await asyncio.sleep(30)


# =============================================================================
# Main
# =============================================================================

async def main():
    ctx = zmq.asyncio.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(PUB_ADDR)
    logger.info(f"ZMQ PUB bound: {PUB_ADDR}")
    logger.info(f"Symbols: {SYMBOLS}")
    logger.info(f"Intervals (REST): {[i for i, _ in INTERVALS]}")
    logger.info(f"WS streams: trade only ({len(SYMBOLS)} symbols)")

    # Tasks
    tasks = [asyncio.create_task(ws_trade_loop(pub))]
    for symbol in SYMBOLS:
        for interval, seconds in INTERVALS:
            tasks.append(asyncio.create_task(
                poll_kline_loop(symbol, interval, seconds, pub)
            ))

    logger.info(f"태스크 시작: WS trade 1개 + REST poll {len(SYMBOLS)*len(INTERVALS)}개 = 총 {len(tasks)}개")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    pid_file = "/home/double_st_strategy/price_feed/state/price_feed.pid"
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    logger.info(f"=== price_feed 시작 (PID: {os.getpid()}) ===")
    _send_telegram_alert(f"🚀 [price_feed] 시작 (PID: {os.getpid()}) — Hybrid WS trade + REST kline polling")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("price_feed 종료")
    finally:
        try:
            os.remove(pid_file)
        except Exception:
            pass

"""
Strategy 에서 price_feed 의 데이터를 받기 위한 ZMQ SUB 클라이언트.

사용 예:
    from ipc_client import IPCSubscriber

    subscriber = IPCSubscriber(
        symbol="ETHUSDT",
        on_kline_15m=strategy.on_candle_close,  # async def on_candle_close(kline_dict): ...
        on_kline_1h=strategy.on_htf_kline,      # async def on_htf_kline(kline_dict): ...  (옵션)
        on_tick=strategy.on_tick,               # async def on_tick(price_float): ...     (옵션)
        logger=log_handler,
    )
    await subscriber.run()  # 무한 loop (websocket_handler 대체)

Protocol:
  Message: multipart [topic_bytes, payload_bytes]
  Topic:   "{SYMBOL}.{stream_type}" (예: "ETHUSDT.kline_15m")
  Payload: Binance raw JSON (kline obj / aggTrade obj)
"""
import asyncio
import json
import zmq
import zmq.asyncio

PRICE_FEED_ADDR = "tcp://127.0.0.1:5555"
RECV_TIMEOUT_SEC = 120  # IPC 에서 120초 미수신 시 price_feed 이상으로 판정


class IPCSubscriber:
    def __init__(self, symbol: str,
                 on_kline_15m=None, on_kline_1h=None, on_tick=None,
                 logger=None, send_alert=None):
        """
        symbol: 'ETHUSDT' 등 대문자 심볼
        on_kline_15m: async def handler(kline_dict) — Binance kline 'k' 오브젝트 전달
        on_kline_1h: async def handler(kline_dict) — 옵션 (HTF 사용하는 FVG 전략만)
        on_tick: async def handler(price_float) — aggTrade 의 가격 float
        logger: optional logger (info/warning/error 메서드)
        send_alert: optional callable(text) — Telegram 알림용
        """
        self.symbol = symbol.upper()
        self.on_kline_15m = on_kline_15m
        self.on_kline_1h = on_kline_1h
        self.on_tick = on_tick
        self.logger = logger
        self.send_alert = send_alert or (lambda _: None)
        self._alerted_down = False

    def _log(self, level, msg):
        if not self.logger:
            return
        fn = getattr(self.logger, level, None)
        if fn:
            fn(msg)

    async def run(self):
        backoff = 2
        while True:
            ctx = zmq.asyncio.Context.instance()
            sock = ctx.socket(zmq.SUB)
            try:
                sock.connect(PRICE_FEED_ADDR)

                # Subscribe to topics for this symbol
                topics = []
                if self.on_kline_15m:
                    topics.append(f"{self.symbol}.kline_15m")
                if self.on_kline_1h:
                    topics.append(f"{self.symbol}.kline_1h")
                if self.on_tick:
                    topics.append(f"{self.symbol}.trade")
                for t in topics:
                    sock.setsockopt(zmq.SUBSCRIBE, t.encode())

                self._log("info", f"IPC 구독 시작: {self.symbol} topics={topics} (feed={PRICE_FEED_ADDR})")
                if self._alerted_down:
                    self.send_alert(f"🟢 [{self.symbol}] IPC 재연결 복구")
                    self._alerted_down = False
                backoff = 2  # 성공 시 backoff 리셋

                while True:
                    try:
                        parts = await asyncio.wait_for(
                            sock.recv_multipart(), timeout=RECV_TIMEOUT_SEC
                        )
                    except asyncio.TimeoutError:
                        self._log("warning", f"IPC {RECV_TIMEOUT_SEC}s 무수신 - price_feed 이상? 재연결 시도")
                        if not self._alerted_down:
                            self.send_alert(f"🔴 [{self.symbol}] IPC heartbeat 실패 ({RECV_TIMEOUT_SEC}s 무수신)")
                            self._alerted_down = True
                        break  # outer loop 로 → reconnect

                    if len(parts) != 2:
                        continue
                    topic = parts[0].decode(errors="ignore")
                    try:
                        payload = json.loads(parts[1])
                    except Exception:
                        continue

                    # 라우팅
                    if topic.endswith(".kline_15m") and self.on_kline_15m:
                        await self.on_kline_15m(payload)
                    elif topic.endswith(".kline_1h") and self.on_kline_1h:
                        await self.on_kline_1h(payload)
                    elif topic.endswith(".trade") and self.on_tick:
                        try:
                            price = float(payload.get("p", 0))
                            if price > 0:
                                await self.on_tick(price)
                        except Exception:
                            pass

            except Exception as e:
                self._log("error", f"IPC 에러: {e}")
                if not self._alerted_down:
                    self.send_alert(f"🔴 [{self.symbol}] IPC 에러: {e}")
                    self._alerted_down = True
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

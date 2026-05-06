"""
Breakout Strategy (LuxAlgo Trendlines with Breaks)

진입 흐름:
  1. 봉 close (5m kline x=true) → candle_manager 갱신 + trendline state 업데이트
  2. get_breakout_signal() → LONG/SHORT/None
  3. signal 있으면:
       a. ATR(i) × SL_ATR_MULT 로 sl_dist 계산
       b. lev = clamp(RPT/(sl_pct + 2*TAKER), 1, MAX_LEV)
       c. MARKET 주문 (entry = c[i] 가정)
       d. fill 후 STOP_MARKET (SL) + LIMIT (TP) placement
  4. position_sync_task (30s) 가 SL/TP fill 감지

BT 매칭:
  - Entry 가격: BT 의 c[i] vs LIVE 시장가 fill (~slippage 0.01-0.05%)
  - SL/TP: ATR×배수 fixed (Trail 안 함, v3 _common.py 매칭)
  - Same-bar SL+TP: 거래소 자연 처리 (보통 STOP_MARKET 이 LIMIT 보다 빨리 fire)
  - 진입봉 exit skip: BT/LIVE 모두 자연 매칭 (봉 close 후 진입이라 봉 i 끝남)
"""
import asyncio
import json
import os
import logging
import math
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd
import pytz

from config import Config, DynamicConfig, BREAKOUT_DEFAULT_PARAMS
from binance_library import BinanceFuturesClient
from data_handler import BreakoutCandleManager
from state_manager import StateManager


class PositionState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.direction: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_size: float = 0.0
        self.take_profit: float = 0.0
        self.stop_loss: float = 0.0
        self.leverage: float = 1.0
        self.tp_order_id: Optional[int] = None
        self.sl_order_id: Optional[int] = None
        self.liq_price: float = 0.0
        self.is_virtual: bool = False
        self.entry_order_id: Optional[int] = None
        self.entry_time_ms: int = 0

    def has_position(self) -> bool:
        return self.direction is not None and self.entry_size > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'direction': self.direction,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'entry_size': self.entry_size,
            'take_profit': self.take_profit,
            'stop_loss': self.stop_loss,
            'leverage': self.leverage,
            'tp_order_id': self.tp_order_id,
            'sl_order_id': self.sl_order_id,
            'liq_price': self.liq_price,
            'is_virtual': self.is_virtual,
            'entry_order_id': self.entry_order_id,
            'entry_time_ms': self.entry_time_ms,
        }

    def from_dict(self, data: Dict[str, Any]):
        self.direction = data.get('direction')
        self.entry_price = data.get('entry_price', 0.0)
        ts_str = data.get('entry_time')
        self.entry_time = datetime.fromisoformat(ts_str) if ts_str else None
        self.entry_size = data.get('entry_size', 0.0)
        self.take_profit = data.get('take_profit', 0.0)
        self.stop_loss = data.get('stop_loss', 0.0)
        self.leverage = data.get('leverage', 1.0)
        self.tp_order_id = data.get('tp_order_id')
        self.sl_order_id = data.get('sl_order_id')
        self.liq_price = data.get('liq_price', 0.0)
        self.is_virtual = data.get('is_virtual', False)
        self.entry_order_id = data.get('entry_order_id')
        self.entry_time_ms = data.get('entry_time_ms', 0)


class BreakoutStrategy:
    def __init__(self, binance: BinanceFuturesClient, symbol_type: str, logger: logging.Logger):
        self.binance = binance
        self.symbol_type = symbol_type
        self.symbol = Config.get_symbol(symbol_type)
        self.logger = logger
        self.dynamic_config = DynamicConfig(symbol_type)

        self.position = PositionState()

        # 자본
        self.capital = self._get_param('INITIAL_CAPITAL', 200.0)

        # state manager
        self.state_path = Config.get_state_path(symbol_type)
        self.state_manager = StateManager(self.state_path, logger)

        # candle manager (length, mult 파라미터 필수)
        self.candle_manager = BreakoutCandleManager(
            length=self._get_param('LENGTH', 180),
            mult=self._get_param('MULT', 0.47),
            max_candles=2 * self._get_param('LENGTH', 180) + 100,
        )

        # 마지막 trade 의 entry 봉 timestamp (다음 봉 close 까진 새 진입 안 함)
        self._last_entry_ts: Optional[datetime] = None

    def _get_param(self, key: str, default=None):
        return self.dynamic_config.get(key, default)

    def _reload_config(self):
        self.dynamic_config.reload()

    def is_dry_run(self) -> bool:
        return self._get_param('DRY_RUN', True)

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(self):
        mode = "DRY RUN" if self.is_dry_run() else "LIVE 거래"
        self.logger.info("=" * 60)
        self.logger.info("Breakout Strategy 초기화")
        self.logger.info(f"*** {mode} 모드 ***")
        if not self.is_dry_run():
            self.logger.warning("*** 실제 자금으로 거래합니다! ***")
        self.logger.info("=" * 60)

        await self._init_capital()
        state_data = self.state_manager.load_state()
        await self._restore_state(state_data)

    async def _init_capital(self):
        if not self.is_dry_run():
            try:
                await self.binance.set_margin_type('ISOLATED')
            except Exception as e:
                # 이미 ISOLATED 면 에러 — 무시
                self.logger.debug(f"set_margin_type: {e}")

    async def _restore_state(self, state: Dict[str, Any]):
        if not state:
            return
        if 'capital' in state:
            self.capital = float(state['capital'])
            self.logger.info(f"저장된 자본 복구: ${self.capital:.2f}")
        if state.get('position'):
            self.position.from_dict(state['position'])
            if self.position.has_position():
                pp = Config.get_price_precision(self.symbol_type)
                self.logger.info(
                    f"포지션 복구: {self.position.direction} @ ${self.position.entry_price:.{pp}f}"
                )
        # candle manager state 는 load_historical 후 따로 복구
        self._cm_state_to_restore = state.get('candle_manager')
        # _last_entry_ts 복구 (재시작 시 진입봉 exit skip 정확히 동작)
        last_entry_ts_str = state.get('last_entry_ts')
        if last_entry_ts_str:
            self._last_entry_ts = pd.to_datetime(last_entry_ts_str, utc=True)
            self.logger.info(f"_last_entry_ts 복구: {self._last_entry_ts}")

    async def _sync_with_binance(self):
        """LIVE: 거래소 포지션 sync."""
        if self.is_dry_run():
            return
        try:
            pos_info = await self.binance.get_position_info()
            if pos_info and not self.position.has_position():
                self.logger.warning(f"거래소에 포지션 있음 — strategy state 갱신")
                self.position.direction = pos_info['direction']
                self.position.entry_price = pos_info['entry_price']
                self.position.entry_size = pos_info['size']
        except Exception as e:
            self.logger.error(f"거래소 sync 에러: {e}")

    def _save_state(self):
        data = {
            'capital': self.capital,
            'position': self.position.to_dict() if self.position.has_position() else None,
            'candle_manager': self.candle_manager.to_dict(),
            'last_entry_ts': self._last_entry_ts.isoformat() if self._last_entry_ts is not None else None,
            'last_updated': datetime.now(pytz.UTC).isoformat(),
        }
        self.state_manager.save_state(data)

    # ========================================================================
    # Historical data loading
    # ========================================================================

    async def load_historical_data(self):
        tf = self._get_param('TF', '5m')
        L = self._get_param('LENGTH', 180)
        # ATR (Wilder/RMA) 수렴 위해 충분히 많이 — 5L 또는 2000 봉 (Wilder ~10×L 권장이지만 5L 도 충분히 수렴)
        n_bars = max(2000, 5 * L)
        self.logger.info(f"과거 5m 봉 데이터 로드 중... ({n_bars} bars 목표)")

        # Binance API limit 1500 per request (futures)
        all_klines = []
        end_ts = int(time.time() * 1000)
        while len(all_klines) < n_bars:
            limit = min(1500, n_bars - len(all_klines))
            try:
                # binance.client.futures_klines 는 sync 메서드
                klines = self.binance.client.futures_klines(
                    symbol=self.symbol, interval=tf, limit=limit, endTime=end_ts
                )
            except Exception as e:
                self.logger.error(f"klines 가져오기 실패: {e}")
                break
            if not klines:
                break
            # klines = [[open_time, o, h, l, c, v, close_time, ...], ...]
            # 마지막 미완성 봉 제외 (첫 호출에만)
            if not all_klines:
                klines = klines[:-1]
            all_klines = klines + all_klines
            end_ts = klines[0][0] - 1
            if len(klines) < limit:
                break

        # dict 형식으로 변환
        formatted = []
        for k in all_klines:
            formatted.append({
                't': k[0], 'o': k[1], 'h': k[2], 'l': k[3], 'c': k[4], 'v': k[5]
            })
        self.candle_manager.load_historical(formatted)
        self.logger.info(f"5m 봉 로드 완료: {len(formatted)} 개")

        # candle_manager state 복구 — 의미 있는 trendline (upper_init=True) 일 때만.
        # clean restart 시 빈 candle_manager 블록이 load_historical 의 정확한 replay 결과를 덮어쓰지 않도록.
        if hasattr(self, '_cm_state_to_restore') and self._cm_state_to_restore \
           and self._cm_state_to_restore.get('upper_init', False):
            self.candle_manager.from_dict(self._cm_state_to_restore)

        th = self.candle_manager.get_thresholds()
        self.logger.info(
            f"Trendline state: upper={th['upper']}, lower={th['lower']}, "
            f"upos={th['upos']}, dnos={th['dnos']}, atr={th['atr']}"
        )

    # ========================================================================
    # Candle close handler — main signal entry point
    # ========================================================================

    async def on_candle_close(self, kline: Dict[str, Any]):
        """5m 봉 마감 (kline x=true) 시 호출."""
        if not kline.get('x', True):
            return  # 미완성 봉 무시

        is_new = self.candle_manager.append_closed_kline(kline)
        if not is_new:
            return

        self._reload_config()

        pp = Config.get_price_precision(self.symbol_type)
        ts = pd.to_datetime(kline['t'], unit='ms', utc=True)
        c = float(kline['c'])
        self.logger.info(
            f"5m | {ts.strftime('%H:%M')} | O:{float(kline['o']):.{pp}f} "
            f"H:{float(kline['h']):.{pp}f} L:{float(kline['l']):.{pp}f} C:{c:.{pp}f}"
        )

        # 포지션 있으면 OHLC 로 SL/TP/LIQ 체크 (DRY 모드만 — LIVE 는 거래소가 자동 처리)
        if self.position.has_position():
            await self._check_exit_dry(kline)
            self._save_state()
            return

        # 포지션 없음 → breakout signal 체크
        signal = self.candle_manager.get_breakout_signal()
        if signal:
            self.logger.info(f"[BREAKOUT] {signal} signal at close=${c:.{pp}f}")
            trade_dir = self._get_param('TRADE_DIRECTION', 'BOTH')
            if trade_dir != 'BOTH' and trade_dir != signal:
                self.logger.info(f"  TRADE_DIRECTION={trade_dir} 라 {signal} skip")
            else:
                await self._execute_entry(signal, c, ts)

        self._save_state()

    # ========================================================================
    # Entry execution (MARKET)
    # ========================================================================

    async def _execute_entry(self, direction: str, signal_price: float, bar_ts):
        atr_now = self.candle_manager.get_current_atr()
        if atr_now is None or atr_now <= 0:
            self.logger.warning(f"ATR 없음 — entry skip")
            return

        sl_atr_mult = self._get_param('SL_ATR_MULT', 4.2)
        rr = self._get_param('RR', 1.1)
        risk_per_trade = self._get_param('RISK_PER_TRADE', 0.08)
        max_lev = self._get_param('MAX_LEVERAGE', 90)
        taker_fee = self._get_param('TAKER_FEE', 0.0005)

        sl_dist = atr_now * sl_atr_mult
        if sl_dist <= 0:
            return

        ep = signal_price  # MARKET 진입 → 시장가 fill 가정 (BT 의 c[i] 와 매칭)

        sl_pct = sl_dist / ep
        eff_sl = sl_pct + 2.0 * taker_fee
        # BT 와 동일한 float lev 로 사이즈 계산 → 같은 사이즈 = 같은 risk
        lev_float = max(1.0, min(float(max_lev), risk_per_trade / eff_sl))
        # 거래소는 정수 lev 만 받음 → ceil. 단 사이즈/LIQ 는 lev_float 기준 (BT 매칭).
        # 효과: 거래소 set_lev = ceil 이라 max 허용 notional 이 약간 더 큼 → 마진 5% 버퍼 자연 발생.
        lev_int = max(1, min(int(max_lev), int(math.ceil(lev_float))))

        if direction == 'LONG':
            sl_edge = ep - sl_dist
            tp_edge = ep + rr * sl_dist
            liq_edge = ep * (1.0 - 1.0 / lev_float)  # BT 의 LIQ 공식 그대로
        else:
            sl_edge = ep + sl_dist
            tp_edge = ep - rr * sl_dist
            liq_edge = ep * (1.0 + 1.0 / lev_float)

        notional = self.capital * lev_float
        sz = notional / ep

        pp = Config.get_price_precision(self.symbol_type)
        qp = Config.get_qty_precision(self.symbol_type)
        sz = round(sz, qp)
        if sz <= 0:
            self.logger.warning(f"size 너무 작음 — entry skip (sz={sz})")
            return

        self.logger.info("=" * 50)
        self.logger.info(f"  {direction} 시장가 진입")
        self.logger.info(f"  진입가(예상): ${ep:.{pp}f}, SL: ${sl_edge:.{pp}f}, TP: ${tp_edge:.{pp}f}")
        self.logger.info(f"  lev_float={lev_float:.2f} (거래소 set={lev_int}x), size={sz}")
        self.logger.info(f"  LIQ(BT)≈${liq_edge:.{pp}f} (실제 거래소 LIQ 는 약간 보수적, set_lev={lev_int} 기준)")
        self.logger.info("=" * 50)

        if self.is_dry_run():
            # DRY 는 BT 와 동일 LIQ 사용
            await self._on_entry_filled_dry(direction, ep, sz, sl_edge, tp_edge, liq_edge, lev_float, bar_ts)
        else:
            try:
                # 시장가 진입 (open_market_position 내부에서 set_leverage 호출 — leverage 명시 전달)
                order = await self.binance.open_market_position(
                    direction=direction,
                    quantity=sz,
                    leverage=lev_int,
                )
                if order is None:
                    self.logger.error("시장가 진입 실패")
                    return

                entry_order_id = order.get('orderId')
                entry_time_ms = order.get('updateTime', int(time.time() * 1000))

                # ★ 검증된 패턴 (hyper_v2:567-578): 0.5초 대기 후 거래소 포지션 조회로 실제 체결가 획득
                # MARKET 주문 응답의 avgPrice 가 0.0 으로 오는 경우가 있어 별도 조회 필수
                await asyncio.sleep(0.5)
                pos_info = await self.binance.get_position_info()
                if pos_info is None or pos_info.get('size', 0) == 0:
                    self.logger.error("시장가 진입 후 포지션 조회 실패 — 비상 청산")
                    await self._emergency_close()
                    return

                actual_entry_price = pos_info['entry_price']
                actual_size = pos_info['size']
                self.logger.info(
                    f"시장가 fill: {direction} {actual_size} @ ${actual_entry_price:.{pp}f} (id={entry_order_id})"
                )

                # SL/TP 가격을 actual entry 기준 재계산 (BT 와 동일하게 lev_float 사용)
                if direction == 'LONG':
                    new_sl = actual_entry_price - sl_dist
                    new_tp = actual_entry_price + rr * sl_dist
                    new_liq = actual_entry_price * (1.0 - 1.0 / lev_float)
                else:
                    new_sl = actual_entry_price + sl_dist
                    new_tp = actual_entry_price - rr * sl_dist
                    new_liq = actual_entry_price * (1.0 + 1.0 / lev_float)

                self.position.entry_time_ms = entry_time_ms
                await self._on_entry_filled_live(
                    direction, actual_entry_price, actual_size,
                    new_sl, new_tp, new_liq, lev_float, bar_ts,
                    entry_order_id=entry_order_id,
                )
            except Exception as e:
                self.logger.exception(f"시장가 진입 에러: {e}")

    async def _on_entry_filled_dry(
        self, direction, ep, sz, sl_edge, tp_edge, liq_edge, lev, bar_ts
    ):
        self.position.direction = direction
        self.position.entry_price = ep
        # entry_time = 진입봉 timestamp (BT entry_idx 와 매칭). DRY exit check 의 _last_entry_ts 도 이거 사용.
        self.position.entry_time = bar_ts.to_pydatetime() if hasattr(bar_ts, 'to_pydatetime') else bar_ts
        self.position.entry_size = sz
        self.position.stop_loss = sl_edge
        self.position.take_profit = tp_edge
        self.position.liq_price = liq_edge
        self.position.leverage = lev
        self.position.is_virtual = False
        self._last_entry_ts = bar_ts  # 봉 timestamp (Timestamp 객체)
        self.logger.info(f"[DRY] {direction} 진입 완료 (가상 fill @ ${ep}, bar_ts={bar_ts})")

    async def _on_entry_filled_live(
        self, direction, ep, sz, sl_edge, tp_edge, liq_edge, lev, bar_ts,
        entry_order_id=None,
    ):
        self.position.direction = direction
        self.position.entry_price = ep
        self.position.entry_time = bar_ts.to_pydatetime() if hasattr(bar_ts, 'to_pydatetime') else bar_ts
        self.position.entry_size = sz
        self.position.stop_loss = sl_edge
        self.position.take_profit = tp_edge
        self.position.liq_price = liq_edge
        self.position.leverage = lev
        self.position.entry_order_id = entry_order_id
        self.position.entry_time_ms = int(time.time() * 1000)
        self._last_entry_ts = bar_ts

        # SL placement (1초 간격 60회 retry)
        sl_ok = await self._place_sl_with_retry(sl_edge, sz)
        # TP placement
        tp_ok = await self._place_tp_with_retry(tp_edge, sz)
        if not sl_ok or not tp_ok:
            self.logger.error("SL/TP placement 실패 — 비상 청산")
            await self._emergency_close()

    async def _place_sl_with_retry(self, sl_price: float, sz: float, retries: int = 60) -> bool:
        """ob/fvg 와 동일 패턴: quantity 인자 없이 (closePosition=true 사용), stop_price 만 전달."""
        for attempt in range(retries):
            try:
                pos = await self.binance.get_position_info()
                if not pos or pos.get('size', 0) == 0:
                    self.logger.warning("포지션 사라짐 — SL placement 중단")
                    return False
                order = await self.binance.set_stop_loss(
                    direction=self.position.direction,
                    stop_price=sl_price,
                )
                if order:
                    sl_id = str(order.get('orderId') or order.get('algoId') or '')
                    if sl_id:
                        self.position.sl_order_id = sl_id
                        self.logger.info(f"SL placement 성공 (시도 {attempt+1}): ${sl_price}")
                        return True
            except Exception as e:
                self.logger.warning(f"SL placement 시도 {attempt+1} 실패: {e}")
            await asyncio.sleep(1)
        return False

    async def _place_tp_with_retry(self, tp_price: float, sz: float, retries: int = 60) -> bool:
        """ob/fvg 와 동일 패턴: quantity 명시 전달."""
        for attempt in range(retries):
            try:
                pos = await self.binance.get_position_info()
                if not pos or pos.get('size', 0) == 0:
                    self.logger.warning("포지션 사라짐 — TP placement 중단")
                    return False
                order = await self.binance.place_limit_close(
                    direction=self.position.direction,
                    price=tp_price,
                    quantity=sz,
                )
                if order:
                    tp_id = str(order.get('orderId') or '')
                    if tp_id:
                        self.position.tp_order_id = tp_id
                        self.logger.info(f"TP placement 성공 (시도 {attempt+1}): ${tp_price}")
                        return True
            except Exception as e:
                self.logger.warning(f"TP placement 시도 {attempt+1} 실패: {e}")
            await asyncio.sleep(1)
        return False

    async def _emergency_close(self):
        """SL/TP placement 실패 또는 critical 에러 시 시장가 청산."""
        self.logger.error("🚨 비상 청산 (시장가)")
        if self.is_dry_run():
            self.position.reset()
            return
        try:
            await self.binance.cancel_all_orders()
            await self.binance.close_position_market(self.position.direction, self.position.entry_size)
        except Exception as e:
            self.logger.exception(f"비상 청산 에러: {e}")
        self.position.reset()
        self._save_state()

    # ========================================================================
    # Exit handling
    # ========================================================================

    async def on_tp_filled(self, exit_price: float):
        if not self.position.has_position():
            return
        net_pnl = await self._compute_actual_pnl(exit_price, 'TP')
        old_cap = self.capital
        self.capital += net_pnl
        self._record_trade(exit_price, 'TP', net_pnl)
        self.logger.info(f"✅ TP 체결: ${self.capital:.2f} (PnL: ${net_pnl:+.2f})")
        self.position.reset()
        self._save_state()

    async def on_sl_filled(self, exit_price: float):
        if not self.position.has_position():
            return
        net_pnl = await self._compute_actual_pnl(exit_price, 'SL')
        old_cap = self.capital
        self.capital += net_pnl
        self._record_trade(exit_price, 'SL', net_pnl)
        self.logger.info(f"🛑 SL 체결: ${self.capital:.2f} (PnL: ${net_pnl:+.2f})")
        self.position.reset()
        self._save_state()

    async def _compute_actual_pnl(self, exit_price: float, reason: str) -> float:
        """LIVE: 거래소 실제 PnL 조회 (entry+exit 수수료 포함). 실패 시 local 계산."""
        if self.is_dry_run():
            return self._calc_local_pnl(exit_price, reason)
        try:
            result = await self.binance.get_actual_trade_pnl(
                entry_order_id=self.position.entry_order_id,
                entry_time_ms=self.position.entry_time_ms,
            )
            if result and 'net_pnl' in result:
                return float(result['net_pnl'])
        except Exception as e:
            self.logger.warning(f"actual PnL 조회 실패 — local 계산: {e}")
        return self._calc_local_pnl(exit_price, reason)

    def _calc_local_pnl(self, exit_price: float, reason: str) -> float:
        ep = self.position.entry_price
        sz = self.position.entry_size
        taker = self._get_param('TAKER_FEE', 0.0005)
        maker = self._get_param('MAKER_FEE', 0.0002)

        if self.position.direction == 'LONG':
            pnl = (exit_price - ep) * sz
        else:
            pnl = (ep - exit_price) * sz

        entry_fee = ep * sz * taker  # MARKET entry → TAKER
        if reason == 'TP':
            exit_fee = exit_price * sz * maker  # LIMIT TP → MAKER
        else:
            exit_fee = exit_price * sz * taker  # SL/LIQ STOP_MARKET → TAKER
        return pnl - entry_fee - exit_fee

    def _record_trade(self, exit_price: float, reason: str, net_pnl: float):
        path = Config.get_trades_path(self.symbol_type)
        try:
            with open(path, 'a') as f:
                ent = self.position.entry_time.isoformat() if self.position.entry_time else ''
                ext = datetime.now(pytz.UTC).isoformat()
                f.write(
                    f"{ent},{ext},{self.position.direction},{self.position.entry_price},"
                    f"{exit_price},{self.position.take_profit},{self.position.stop_loss},"
                    f"{self.position.leverage:.2f},{self.position.entry_size},{reason},"
                    f"{net_pnl:.4f},{self.capital:.4f}\n"
                )
        except Exception as e:
            self.logger.error(f"trade 기록 실패: {e}")

    async def _check_exit_dry(self, kline: Dict[str, Any]):
        """DRY 모드: 봉 OHLC 로 SL/TP/LIQ touch 체크. 진입봉 다음 bar 부터만 (BT 매칭)."""
        h_v = float(kline['h'])
        l_v = float(kline['l'])
        ts = pd.to_datetime(kline['t'], unit='ms', utc=True)

        # 진입봉 자체 (= 진입 bar timestamp 와 같은 봉) 는 skip
        if self._last_entry_ts is not None and ts <= self._last_entry_ts:
            return

        ex_price = None
        ex_reason = None
        if self.position.direction == 'LONG':
            if l_v <= self.position.liq_price:
                ex_price = self.position.liq_price; ex_reason = 'LIQ'
            elif l_v <= self.position.stop_loss:
                ex_price = self.position.stop_loss; ex_reason = 'SL'
            elif h_v >= self.position.take_profit:
                ex_price = self.position.take_profit; ex_reason = 'TP'
        else:
            if h_v >= self.position.liq_price:
                ex_price = self.position.liq_price; ex_reason = 'LIQ'
            elif h_v >= self.position.stop_loss:
                ex_price = self.position.stop_loss; ex_reason = 'SL'
            elif l_v <= self.position.take_profit:
                ex_price = self.position.take_profit; ex_reason = 'TP'

        if ex_reason:
            if ex_reason == 'LIQ':
                # capital 전체 손실 — net_pnl 먼저 기록, 그 다음 cap=0
                net_pnl = -self.capital
                self.capital = 0.0
            else:
                net_pnl = self._calc_local_pnl(ex_price, ex_reason)
                self.capital += net_pnl
                if self.capital < 0:
                    self.capital = 0.0
            self._record_trade(ex_price, ex_reason, net_pnl)
            self.logger.info(
                f"[DRY] {ex_reason} 청산 @ ${ex_price}, PnL=${net_pnl:+.2f}, cap=${self.capital:.2f}"
            )
            self.position.reset()

    # ========================================================================
    # Tick handler (used for SL/TP detection if needed)
    # ========================================================================

    async def on_tick(self, price: float):
        # Breakout 전략은 봉 마감 기반이라 tick 은 SL/TP 모니터링용
        # 거래소가 자동 처리하므로 여기선 가벼운 fallback 만 (DRY 모드)
        pass

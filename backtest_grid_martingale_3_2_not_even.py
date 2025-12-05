"""
Grid Martingale Backtest Strategy V3_2 - 물량 덜어내기 + 그리드 재설정

전략 개요:
- Level 1: 평단가 +0.4% 익절 (전량) → 새 그리드 설정
- Level 2 이상: 평단가 +0.01%에서 1단계 물량 제외 나머지 덜어내기
  → 덜어낸 후 그리드 재설정 (현재 평단가 = 새 Level 1 진입가)
  → 기준가 역산: grid_center = avg_price / (1 - GRID_INTERVAL_PCT) for LONG
                 grid_center = avg_price / (1 + GRID_INTERVAL_PCT) for SHORT
- Level 4 가격 터치 시 손절 (전량)

물량 덜어내기 후:
- Level 1 물량만 남김 (current_level = 1 로 리셋)
- 평단가는 그대로 유지 (= 새 Level 1 진입가)
- 그리드 기준가 역산하여 Level 2~4 가격 재설정

사용법:
    python backtest_grid_martingale_3_2.py
"""

import pandas as pd
import numpy as np
from datetime import datetime

# ================================================================================
# CONFIG - 파라미터 설정
# ================================================================================

# 데이터 파일
DATA_FILE = 'historical_data/BTCUSDT_1m_raw.csv'

# 백테스트 기간
START_DATE = '2024-01-01'
END_DATE = '2025-12-30'

# 자본 설정
INITIAL_CAPITAL = 1000.0  # USDT
LEVERAGE_LONG = 20   # LONG 레버리지 (파라미터)
LEVERAGE_SHORT = 5  # SHORT 레버리지 (파라미터)

# 거래 방향 설정
# 'BOTH' = 롱/숏 둘 다, 'LONG' = 롱만, 'SHORT' = 숏만
TRADE_DIRECTION = 'LONG'

# 그리드 설정
GRID_RANGE_PCT = 0.040  # ±4% 범위 : 이더리움은 0.02로
MAX_ENTRY_LEVEL = 4  # 최대 진입 레벨
# 진입 비율
ENTRY_RATIOS = [0.05, 0.20, 0.25, 0.5]  # 5%, 10%, 30%, 55%

# 레벨별 진입 거리 (기준가 대비 %)
# Level 1: 0.5%, Level 2: 1.0%, Level 3: 4%, Level 4: 4.5%, 손절: 5%
LEVEL_DISTANCES = [0.005, 0.010, 0.040, 0.045]  # 진입 레벨
SL_DISTANCE = 0.05  # 손절 레벨 (5%)

# 익절 설정
TP_PCT = 0.005  # 익절: 평단가 +0.5% (Level 1~2)
BE_PCT = 0.001  # 본절: 평단가 +0.1% (Level 3 이상, 수수료 없음)
# 손절은 Level 4 가격 터치 시 (SL_PCT 미사용)

# 수수료
MAKER_FEE = 0.0  # 지정가 수수료
TAKER_FEE = 0.000275  # 시장가 수수료 0.0275%

# ================================================================================
# 백테스터 클래스
# ================================================================================

class GridMartingaleBacktesterV3:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.capital = INITIAL_CAPITAL
        self.initial_capital = INITIAL_CAPITAL

        # 포지션 상태
        self.position = None  # 'LONG' or 'SHORT' or None
        self.entries = []  # [(price, amount), ...]
        self.avg_price = 0.0
        self.total_size = 0.0  # BTC 수량
        self.current_level = 0  # 현재 진입 레벨 (0~4)
        self.level_prices = [None] * MAX_ENTRY_LEVEL  # 각 레벨 진입가격
        self.entry_fees = 0.0  # 누적 진입 수수료
        self.level1_btc_amount = 0.0  # Level 1 진입 시 BTC 수량 (덜어내기용)
        self.start_grid_center = None  # 거래 시작 시점의 grid_center

        # 그리드 상태
        self.grid_center = None  # 그리드 기준 가격
        self.pending_limit_price = None  # 대기 중인 지정가
        self.need_market_entry = False  # 다음 봉에서 시장가 체결 필요

        # 거래 기록
        self.trades = []
        self.equity_curve = []

        # 통계
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_level_reached = 0

        # LONG/SHORT 별 통계
        self.long_wins = 0
        self.long_losses = 0
        self.short_wins = 0
        self.short_losses = 0

        # Level 4 통계
        self.level4_wins = 0
        self.level4_losses = 0

    def get_level_price(self, level: int, direction: str) -> float:
        """레벨별 가격 계산 (불균등 간격)"""
        # level 0~3: 진입 레벨, level 4: 손절 레벨
        if level < MAX_ENTRY_LEVEL:
            distance = LEVEL_DISTANCES[level]
        else:
            distance = SL_DISTANCE

        if direction == 'LONG':
            return self.grid_center * (1 - distance)
        else:  # SHORT
            return self.grid_center * (1 + distance)

    def setup_grid(self, center_price: float):
        """그리드 초기화 - 1단계 지정가만 설정"""
        self.grid_center = center_price
        self.pending_limit_price = None
        self.need_market_entry = False

    def calculate_avg_price(self):
        """평균 진입가 계산"""
        if not self.entries:
            return 0.0

        total_value = sum(price * amount for price, amount in self.entries)
        total_amount = sum(amount for _, amount in self.entries)

        if total_amount == 0:
            return 0.0

        return total_value / total_amount

    def get_leverage(self, direction: str):
        """방향에 따른 레버리지 반환"""
        return LEVERAGE_LONG if direction == 'LONG' else LEVERAGE_SHORT

    def execute_entry(self, price: float, ratio: float, direction: str, is_market: bool = False):
        """진입 실행"""
        leverage = self.get_leverage(direction)
        entry_value = self.capital * ratio * leverage

        # BTC 수량 계산
        btc_amount = entry_value / price

        # 수수료 (시장가만)
        if is_market:
            fee = entry_value * TAKER_FEE
        else:
            fee = entry_value * MAKER_FEE

        # 진입 기록
        self.entries.append((price, btc_amount))
        self.total_size += btc_amount
        self.avg_price = self.calculate_avg_price()
        self.entry_fees += fee  # 진입 수수료 누적

        # 레벨별 진입가격 저장
        self.level_prices[self.current_level] = price

        # Level 1 물량 기록 (덜어내기용)
        if self.current_level == 0:
            self.level1_btc_amount = btc_amount

        self.current_level += 1

        # 최대 레벨 기록
        if self.current_level > self.max_level_reached:
            self.max_level_reached = self.current_level

        return fee

    def partial_close_and_reset_grid(self, exit_price: float, timestamp):
        """
        Level 2 이상에서 평단가 +0.01% 도달 시:
        - Level 1 물량 제외 나머지 덜어내기 (본절 청산)
        - 그리드 재설정 (현재 평단가 = 새 Level 1 진입가)
        """
        if self.position is None or self.total_size == 0:
            return

        # 덜어낼 물량 = 전체 - Level 1 물량
        close_amount = self.total_size - self.level1_btc_amount

        if close_amount <= 0:
            return

        # PnL 계산 (덜어낸 물량에 대해서만)
        if self.position == 'LONG':
            pnl = (exit_price - self.avg_price) * close_amount
        else:  # SHORT
            pnl = (self.avg_price - exit_price) * close_amount

        # 본절 청산이므로 수수료 없음 (지정가)
        net_pnl = pnl
        self.capital += net_pnl

        # 거래 기록 (덜어내기)
        is_win = net_pnl > 0
        self.trades.append({
            'timestamp': timestamp,
            'direction': self.position,
            'start_grid_center': self.start_grid_center,
            'grid_center': self.grid_center,
            'entry_price': self.avg_price,
            'exit_price': exit_price,
            'sl_target_price': None,
            'size': close_amount,  # 덜어낸 물량
            'level': self.current_level,
            'pnl': net_pnl,
            'reason': 'PARTIAL_BE',  # 부분 본절
            'balance': self.capital,
            **{f'level{i+1}_price': self.level_prices[i] if i < len(self.level_prices) else None
               for i in range(MAX_ENTRY_LEVEL)}
        })

        # 통계 (덜어내기도 거래로 카운트)
        self.total_trades += 1
        if is_win:
            self.winning_trades += 1
            if self.position == 'LONG':
                self.long_wins += 1
            else:
                self.short_wins += 1
        else:
            self.losing_trades += 1
            if self.position == 'LONG':
                self.long_losses += 1
            else:
                self.short_losses += 1

        # ========================================
        # 그리드 재설정: Level 1 물량만 남김
        # ========================================

        # 남은 물량 = Level 1 물량
        self.total_size = self.level1_btc_amount

        # entries를 새 평단가 기준으로 재설정
        # 현재 평단가가 새 Level 1 진입가가 됨
        new_level1_price = self.avg_price
        self.entries = [(new_level1_price, self.level1_btc_amount)]

        # 평단가는 동일하게 유지
        # (entries가 1개이므로 avg_price = new_level1_price)

        # Level 1로 리셋
        self.current_level = 1
        self.level_prices = [new_level1_price] + [None] * (MAX_ENTRY_LEVEL - 1)
        self.entry_fees = 0.0  # 수수료 리셋

        # 그리드 기준가 역산
        # LONG: level1_price = grid_center * (1 - LEVEL_DISTANCES[0])
        #       → grid_center = level1_price / (1 - LEVEL_DISTANCES[0])
        # SHORT: level1_price = grid_center * (1 + LEVEL_DISTANCES[0])
        #        → grid_center = level1_price / (1 + LEVEL_DISTANCES[0])
        if self.position == 'LONG':
            self.grid_center = new_level1_price / (1 - LEVEL_DISTANCES[0])
        else:  # SHORT
            self.grid_center = new_level1_price / (1 + LEVEL_DISTANCES[0])

        # 대기 상태 리셋
        self.pending_limit_price = None
        self.need_market_entry = False

    def close_position_breakeven(self, exit_price: float, reason: str, timestamp):
        """본절 청산 (수수료 없음) - Level 3 이상에서 사용"""
        if self.position is None or self.total_size == 0:
            return 0.0

        # PnL 계산 (레버리지는 이미 total_size에 반영됨)
        if self.position == 'LONG':
            pnl = (exit_price - self.avg_price) * self.total_size
        else:  # SHORT
            pnl = (self.avg_price - exit_price) * self.total_size

        # 수수료 없음 (지정가 본절)
        net_pnl = pnl
        self.capital += net_pnl

        # 거래 기록
        is_win = net_pnl > 0
        self.trades.append({
            'timestamp': timestamp,
            'direction': self.position,
            'start_grid_center': self.start_grid_center,
            'grid_center': self.grid_center,
            'entry_price': self.avg_price,
            'exit_price': exit_price,
            'sl_target_price': None,
            'size': self.total_size,
            'level': self.current_level,
            'pnl': net_pnl,
            'reason': reason,
            'balance': self.capital,
            **{f'level{i+1}_price': self.level_prices[i] if i < len(self.level_prices) else None
               for i in range(MAX_ENTRY_LEVEL)}
        })

        # 통계 업데이트
        self.total_trades += 1
        if is_win:
            self.winning_trades += 1
            if self.position == 'LONG':
                self.long_wins += 1
            else:
                self.short_wins += 1
        else:
            self.losing_trades += 1
            if self.position == 'LONG':
                self.long_losses += 1
            else:
                self.short_losses += 1

        # 포지션 리셋
        self.position = None
        self.entries = []
        self.avg_price = 0.0
        self.total_size = 0.0
        self.current_level = 0
        self.pending_limit_price = None
        self.need_market_entry = False
        self.level_prices = [None] * MAX_ENTRY_LEVEL
        self.entry_fees = 0.0
        self.level1_btc_amount = 0.0
        self.start_grid_center = None

        return exit_price

    def close_position(self, exit_price: float, reason: str, timestamp, is_market: bool = False):
        """포지션 청산"""
        if self.position is None or self.total_size == 0:
            return 0.0

        # PnL 계산 (레버리지는 이미 total_size에 반영됨)
        if self.position == 'LONG':
            pnl = (exit_price - self.avg_price) * self.total_size
        else:  # SHORT
            pnl = (self.avg_price - exit_price) * self.total_size

        # 수수료 (청산 수수료)
        exit_value = exit_price * self.total_size
        if is_market:
            exit_fee = exit_value * TAKER_FEE
        else:
            exit_fee = exit_value * MAKER_FEE

        # 총 수수료 = 진입 수수료 + 청산 수수료
        total_fee = self.entry_fees + exit_fee
        net_pnl = pnl - total_fee
        self.capital += net_pnl

        # 손절 예정가 계산 (max 레벨 도달 시에만)
        sl_target_price = None
        if self.current_level >= MAX_ENTRY_LEVEL:
            if self.position == 'LONG':
                sl_target_price = self.avg_price * (1 - SL_DISTANCE)
            else:  # SHORT
                sl_target_price = self.avg_price * (1 + SL_DISTANCE)

        # 거래 기록
        is_win = net_pnl > 0
        self.trades.append({
            'timestamp': timestamp,
            'direction': self.position,
            'start_grid_center': self.start_grid_center,
            'grid_center': self.grid_center,
            'entry_price': self.avg_price,
            'exit_price': exit_price,
            'sl_target_price': sl_target_price,
            'size': self.total_size,
            'level': self.current_level,
            'pnl': net_pnl,
            'reason': reason,
            'balance': self.capital,
            **{f'level{i+1}_price': self.level_prices[i] if i < len(self.level_prices) else None
               for i in range(MAX_ENTRY_LEVEL)}
        })

        # 통계 업데이트
        self.total_trades += 1
        if is_win:
            self.winning_trades += 1
            if self.position == 'LONG':
                self.long_wins += 1
            else:
                self.short_wins += 1
        else:
            self.losing_trades += 1
            if self.position == 'LONG':
                self.long_losses += 1
            else:
                self.short_losses += 1

        # Level 4 통계
        if self.current_level >= MAX_ENTRY_LEVEL:
            if is_win:
                self.level4_wins += 1
            else:
                self.level4_losses += 1

        # 포지션 리셋
        self.position = None
        self.entries = []
        self.avg_price = 0.0
        self.total_size = 0.0
        self.current_level = 0
        self.pending_limit_price = None
        self.need_market_entry = False
        self.level_prices = [None] * MAX_ENTRY_LEVEL  # 레벨 가격 리셋
        self.entry_fees = 0.0  # 진입 수수료 리셋
        self.level1_btc_amount = 0.0  # Level 1 물량 리셋
        self.start_grid_center = None  # 시작 그리드 센터 리셋

        return exit_price

    def process_bar(self, idx: int, row: pd.Series):
        """봉 처리"""
        timestamp = row['timestamp']
        open_price = row['Open']
        high_price = row['High']
        low_price = row['Low']
        close_price = row['Close']

        # 첫 봉이면 그리드 설정
        if self.grid_center is None:
            self.setup_grid(close_price)
            self.equity_curve.append({
                'timestamp': timestamp,
                'equity': self.capital
            })
            return

        # ============================================================
        # Step 1: 포지션 없음 - 첫 진입 + 한 봉에 여러 레벨 동시 체결
        # (거미줄처럼 미리 지정가 걸어놓은 것처럼 처리)
        # ============================================================
        if self.position is None:
            long_limit = self.get_level_price(0, 'LONG')   # -1%
            short_limit = self.get_level_price(0, 'SHORT')  # +1%

            # LONG 체결 (가격이 아래로)
            if (TRADE_DIRECTION in ['BOTH', 'LONG']) and low_price <= long_limit:
                self.position = 'LONG'
                self.start_grid_center = self.grid_center  # 거래 시작 시점 기록
                # 한 봉에서 터치한 모든 레벨 체결
                for level in range(MAX_ENTRY_LEVEL):
                    level_price = self.get_level_price(level, 'LONG')
                    if low_price <= level_price:
                        self.execute_entry(level_price, ENTRY_RATIOS[level], 'LONG', is_market=False)
                    else:
                        break

            # SHORT 체결 (가격이 위로)
            elif (TRADE_DIRECTION in ['BOTH', 'SHORT']) and high_price >= short_limit:
                self.position = 'SHORT'
                self.start_grid_center = self.grid_center  # 거래 시작 시점 기록
                # 한 봉에서 터치한 모든 레벨 체결
                for level in range(MAX_ENTRY_LEVEL):
                    level_price = self.get_level_price(level, 'SHORT')
                    if high_price >= level_price:
                        self.execute_entry(level_price, ENTRY_RATIOS[level], 'SHORT', is_market=False)
                    else:
                        break

        # ============================================================
        # Step 2: 포지션 있음 - 추가 진입 체크 (한 봉에 여러 레벨 동시 체결)
        # ============================================================
        elif self.position is not None and self.current_level < MAX_ENTRY_LEVEL:
            if self.position == 'LONG':
                # 한 봉에서 터치한 모든 레벨 체결
                for level in range(self.current_level, MAX_ENTRY_LEVEL):
                    level_price = self.get_level_price(level, 'LONG')
                    if low_price <= level_price:
                        self.execute_entry(level_price, ENTRY_RATIOS[level], 'LONG', is_market=False)
                    else:
                        break
            else:  # SHORT
                for level in range(self.current_level, MAX_ENTRY_LEVEL):
                    level_price = self.get_level_price(level, 'SHORT')
                    if high_price >= level_price:
                        self.execute_entry(level_price, ENTRY_RATIOS[level], 'SHORT', is_market=False)
                    else:
                        break

        # ============================================================
        # Step 3: 손절 체크 (Level 4 체결 후, Level 5 가격 터치 시 손절)
        # 손절가에서 지정가 청산 (close 가격 아님)
        # ============================================================
        if self.position is not None and self.current_level >= MAX_ENTRY_LEVEL:
            sl_price = self.get_level_price(MAX_ENTRY_LEVEL, self.position)

            if self.position == 'LONG' and low_price <= sl_price:
                # 손절가에서 지정가 청산
                new_center = self.close_position(sl_price, 'SL', timestamp, is_market=False)
                self.setup_grid(new_center)
                self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                return

            elif self.position == 'SHORT' and high_price >= sl_price:
                # 손절가에서 지정가 청산
                new_center = self.close_position(sl_price, 'SL', timestamp, is_market=False)
                self.setup_grid(new_center)
                self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                return

        # ============================================================
        # Step 4: 익절 체크
        # Level 1: 평단가 +TP_PCT% 전량 익절
        # Level 2 이상: 평단가 +BE_PCT%에서 덜어내기 + 그리드 재설정
        # ============================================================
        if self.position is not None:
            if self.current_level == 1:
                if self.position == 'LONG':
                    tp_price = self.avg_price * (1 + TP_PCT)
                    if high_price >= tp_price:
                        new_center = self.close_position(tp_price, 'TP', timestamp, is_market=False)
                        self.setup_grid(new_center)
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        return
                else:  # SHORT
                    tp_price = self.avg_price * (1 - TP_PCT)
                    if low_price <= tp_price:
                        new_center = self.close_position(tp_price, 'TP', timestamp, is_market=False)
                        self.setup_grid(new_center)
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        return
            elif self.current_level >= 2:
                if self.position == 'LONG':
                    be_price = self.avg_price * (1 + BE_PCT)
                    if high_price >= be_price:
                        self.partial_close_and_reset_grid(be_price, timestamp)
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        return
                else:  # SHORT
                    be_price = self.avg_price * (1 - BE_PCT)
                    if low_price <= be_price:
                        self.partial_close_and_reset_grid(be_price, timestamp)
                        self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                        return

        # 포지션 없을 때: 가격이 그리드 범위 밖으로 벗어나면 그리드 재설정
        if self.position is None:
            # 그리드 범위: 기준가 ± (GRID_RANGE_PCT / 2)
            half_range = GRID_RANGE_PCT / 2  # 2.5%
            upper_bound = self.grid_center * (1 + half_range)
            lower_bound = self.grid_center * (1 - half_range)

            # LONG만 볼 때: 위로 벗어나면 그리드 재설정
            if TRADE_DIRECTION == 'LONG' and close_price > upper_bound:
                self.grid_center = close_price

            # SHORT만 볼 때: 아래로 벗어나면 그리드 재설정
            elif TRADE_DIRECTION == 'SHORT' and close_price < lower_bound:
                self.grid_center = close_price

            # BOTH일 때: 양쪽 다 보니까 어느 쪽이든 진입 가능 → 재설정 불필요
            # (위로 가면 SHORT 진입, 아래로 가면 LONG 진입)

        # 에쿼티 기록
        current_equity = self.capital
        if self.position and self.total_size > 0:
            if self.position == 'LONG':
                unrealized_pnl = (close_price - self.avg_price) * self.total_size
            else:
                unrealized_pnl = (self.avg_price - close_price) * self.total_size
            current_equity += unrealized_pnl

        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': current_equity
        })

    def _check_next_level_after_close(self, close_price: float):
        """봉 마감 후 다음 레벨 체결 방법 결정"""
        if self.position is None or self.current_level >= MAX_ENTRY_LEVEL:
            return

        next_level = self.current_level
        next_limit_price = self.get_level_price(next_level, self.position)

        if self.position == 'LONG':
            # close가 다음 지정가보다 이미 아래면 → 다음 봉 open에 시장가
            if close_price <= next_limit_price:
                self.need_market_entry = True
                self.pending_limit_price = None
            else:
                # 아직 안 닿음 → 지정가 대기
                self.pending_limit_price = next_limit_price
                self.need_market_entry = False

        else:  # SHORT
            # close가 다음 지정가보다 이미 위면 → 다음 봉 open에 시장가
            if close_price >= next_limit_price:
                self.need_market_entry = True
                self.pending_limit_price = None
            else:
                # 아직 안 닿음 → 지정가 대기
                self.pending_limit_price = next_limit_price
                self.need_market_entry = False

    def run(self):
        """백테스트 실행"""
        print("=" * 60)
        print("Grid Martingale Backtest V3_2 (Level 4 손절)")
        print("=" * 60)
        print(f"Period: {START_DATE} ~ {END_DATE}")
        print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
        print(f"Trade Direction: {TRADE_DIRECTION}")
        print(f"Leverage LONG: {LEVERAGE_LONG}x / SHORT: {LEVERAGE_SHORT}x")
        print(f"Grid Range: ±{GRID_RANGE_PCT*100:.1f}%")
        print(f"Level Distances: {[f'{d*100:.1f}%' for d in LEVEL_DISTANCES]} / SL: {SL_DISTANCE*100:.1f}%")
        print(f"Entry Ratios: {[f'{r*100:.0f}%' for r in ENTRY_RATIOS]}")
        print(f"Take Profit (Lv1): {TP_PCT*100:.2f}%")
        print(f"Break Even (Lv2+): {BE_PCT*100:.3f}% (덜어내기)")
        print(f"Maker Fee: {MAKER_FEE*100:.4f}% / Taker Fee: {TAKER_FEE*100:.4f}%")
        print("=" * 60)

        # 데이터 필터링
        df_filtered = self.df[
            (self.df['timestamp'] >= START_DATE) &
            (self.df['timestamp'] <= END_DATE)
        ].copy()

        print(f"Total bars: {len(df_filtered):,}")
        print()

        # 봉 순회
        for idx in range(len(df_filtered)):
            row = df_filtered.iloc[idx]
            self.process_bar(idx, row)

            if self.capital <= 0:
                print(f"⚠️ BANKRUPT at {row['timestamp']}")
                break

        # 마지막 포지션 강제 청산
        if self.position is not None:
            last_row = df_filtered.iloc[-1]
            self.close_position(last_row['Close'], 'END', last_row['timestamp'], is_market=True)

        self.print_results()
        self.save_results()

    def print_results(self):
        """결과 출력"""
        print()
        print("=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)

        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        print(f"Final Capital: ${final_capital:,.2f}")
        print(f"Total Return: {total_return:+.2f}%")
        print()
        print(f"Total Trades: {self.total_trades}")
        print(f"Winning Trades: {self.winning_trades}")
        print(f"Losing Trades: {self.losing_trades}")

        if self.total_trades > 0:
            win_rate = self.winning_trades / self.total_trades * 100
            print(f"Win Rate: {win_rate:.1f}%")

        print()
        print("-" * 40)
        print("LONG/SHORT 별 통계")
        print("-" * 40)

        long_total = self.long_wins + self.long_losses
        if long_total > 0:
            long_win_rate = self.long_wins / long_total * 100
            print(f"LONG  - Total: {long_total}, Wins: {self.long_wins}, Losses: {self.long_losses}, Win Rate: {long_win_rate:.1f}%")
        else:
            print(f"LONG  - Total: 0")

        short_total = self.short_wins + self.short_losses
        if short_total > 0:
            short_win_rate = self.short_wins / short_total * 100
            print(f"SHORT - Total: {short_total}, Wins: {self.short_wins}, Losses: {self.short_losses}, Win Rate: {short_win_rate:.1f}%")
        else:
            print(f"SHORT - Total: 0")

        print("-" * 40)

        # Level 4 통계
        level4_total = self.level4_wins + self.level4_losses
        if level4_total > 0:
            level4_win_rate = self.level4_wins / level4_total * 100
            print(f"LV4   - Total: {level4_total}, Wins: {self.level4_wins}, Losses: {self.level4_losses}, Win Rate: {level4_win_rate:.1f}%")
        else:
            print(f"LV4   - Total: 0")

        print("-" * 40)
        print()
        print(f"Max Level Reached: {self.max_level_reached}")

        if self.equity_curve:
            equities = [e['equity'] for e in self.equity_curve]
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100
                if dd > max_dd:
                    max_dd = dd
            print(f"Max Drawdown: {max_dd:.2f}%")

        print("=" * 60)

    def save_results(self):
        """결과 저장"""
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv('trades_grid_martingale_3_2.csv', index=False)
            print(f"Trades saved to trades_grid_martingale_3_2.csv")

        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv('equity_grid_martingale_3_2.csv', index=False)
            print(f"Equity curve saved to equity_grid_martingale_3_2.csv")


# ================================================================================
# 메인
# ================================================================================

def main():
    print(f"Loading data from {DATA_FILE}...")
    df = pd.read_csv(DATA_FILE)

    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    elif 'Open time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['Open time'], unit='ms')

    if 'Open' not in df.columns:
        df = df.rename(columns={
            'Open time': 'timestamp',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })

    print(f"Data loaded: {len(df):,} rows")
    print(f"Date range: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print()

    backtester = GridMartingaleBacktesterV3(df)
    backtester.run()


if __name__ == '__main__':
    main()

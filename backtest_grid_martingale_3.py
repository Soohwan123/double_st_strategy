"""
Grid Martingale Backtest Strategy V3 - Realistic Version

전략 개요 (현실적 시뮬레이션):
- 현재가 기준 ±2%에만 지정가 주문 (1단계)
- 먼저 체결되는 방향으로 포지션 확정
- 다음 레벨 체결 판단: 봉 close 기준
  - close가 다음 지정가를 이미 지나갔으면 → 다음 봉 open에 시장가 체결
  - close가 다음 지정가를 안 지나갔으면 → 지정가 대기
- 매 봉 제일 먼저 익절 가능한지 체크
- 5단계 전부 체결 후 손절 활성화

사용법:
    python backtest_grid_martingale_3.py
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
START_DATE = '2024-01-11'
END_DATE = '2025-12-31'

# 자본 설정
INITIAL_CAPITAL = 1000.0  # USDT
LEVERAGE_LONG = 5   # LONG 레버리지 (파라미터)
LEVERAGE_SHORT = 3  # SHORT 레버리지 (파라미터)

# 그리드 설정
GRID_RANGE_PCT = 0.050  # ±5% 범위
GRID_LEVELS = 4  # 4단계
# GRID_LEVELS = 5  # 5단계
GRID_INTERVAL_PCT = GRID_RANGE_PCT / GRID_LEVELS  # 1.25% 간격

# 진입 비율 (각 단계별 자본 대비 %)
ENTRY_RATIOS = [0.05, 0.10, 0.30, 0.55]  # 1%, 2%, 6%, 18%, 73%
# ENTRY_RATIOS = [0.01, 0.02, 0.06, 0.18, 0.73]  # 1%, 2%, 6%, 18%, 73%

# 익절/손절 설정
TP_PCT = 0.0035  # 익절: 평단가 +0.75% (파라미터)
SL_PCT = 0.01  # 손절: 평단가 -1% (5단계 전부 체결 후) (파라미터)

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
        self.level_prices = [None, None, None, None, None]  # 각 레벨 진입가격
        self.entry_fees = 0.0  # 누적 진입 수수료

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
        """레벨별 가격 계산"""
        if direction == 'LONG':
            return self.grid_center * (1 - GRID_INTERVAL_PCT * (level + 1))
        else:  # SHORT
            return self.grid_center * (1 + GRID_INTERVAL_PCT * (level + 1))

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

        # 마지막 레벨(4단계)은 레버리지 2배
        if self.current_level == GRID_LEVELS - 1:
            leverage = leverage

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
        self.current_level += 1

        # 최대 레벨 기록
        if self.current_level > self.max_level_reached:
            self.max_level_reached = self.current_level

        return fee

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
        if self.current_level >= GRID_LEVELS:
            if self.position == 'LONG':
                sl_target_price = self.avg_price * (1 - SL_PCT)
            else:  # SHORT
                sl_target_price = self.avg_price * (1 + SL_PCT)

        # 거래 기록
        is_win = net_pnl > 0
        self.trades.append({
            'timestamp': timestamp,
            'direction': self.position,
            'grid_center': self.grid_center,
            'entry_price': self.avg_price,
            'exit_price': exit_price,
            'sl_target_price': sl_target_price,
            'size': self.total_size,
            'level': self.current_level,
            'pnl': net_pnl,
            'reason': reason,
            'balance': self.capital,
            'level1_price': self.level_prices[0],
            'level2_price': self.level_prices[1],
            'level3_price': self.level_prices[2],
            'level4_price': self.level_prices[3],
            'level5_price': self.level_prices[4]
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
        if self.current_level >= GRID_LEVELS:
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
        self.level_prices = [None, None, None, None, None]  # 레벨 가격 리셋
        self.entry_fees = 0.0  # 진입 수수료 리셋

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
        # Step 0: 이전 봉에서 시장가 체결 필요한 경우 (open 가격에 체결)
        # ============================================================
        if self.need_market_entry and self.position is not None and self.current_level < GRID_LEVELS:
            ratio = ENTRY_RATIOS[self.current_level]
            self.execute_entry(open_price, ratio, self.position, is_market=True)
            self.need_market_entry = False

        # ============================================================
        # Step 1: 익절 체크 (제일 먼저!)
        # ============================================================
        if self.position is not None:
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

        # ============================================================
        # Step 2: 손절 체크 (전 레벨 체결 후)
        # - close가 손절가 밖이면 → close에 시장가 손절
        # - close가 손절가 안이면 → 홀딩, 이후 low/high 터치 시 손절가에 청산
        # ============================================================
        if self.position is not None and self.current_level >= GRID_LEVELS:
            if self.position == 'LONG':
                sl_price = self.avg_price * (1 - SL_PCT)
                # close가 손절가 밖 (이미 돌파) → close에 시장가 손절
                if close_price <= sl_price:
                    new_center = self.close_position(close_price, 'SL', timestamp, is_market=True)
                    self.setup_grid(new_center)
                    self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                    return
                # close가 손절가 안이지만 low가 터치 → 손절가에 청산
                elif low_price <= sl_price:
                    new_center = self.close_position(sl_price, 'SL', timestamp, is_market=False)
                    self.setup_grid(new_center)
                    self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                    return
            else:  # SHORT
                sl_price = self.avg_price * (1 + SL_PCT)
                # close가 손절가 밖 (이미 돌파) → close에 시장가 손절
                if close_price >= sl_price:
                    new_center = self.close_position(close_price, 'SL', timestamp, is_market=True)
                    self.setup_grid(new_center)
                    self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                    return
                # close가 손절가 안이지만 high가 터치 → 손절가에 청산
                elif high_price >= sl_price:
                    new_center = self.close_position(sl_price, 'SL', timestamp, is_market=False)
                    self.setup_grid(new_center)
                    self.equity_curve.append({'timestamp': timestamp, 'equity': self.capital})
                    return

        # ============================================================
        # Step 3: 포지션 없음 - 첫 진입 체크
        # ============================================================
        if self.position is None:
            long_limit = self.get_level_price(0, 'LONG')   # -2%
            short_limit = self.get_level_price(0, 'SHORT')  # +2%

            # LONG 체결 (가격이 아래로)
            if low_price <= long_limit:
                self.position = 'LONG'
                self.execute_entry(long_limit, ENTRY_RATIOS[0], 'LONG', is_market=False)
                # close 기준으로 다음 레벨 체크
                self._check_next_level_after_close(close_price)

            # SHORT 체결 (가격이 위로)
            elif high_price >= short_limit:
                self.position = 'SHORT'
                self.execute_entry(short_limit, ENTRY_RATIOS[0], 'SHORT', is_market=False)
                # close 기준으로 다음 레벨 체크
                self._check_next_level_after_close(close_price)

        # ============================================================
        # Step 4: 포지션 있음 - 추가 진입 체크 (지정가 대기 중인 경우)
        # ============================================================
        elif self.current_level < GRID_LEVELS:
            if self.pending_limit_price is not None:
                # 지정가 체결 체크
                if self.position == 'LONG' and low_price <= self.pending_limit_price:
                    ratio = ENTRY_RATIOS[self.current_level]
                    self.execute_entry(self.pending_limit_price, ratio, 'LONG', is_market=False)
                    self.pending_limit_price = None
                    # close 기준으로 다음 레벨 체크
                    self._check_next_level_after_close(close_price)

                elif self.position == 'SHORT' and high_price >= self.pending_limit_price:
                    ratio = ENTRY_RATIOS[self.current_level]
                    self.execute_entry(self.pending_limit_price, ratio, 'SHORT', is_market=False)
                    self.pending_limit_price = None
                    # close 기준으로 다음 레벨 체크
                    self._check_next_level_after_close(close_price)

                else:
                    # 지정가 미체결 - close 기준으로 다음 봉 행동 결정
                    self._check_next_level_after_close(close_price)
            else:
                # 지정가 없음 - close 기준으로 다음 봉 행동 결정
                self._check_next_level_after_close(close_price)

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
        if self.position is None or self.current_level >= GRID_LEVELS:
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
        print("Grid Martingale Backtest V3 (Realistic)")
        print("=" * 60)
        print(f"Period: {START_DATE} ~ {END_DATE}")
        print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
        print(f"Leverage LONG: {LEVERAGE_LONG}x / SHORT: {LEVERAGE_SHORT}x")
        print(f"Grid Range: ±{GRID_RANGE_PCT*100:.1f}%")
        print(f"Grid Interval: {GRID_INTERVAL_PCT*100:.1f}%")
        print(f"Entry Ratios: {[f'{r*100:.0f}%' for r in ENTRY_RATIOS]}")
        print(f"Take Profit: {TP_PCT*100:.2f}%")
        print(f"Stop Loss: {SL_PCT*100:.1f}% (after all levels)")
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
            trades_df.to_csv('trades_grid_martingale_3.csv', index=False)
            print(f"Trades saved to trades_grid_martingale_3.csv")

        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv('equity_grid_martingale_3.csv', index=False)
            print(f"Equity curve saved to equity_grid_martingale_3.csv")


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

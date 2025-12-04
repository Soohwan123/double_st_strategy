"""
Grid Martingale Backtest Strategy V1

전략 개요:
- 현재가 기준 ±10% 범위에 5단계 지정가 주문
- 진입 비율: 1%, 2%, 6%, 18%, 54% (총 81%)
- 먼저 터치하는 방향으로 포지션 방향 결정
- 평단가 +2% 도달 시 익절
- 5단계 전부 체결 후 평단가 -1% 시 손절
- 익절/손절 후 해당 가격 기준으로 리셋

사용법:
    python backtest_grid_martingale.py
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
START_DATE = '2023-01-01'
END_DATE = '2025-12-31'

# 자본 설정
INITIAL_CAPITAL = 1000.0  # USDT
LEVERAGE_LONG = 5   # LONG 레버리지 (파라미터)
LEVERAGE_SHORT = 4  # SHORT 레버리지 (파라미터)

# 그리드 설정
GRID_RANGE_PCT = 0.050  # ±5% 범위
GRID_LEVELS = 5  # 5단계
GRID_INTERVAL_PCT = GRID_RANGE_PCT / GRID_LEVELS  # 2% 간격

# 진입 비율 (각 단계별 자본 대비 %)
ENTRY_RATIOS = [0.01, 0.02, 0.06, 0.18, 0.73]  # 1%, 2%, 6%, 18%, 73%

# 익절/손절 설정
TP_PCT = 0.0035  # 익절: 평단가 +0.75% (파라미터)
SL_PCT = 0.005  # 손절: 평단가 -1% (5단계 전부 체결 후) (파라미터)

# 수수료
FEE_RATE = 0.000275  # 0.0275%

# ================================================================================
# 백테스터 클래스
# ================================================================================

class GridMartingaleBacktester:
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

        # 그리드 상태
        self.grid_center = None  # 그리드 기준 가격
        self.long_orders = []  # [(price, ratio), ...]
        self.short_orders = []  # [(price, ratio), ...]

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

    def setup_grid(self, center_price: float):
        """그리드 주문 설정"""
        self.grid_center = center_price
        self.long_orders = []
        self.short_orders = []

        for i in range(GRID_LEVELS):
            # 아래로 LONG 주문 (가격 하락 시 매수)
            long_price = center_price * (1 - GRID_INTERVAL_PCT * (i + 1))
            self.long_orders.append((long_price, ENTRY_RATIOS[i]))

            # 위로 SHORT 주문 (가격 상승 시 매도)
            short_price = center_price * (1 + GRID_INTERVAL_PCT * (i + 1))
            self.short_orders.append((short_price, ENTRY_RATIOS[i]))

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

    def execute_entry(self, price: float, ratio: float, direction: str):
        """진입 실행"""
        # 진입 금액 계산 (방향별 레버리지 적용)
        leverage = self.get_leverage(direction)
        entry_value = self.capital * ratio * leverage

        # BTC 수량 계산
        btc_amount = entry_value / price

        # 수수료 차감
        fee = entry_value * FEE_RATE

        # 진입 기록
        self.entries.append((price, btc_amount))
        self.total_size += btc_amount
        self.avg_price = self.calculate_avg_price()

        # 레벨별 진입가격 저장
        self.level_prices[self.current_level] = price
        self.current_level += 1

        # 최대 레벨 기록
        if self.current_level > self.max_level_reached:
            self.max_level_reached = self.current_level

        return fee

    def close_position(self, exit_price: float, reason: str, timestamp):
        """포지션 청산"""
        if self.position is None or self.total_size == 0:
            return 0.0

        # PnL 계산 (레버리지는 이미 total_size에 반영됨)
        if self.position == 'LONG':
            pnl = (exit_price - self.avg_price) * self.total_size
        else:  # SHORT
            pnl = (self.avg_price - exit_price) * self.total_size

        # 청산 수수료
        exit_value = exit_price * self.total_size
        fee = exit_value * FEE_RATE

        # 순 PnL
        net_pnl = pnl - fee

        # 자본 업데이트
        self.capital += net_pnl

        # 거래 기록
        is_win = net_pnl > 0
        self.trades.append({
            'timestamp': timestamp,
            'direction': self.position,
            'grid_center': self.grid_center,
            'entry_price': self.avg_price,
            'exit_price': exit_price,
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

        # 포지션 리셋
        old_position = self.position
        self.position = None
        self.entries = []
        self.avg_price = 0.0
        self.total_size = 0.0
        self.current_level = 0
        self.level_prices = [None, None, None, None, None]  # 레벨 가격 리셋

        return exit_price  # 다음 그리드 기준 가격으로 반환

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
        # Case 1: 포지션 없음 - 첫 진입 체크
        # ============================================================
        if self.position is None:
            # LONG 방향 체크 (가격이 아래로)
            long_triggered = False
            for i, (order_price, ratio) in enumerate(self.long_orders):
                if low_price <= order_price:
                    long_triggered = True
                    self.position = 'LONG'
                    self.short_orders = []  # 반대 주문 취소
                    self.execute_entry(order_price, ratio, 'LONG')
                    break

            # SHORT 방향 체크 (가격이 위로)
            if not long_triggered:
                for i, (order_price, ratio) in enumerate(self.short_orders):
                    if high_price >= order_price:
                        self.position = 'SHORT'
                        self.long_orders = []  # 반대 주문 취소
                        self.execute_entry(order_price, ratio, 'SHORT')
                        break

        # ============================================================
        # Case 2: 포지션 있음 - 추가 진입 / 익절 / 손절 체크
        # ============================================================
        else:
            # 익절가 계산
            if self.position == 'LONG':
                tp_price = self.avg_price * (1 + TP_PCT)
                sl_price = self.avg_price * (1 - SL_PCT) if self.current_level >= GRID_LEVELS else None
            else:  # SHORT
                tp_price = self.avg_price * (1 - TP_PCT)
                sl_price = self.avg_price * (1 + SL_PCT) if self.current_level >= GRID_LEVELS else None

            # ----- 익절 체크 -----
            if self.position == 'LONG' and high_price >= tp_price:
                new_center = self.close_position(tp_price, 'TP', timestamp)
                self.setup_grid(new_center)
                self.equity_curve.append({
                    'timestamp': timestamp,
                    'equity': self.capital
                })
                return

            if self.position == 'SHORT' and low_price <= tp_price:
                new_center = self.close_position(tp_price, 'TP', timestamp)
                self.setup_grid(new_center)
                self.equity_curve.append({
                    'timestamp': timestamp,
                    'equity': self.capital
                })
                return

            # ----- 손절 체크 (5단계 전부 체결 후) -----
            if sl_price is not None:
                if self.position == 'LONG' and low_price <= sl_price:
                    new_center = self.close_position(sl_price, 'SL', timestamp)
                    self.setup_grid(new_center)
                    self.equity_curve.append({
                        'timestamp': timestamp,
                        'equity': self.capital
                    })
                    return

                if self.position == 'SHORT' and high_price >= sl_price:
                    new_center = self.close_position(sl_price, 'SL', timestamp)
                    self.setup_grid(new_center)
                    self.equity_curve.append({
                        'timestamp': timestamp,
                        'equity': self.capital
                    })
                    return

            # ----- 추가 진입 체크 -----
            if self.current_level < GRID_LEVELS:
                if self.position == 'LONG':
                    # 다음 LONG 레벨 체크
                    next_order_price, next_ratio = self.long_orders[self.current_level]
                    if low_price <= next_order_price:
                        self.execute_entry(next_order_price, next_ratio, 'LONG')

                elif self.position == 'SHORT':
                    # 다음 SHORT 레벨 체크
                    next_order_price, next_ratio = self.short_orders[self.current_level]
                    if high_price >= next_order_price:
                        self.execute_entry(next_order_price, next_ratio, 'SHORT')

        # 에쿼티 기록 (매 봉마다)
        current_equity = self.capital
        if self.position and self.total_size > 0:
            # 미실현 PnL 포함 (레버리지는 이미 total_size에 반영됨)
            if self.position == 'LONG':
                unrealized_pnl = (close_price - self.avg_price) * self.total_size
            else:
                unrealized_pnl = (self.avg_price - close_price) * self.total_size
            current_equity += unrealized_pnl

        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': current_equity
        })

    def run(self):
        """백테스트 실행"""
        print("=" * 60)
        print("Grid Martingale Backtest V1")
        print("=" * 60)
        print(f"Period: {START_DATE} ~ {END_DATE}")
        print(f"Initial Capital: ${INITIAL_CAPITAL:,.2f}")
        print(f"Leverage LONG: {LEVERAGE_LONG}x / SHORT: {LEVERAGE_SHORT}x")
        print(f"Grid Range: ±{GRID_RANGE_PCT*100:.1f}%")
        print(f"Grid Interval: {GRID_INTERVAL_PCT*100:.1f}%")
        print(f"Entry Ratios: {[f'{r*100:.0f}%' for r in ENTRY_RATIOS]}")
        print(f"Take Profit: {TP_PCT*100:.1f}%")
        print(f"Stop Loss: {SL_PCT*100:.1f}% (after all levels)")
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

            # 파산 체크
            if self.capital <= 0:
                print(f"⚠️ BANKRUPT at {row['timestamp']}")
                break

        # 마지막 포지션 강제 청산
        if self.position is not None:
            last_row = df_filtered.iloc[-1]
            self.close_position(last_row['Close'], 'END', last_row['timestamp'])

        # 결과 출력
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

        # LONG 통계
        long_total = self.long_wins + self.long_losses
        if long_total > 0:
            long_win_rate = self.long_wins / long_total * 100
            print(f"LONG  - Total: {long_total}, Wins: {self.long_wins}, Losses: {self.long_losses}, Win Rate: {long_win_rate:.1f}%")
        else:
            print(f"LONG  - Total: 0")

        # SHORT 통계
        short_total = self.short_wins + self.short_losses
        if short_total > 0:
            short_win_rate = self.short_wins / short_total * 100
            print(f"SHORT - Total: {short_total}, Wins: {self.short_wins}, Losses: {self.short_losses}, Win Rate: {short_win_rate:.1f}%")
        else:
            print(f"SHORT - Total: 0")

        print("-" * 40)
        print()
        print(f"Max Level Reached: {self.max_level_reached}")

        # 최대 손실 (MDD)
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
        # 거래 내역 저장
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv('trades_grid_martingale.csv', index=False)
            print(f"Trades saved to trades_grid_martingale.csv")

        # 에쿼티 커브 저장
        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv('equity_grid_martingale.csv', index=False)
            print(f"Equity curve saved to equity_grid_martingale.csv")


# ================================================================================
# 메인
# ================================================================================

def main():
    # 데이터 로드
    print(f"Loading data from {DATA_FILE}...")
    df = pd.read_csv(DATA_FILE)

    # timestamp 변환
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    elif 'Open time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['Open time'], unit='ms')

    # 컬럼명 정리
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

    # 백테스터 실행
    backtester = GridMartingaleBacktester(df)
    backtester.run()


if __name__ == '__main__':
    main()

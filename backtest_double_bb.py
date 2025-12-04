"""
Double Bollinger Band Strategy - Backtester

전략 설명:
- 5분봉 기준 BB(20,2)와 BB(4,4) 동시 터치 시 진입
- LONG: Low가 두 lower band 동시 터치 → bb_lower_4_4 값에 진입
- SHORT: High가 두 upper band 동시 터치 → bb_upper_4_4 값에 진입
- 익절: 진입가의 N% 거리
- 본절 스탑로스: 진입 봉 마감 후 다음 봉부터 활성화

사용법:
    python backtest_double_bb.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG: 파라미터 설정 (자유롭게 수정 가능)
# ================================================================================

# 백테스트 기간
START_DATE = '2025-10-01'
END_DATE = '2025-11-30'

# 데이터 파일 경로
DATA_FILE = 'backtest_data/BTCUSDT_double_bb_2019_10_11.csv'

# 초기 자본 및 레버리지
INITIAL_CAPITAL = 1000.0  # USDT
LEVERAGE = 10             # 레버리지 배수

# 포지션 사이징
POSITION_SIZE_PCT = 1.0   # 자본의 몇 %를 사용할지 (1.0 = 100%)

# 익절 설정
TAKE_PROFIT_PCT = 0.003   # 익절 비율 (0.003 = 0.3%)

# 수수료 설정
FEE_RATE = 0.000275         # 수수료율 (0.04% = 테이커 기준)

# 결과 저장
OUTPUT_CSV = 'backtest_results_double_bb.csv'
TRADES_CSV = 'trades_double_bb.csv'

# ================================================================================
# 전략 클래스
# ================================================================================

class DoubleBBBacktester:
    def __init__(self, data_file, initial_capital, leverage, position_size_pct,
                 take_profit_pct, fee_rate, start_date, end_date):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.position_size_pct = position_size_pct
        self.take_profit_pct = take_profit_pct
        self.fee_rate = fee_rate
        self.start_date = start_date
        self.end_date = end_date

        # 상태 변수
        self.capital = initial_capital
        self.position = None  # {'direction': 'LONG'/'SHORT', 'entry_price': float,
                              #  'size': float, 'entry_time': timestamp, 'tp_price': float,
                              #  'sl_active': bool, 'entry_bar_closed': bool}
        self.trades = []
        self.equity_curve = []

    def load_data(self):
        """데이터 로드 및 필터링"""
        print(f"📂 데이터 로드: {self.data_file}")

        df = pd.read_csv(self.data_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # 기간 필터링
        df = df[(df['timestamp'] >= self.start_date) &
                (df['timestamp'] <= self.end_date)]

        df = df.reset_index(drop=True)

        print(f"   기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
        print(f"   데이터 수: {len(df):,} rows")

        return df

    def check_long_entry(self, row):
        """
        LONG 진입 조건 확인
        - Low가 bb_lower_20_2와 bb_lower_4_4 둘 다 터치
        - 진입가: 두 lower band 중 더 낮은 값 (더 유리한 가격)
        """
        low = row['Low']
        bb_lower_20_2 = row['bb_lower_20_2']
        bb_lower_4_4 = row['bb_lower_4_4']

        # 두 밴드 모두 터치 (Low가 두 lower band 이하)
        if low <= bb_lower_20_2 and low <= bb_lower_4_4:
            # 더 낮은 값에 진입 (롱일 때 더 유리)
            entry_price = min(bb_lower_20_2, bb_lower_4_4)
            return True, entry_price
        return False, None

    def check_short_entry(self, row):
        """
        SHORT 진입 조건 확인
        - High가 bb_upper_20_2와 bb_upper_4_4 둘 다 터치
        - 진입가: 두 upper band 중 더 높은 값 (더 유리한 가격)
        """
        high = row['High']
        bb_upper_20_2 = row['bb_upper_20_2']
        bb_upper_4_4 = row['bb_upper_4_4']

        # 두 밴드 모두 터치 (High가 두 upper band 이상)
        if high >= bb_upper_20_2 and high >= bb_upper_4_4:
            # 더 높은 값에 진입 (숏일 때 더 유리)
            entry_price = max(bb_upper_20_2, bb_upper_4_4)
            return True, entry_price
        return False, None

    def calculate_position_size(self, entry_price):
        """포지션 크기 계산"""
        # 사용 가능 자본
        available_capital = self.capital * self.position_size_pct

        # 레버리지 적용 포지션 가치
        position_value = available_capital * self.leverage

        # BTC 수량
        size = position_value / entry_price

        return size, position_value

    def open_position(self, direction, entry_price, entry_time):
        """포지션 오픈"""
        size, position_value = self.calculate_position_size(entry_price)

        # 진입 수수료
        entry_fee = position_value * self.fee_rate

        # 익절가 계산
        if direction == 'LONG':
            tp_price = entry_price * (1 + self.take_profit_pct)
        else:  # SHORT
            tp_price = entry_price * (1 - self.take_profit_pct)

        self.position = {
            'direction': direction,
            'entry_price': entry_price,
            'size': size,
            'position_value': position_value,
            'entry_time': entry_time,
            'tp_price': tp_price,
            'entry_bar_idx': None,  # 진입 봉 인덱스 (process_bar에서 설정)
            'entry_fee': entry_fee
        }

        # 수수료 차감
        self.capital -= entry_fee

        return True

    def close_position(self, exit_price, exit_time, exit_reason):
        """포지션 청산"""
        if self.position is None:
            return

        direction = self.position['direction']
        entry_price = self.position['entry_price']
        size = self.position['size']
        position_value = self.position['position_value']
        entry_fee = self.position['entry_fee']

        # PnL 계산
        if direction == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:  # SHORT
            pnl_pct = (entry_price - exit_price) / entry_price

        # 레버리지 적용 PnL
        gross_pnl = position_value * pnl_pct

        # 청산 수수료 (포지션 가치에 대해 고정)
        exit_fee = position_value * self.fee_rate

        # 순 PnL
        net_pnl = gross_pnl - exit_fee - entry_fee

        # 자본 업데이트
        self.capital += net_pnl

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': exit_time,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'size': size,
            'position_value': position_value,
            'pnl_pct': pnl_pct * 100,  # 퍼센트로
            'gross_pnl': gross_pnl,
            'entry_fee': entry_fee,
            'exit_fee': exit_fee,
            'net_pnl': net_pnl,
            'exit_reason': exit_reason,
            'capital_after': self.capital
        }
        self.trades.append(trade)

        # 포지션 초기화
        self.position = None

        return trade

    def process_bar(self, idx, row, prev_row):
        """
        각 봉 처리

        로직:
        1. 포지션이 있으면 청산 조건 확인
        2. 포지션이 없으면 진입 조건 확인

        본절 스탑로스:
        - 진입 봉(entry_bar_idx == idx): 익절만 확인
        - 다음 봉부터(idx > entry_bar_idx): 본절 스탑로스 활성화
        """
        timestamp = row['timestamp']
        open_price = row['Open']
        high = row['High']
        low = row['Low']
        close = row['Close']

        # 포지션이 있는 경우 - 청산 로직
        if self.position is not None:
            direction = self.position['direction']
            entry_price = self.position['entry_price']
            tp_price = self.position['tp_price']
            entry_bar_idx = self.position['entry_bar_idx']

            # 본절 스탑로스 활성화 여부: 진입 봉 다음 봉부터
            sl_active = (idx > entry_bar_idx)

            exit_price = None
            exit_reason = None

            if direction == 'LONG':
                if sl_active:
                    # 시가가 이미 손절라인 아래 → 손절 (갭 다운)
                    if open_price < entry_price:
                        exit_price = open_price
                        exit_reason = 'STOP_LOSS'
                    # 익절과 본절 둘 다 가능한 경우
                    elif high >= tp_price and low <= entry_price:
                        # 시가 기준으로 판단: 시가가 진입가 위면 익절 먼저 시도
                        if open_price >= entry_price:
                            exit_price = tp_price
                            exit_reason = 'TAKE_PROFIT'
                        else:
                            exit_price = entry_price
                            exit_reason = 'BREAK_EVEN'
                    # 익절만 해당
                    elif high >= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TAKE_PROFIT'
                    # 본절만 해당
                    elif low <= entry_price:
                        exit_price = entry_price
                        exit_reason = 'BREAK_EVEN'
                else:
                    # 진입 봉 - 익절만 확인
                    if high >= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TAKE_PROFIT'

            else:  # SHORT
                if sl_active:
                    # 시가가 이미 손절라인 위 → 손절 (갭 업)
                    if open_price > entry_price:
                        exit_price = open_price
                        exit_reason = 'STOP_LOSS'
                    # 익절과 본절 둘 다 가능한 경우
                    elif low <= tp_price and high >= entry_price:
                        if open_price <= entry_price:
                            exit_price = tp_price
                            exit_reason = 'TAKE_PROFIT'
                        else:
                            exit_price = entry_price
                            exit_reason = 'BREAK_EVEN'
                    # 익절만 해당
                    elif low <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TAKE_PROFIT'
                    # 본절만 해당
                    elif high >= entry_price:
                        exit_price = entry_price
                        exit_reason = 'BREAK_EVEN'
                else:
                    # 진입 봉 - 익절만 확인
                    if low <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TAKE_PROFIT'

            # 청산 실행
            if exit_price is not None:
                self.close_position(exit_price, timestamp, exit_reason)

        # 포지션이 없는 경우 - 진입 로직
        if self.position is None:
            # LONG 진입 확인
            long_signal, long_entry_price = self.check_long_entry(row)
            if long_signal:
                self.open_position('LONG', long_entry_price, timestamp)
                self.position['entry_bar_idx'] = idx  # 진입 봉 인덱스 저장
                return

            # SHORT 진입 확인
            short_signal, short_entry_price = self.check_short_entry(row)
            if short_signal:
                self.open_position('SHORT', short_entry_price, timestamp)
                self.position['entry_bar_idx'] = idx  # 진입 봉 인덱스 저장
                return

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("🚀 Double BB Strategy Backtest")
        print("=" * 80)

        # 설정 출력
        print(f"\n📊 설정:")
        print(f"   초기 자본: ${self.initial_capital:,.2f}")
        print(f"   레버리지: {self.leverage}x")
        print(f"   포지션 크기: {self.position_size_pct * 100:.0f}%")
        print(f"   익절 비율: {self.take_profit_pct * 100:.2f}%")
        print(f"   수수료율: {self.fee_rate * 100:.4f}%")

        # 데이터 로드
        df = self.load_data()

        if len(df) == 0:
            print("❌ 데이터가 없습니다.")
            return

        print(f"\n⏳ 백테스트 실행 중...")

        # 봉별 처리
        prev_row = None
        for idx in range(len(df)):
            row = df.iloc[idx]
            self.process_bar(idx, row, prev_row)

            # 자본 기록
            unrealized_pnl = 0
            if self.position is not None:
                if self.position['direction'] == 'LONG':
                    unrealized_pnl = self.position['position_value'] * \
                        (row['Close'] - self.position['entry_price']) / self.position['entry_price']
                else:
                    unrealized_pnl = self.position['position_value'] * \
                        (self.position['entry_price'] - row['Close']) / self.position['entry_price']

            self.equity_curve.append({
                'timestamp': row['timestamp'],
                'capital': self.capital,
                'equity': self.capital + unrealized_pnl
            })

            prev_row = row

        # 마지막 포지션 청산 (있다면)
        if self.position is not None:
            last_row = df.iloc[-1]
            self.close_position(last_row['Close'], last_row['timestamp'], 'END_OF_DATA')

        # 결과 출력
        self.print_results()

        # 결과 저장
        self.save_results()

        return self.trades, self.equity_curve

    def print_results(self):
        """결과 출력"""
        print("\n" + "=" * 80)
        print("📈 백테스트 결과")
        print("=" * 80)

        if len(self.trades) == 0:
            print("❌ 거래 없음")
            return

        trades_df = pd.DataFrame(self.trades)

        # 기본 통계
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['net_pnl'] > 0])
        losing_trades = len(trades_df[trades_df['net_pnl'] <= 0])
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

        # 수익률
        total_return = (self.capital - self.initial_capital) / self.initial_capital * 100

        # PnL 통계
        total_pnl = trades_df['net_pnl'].sum()
        avg_pnl = trades_df['net_pnl'].mean()
        max_win = trades_df['net_pnl'].max()
        max_loss = trades_df['net_pnl'].min()

        # 승/패 평균
        avg_win = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['net_pnl'] <= 0]['net_pnl'].mean() if losing_trades > 0 else 0

        # Profit Factor
        gross_profit = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(trades_df[trades_df['net_pnl'] <= 0]['net_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # 청산 사유별 통계
        exit_reasons = trades_df['exit_reason'].value_counts()

        # 방향별 통계
        long_trades = trades_df[trades_df['direction'] == 'LONG']
        short_trades = trades_df[trades_df['direction'] == 'SHORT']

        # 최대 낙폭 (MDD)
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].min()

        print(f"\n💰 자본 변화:")
        print(f"   초기 자본: ${self.initial_capital:,.2f}")
        print(f"   최종 자본: ${self.capital:,.2f}")
        print(f"   총 수익률: {total_return:+.2f}%")
        print(f"   총 PnL: ${total_pnl:+,.2f}")

        print(f"\n📊 거래 통계:")
        print(f"   총 거래 수: {total_trades}")
        print(f"   승리: {winning_trades} ({win_rate:.1f}%)")
        print(f"   패배: {losing_trades} ({100-win_rate:.1f}%)")
        print(f"   Profit Factor: {profit_factor:.2f}")

        print(f"\n💵 PnL 통계:")
        print(f"   평균 PnL: ${avg_pnl:+,.2f}")
        print(f"   평균 승리: ${avg_win:+,.2f}")
        print(f"   평균 패배: ${avg_loss:+,.2f}")
        print(f"   최대 승리: ${max_win:+,.2f}")
        print(f"   최대 패배: ${max_loss:+,.2f}")

        print(f"\n📉 리스크:")
        print(f"   최대 낙폭 (MDD): {max_drawdown:.2f}%")

        print(f"\n🎯 청산 사유:")
        for reason, count in exit_reasons.items():
            pct = count / total_trades * 100
            print(f"   {reason}: {count} ({pct:.1f}%)")

        print(f"\n📈 방향별 통계:")
        if len(long_trades) > 0:
            long_win_rate = len(long_trades[long_trades['net_pnl'] > 0]) / len(long_trades) * 100
            print(f"   LONG: {len(long_trades)}건, 승률 {long_win_rate:.1f}%, PnL ${long_trades['net_pnl'].sum():+,.2f}")
        if len(short_trades) > 0:
            short_win_rate = len(short_trades[short_trades['net_pnl'] > 0]) / len(short_trades) * 100
            print(f"   SHORT: {len(short_trades)}건, 승률 {short_win_rate:.1f}%, PnL ${short_trades['net_pnl'].sum():+,.2f}")

    def save_results(self):
        """결과 저장"""
        if len(self.trades) > 0:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(TRADES_CSV, index=False)
            print(f"\n💾 거래 내역 저장: {TRADES_CSV}")

        if len(self.equity_curve) > 0:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv(OUTPUT_CSV, index=False)
            print(f"💾 자본 곡선 저장: {OUTPUT_CSV}")


# ================================================================================
# 메인 실행
# ================================================================================

def main():
    backtester = DoubleBBBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        leverage=LEVERAGE,
        position_size_pct=POSITION_SIZE_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        fee_rate=FEE_RATE,
        start_date=START_DATE,
        end_date=END_DATE
    )

    backtester.run()


if __name__ == "__main__":
    main()

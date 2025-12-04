"""
EMA 크로스 전략 - Backtester

전략 설명:
- EMA(5), EMA(10), EMA(20) 사용
- 가격이 모든 EMA 위에서 종가 마감 → LONG
- 가격이 모든 EMA 아래에서 종가 마감 → SHORT
- 포지션 스위칭 방식 (반대 신호 시 청산 후 진입)

사용법:
    python backtest_ema_strategy.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG: 파라미터 설정
# ================================================================================

# 백테스트 기간
START_DATE = '2022-01-01'
END_DATE = '2023-11-30'

# 데이터 파일 경로
DATA_FILE = 'backtest_data/BTCUSDT_ema_strategy.csv'

# 초기 자본
INITIAL_CAPITAL = 1000.0  # USDT

# 레버리지 설정
LEVERAGE = 1  # 레버리지 배수

# 포지션 사이징
POSITION_SIZE_PCT = 1.0  # 자본의 100% 사용

# 수수료 설정
FEE_RATE = 0.000275  # 수수료율 (0.0275%)

# 결과 저장
OUTPUT_CSV = 'backtest_results_ema_strategy.csv'
TRADES_CSV = 'trades_ema_strategy.csv'


# ================================================================================
# 전략 클래스
# ================================================================================

class EMAStrategyBacktester:
    def __init__(self, data_file, initial_capital, leverage, position_size_pct,
                 fee_rate, start_date, end_date):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.position_size_pct = position_size_pct
        self.fee_rate = fee_rate
        self.start_date = start_date
        self.end_date = end_date

        # 상태 변수
        self.capital = initial_capital
        self.position = None  # {'direction': 'LONG'/'SHORT', 'entry_price': ..., ...}
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

    def open_position(self, direction, entry_price, timestamp):
        """포지션 오픈"""
        position_value = self.capital * self.position_size_pct * self.leverage
        size = position_value / entry_price

        # 진입 수수료
        entry_fee = position_value * self.fee_rate
        self.capital -= entry_fee

        self.position = {
            'direction': direction,
            'entry_price': entry_price,
            'entry_time': timestamp,
            'size': size,
            'position_value': position_value,
            'entry_fee': entry_fee
        }

        print(f"   [{direction}] 진입 @ {entry_price:,.1f} | 포지션: ${position_value:,.0f}")

    def close_position(self, exit_price, timestamp, exit_reason):
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
            gross_pnl = (exit_price - entry_price) * size
        else:
            gross_pnl = (entry_price - exit_price) * size

        # 청산 수수료
        exit_fee = position_value * self.fee_rate

        # 순 PnL
        total_fees = entry_fee + exit_fee
        net_pnl = gross_pnl - exit_fee  # entry_fee는 이미 차감됨

        # 자본 업데이트
        self.capital += gross_pnl - exit_fee

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': timestamp,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'size': size,
            'position_value': position_value,
            'gross_pnl': gross_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'exit_reason': exit_reason,
            'capital_after': self.capital
        }
        self.trades.append(trade)

        pnl_pct = (exit_price / entry_price - 1) * 100 if direction == 'LONG' else (1 - exit_price / entry_price) * 100
        print(f"   [{exit_reason}] {direction} 청산 @ {exit_price:,.1f} | PnL: ${net_pnl:,.2f} ({pnl_pct:+.2f}%)")

        self.position = None

    def process_bar(self, row, idx, df):
        """봉 처리 (LONG ONLY - 매수만)"""
        close_price = row['Close']
        timestamp = row['timestamp']

        long_signal = row.get('long_signal', False)
        short_signal = row.get('short_signal', False)

        # LONG ONLY: 매수 신호 → 진입, 매도 신호 → 청산
        if long_signal:
            if self.position is None:
                # 새 LONG 진입
                print(f"\n🟢 LONG 진입 @ {timestamp}")
                self.open_position('LONG', close_price, timestamp)

        elif short_signal:
            if self.position is not None and self.position['direction'] == 'LONG':
                # LONG 청산 (EMA 아래로 내려감)
                print(f"\n🔴 LONG 청산 @ {timestamp}")
                self.close_position(close_price, timestamp, 'EXIT_BELOW_EMA')

        # 자본 곡선 기록 (미실현 손익 포함)
        if self.position is not None:
            direction = self.position['direction']
            entry_price = self.position['entry_price']
            size = self.position['size']

            if direction == 'LONG':
                unrealized_pnl = (close_price - entry_price) * size
            else:
                unrealized_pnl = (entry_price - close_price) * size

            equity = self.capital + unrealized_pnl
        else:
            equity = self.capital

        self.equity_curve.append({
            'timestamp': timestamp,
            'capital': equity
        })

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("🚀 EMA Strategy 백테스트 시작")
        print("=" * 80)
        print(f"   - 레버리지: {self.leverage}x")
        print(f"   - 포지션 크기: 자본의 {self.position_size_pct*100}%")
        print(f"   - 전략: LONG ONLY (매수만)")
        print(f"   - 진입: 가격 > EMA(5,10,20)")
        print(f"   - 청산: 가격 < EMA(5,10,20)")
        print("=" * 80)

        # 데이터 로드
        df = self.load_data()

        # 신호 통계
        long_count = df['long_signal'].sum() if 'long_signal' in df.columns else 0
        short_count = df['short_signal'].sum() if 'short_signal' in df.columns else 0
        print(f"\n📊 신호 통계:")
        print(f"   LONG 신호: {long_count}개")
        print(f"   SHORT 신호: {short_count}개")

        # 백테스트 실행
        print("\n📈 백테스트 진행 중...")
        for idx, row in df.iterrows():
            self.process_bar(row, idx, df)

        # 미청산 포지션 처리
        if self.position is not None:
            last_row = df.iloc[-1]
            self.close_position(last_row['Close'], last_row['timestamp'], 'END_OF_DATA')

        # 결과 출력
        self.print_results()

        # 결과 저장
        self.save_results()

        return df

    def print_results(self):
        """결과 출력"""
        print("\n" + "=" * 80)
        print("📊 백테스트 결과")
        print("=" * 80)

        total_trades = len(self.trades)
        if total_trades == 0:
            print("거래 없음")
            return

        # 승/패 분류
        wins = [t for t in self.trades if t['net_pnl'] > 0]
        losses = [t for t in self.trades if t['net_pnl'] <= 0]

        # 롱/숏 분류
        long_trades = [t for t in self.trades if t['direction'] == 'LONG']
        short_trades = [t for t in self.trades if t['direction'] == 'SHORT']

        long_wins = [t for t in long_trades if t['net_pnl'] > 0]
        short_wins = [t for t in short_trades if t['net_pnl'] > 0]

        win_rate = len(wins) / total_trades * 100

        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)

        # 최대 낙폭 계산
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['capital']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        print(f"\n총 거래 수: {total_trades}")
        print(f"  - 롱: {len(long_trades)} ({len(long_wins)}승)")
        print(f"  - 숏: {len(short_trades)} ({len(short_wins)}승)")
        print(f"승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")

        print(f"\n초기 자본: ${self.initial_capital:,.2f}")
        print(f"최종 자본: ${self.capital:,.2f}")
        print(f"총 수익: ${total_pnl:,.2f} ({total_pnl/self.initial_capital*100:+.1f}%)")
        print(f"총 수수료: ${total_fees:,.2f}")
        print(f"최대 낙폭: {max_drawdown:.1f}%")

        if wins:
            avg_win = sum(t['net_pnl'] for t in wins) / len(wins)
            print(f"\n평균 수익 (승): ${avg_win:,.2f}")
        if losses:
            avg_loss = sum(t['net_pnl'] for t in losses) / len(losses)
            print(f"평균 손실 (패): ${avg_loss:,.2f}")

        # 평균 보유 기간
        holding_times = []
        for t in self.trades:
            entry = pd.to_datetime(t['entry_time'])
            exit_t = pd.to_datetime(t['exit_time'])
            holding_times.append((exit_t - entry).total_seconds() / 3600)  # 시간 단위

        avg_holding = sum(holding_times) / len(holding_times)
        print(f"\n평균 보유 기간: {avg_holding:.1f}시간")

    def save_results(self):
        """결과 저장"""
        # 거래 내역 저장
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(TRADES_CSV, index=False)
            print(f"\n💾 거래 내역 저장: {TRADES_CSV}")

        # 자본 곡선 저장
        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv(OUTPUT_CSV, index=False)
            print(f"💾 자본 곡선 저장: {OUTPUT_CSV}")


# ================================================================================
# 메인 실행
# ================================================================================

def main():
    backtester = EMAStrategyBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        leverage=LEVERAGE,
        position_size_pct=POSITION_SIZE_PCT,
        fee_rate=FEE_RATE,
        start_date=START_DATE,
        end_date=END_DATE
    )

    backtester.run()


if __name__ == "__main__":
    main()

"""
RSI Divergence Strategy - Martingale Backtester

전략 설명:
- RSI 다이버전스 신호로 진입
- 마틴게일 방식 다단계 진입 (1, 2, 6, 18, 54, ...)
- 평단가 기준 익절/손절

파라미터:
- LEVERAGE: 레버리지 배수
- MAX_ENTRIES: 최대 진입 횟수
- ENTRY_RATIOS: 진입 비율 배열 [1, 2, 6, 18, ...]
- TP_PERCENT: 익절 % (평단 기준)
- SL_PERCENT: 손절 % (평단 기준)

사용법:
    python backtest_rsi_divergence_martingale.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG: 파라미터 설정
# ================================================================================

# 백테스트 기간
START_DATE = '2023-01-01'
END_DATE = '2025-11-30'

# 데이터 파일 경로
DATA_FILE = 'backtest_data/BTCUSDT_rsi_2025_07_11.csv'

# 초기 자본
INITIAL_CAPITAL = 1000.0  # USDT

# ================================================================================
# 마틴게일 설정
# ================================================================================

# 레버리지 설정
LEVERAGE = 10  # 레버리지 배수 (자유롭게 조절)

# 최대 진입 횟수
MAX_ENTRIES = 5  # 최대 5번 진입

# 진입 비율 배열 (누적합 × 2 방식: 1, 2, 6, 18, 54, ...)
# 각 값은 기준 자본의 %
ENTRY_RATIOS = [1, 2, 6, 18, 54]  # 1%, 2%, 6%, 18%, 54%

# 익절/손절 설정 (평단가 기준)
TP_PERCENT = 0.03  # 익절: 평단가 +1%
SL_PERCENT = 0.01  # 손절: 평단가 -1% (모든 진입 소모 후)

# ================================================================================

# 수수료 설정
FEE_RATE = 0.000275  # 수수료율 (0.0275%)

# 결과 저장
OUTPUT_CSV = 'backtest_results_rsi_martingale.csv'
TRADES_CSV = 'trades_rsi_martingale.csv'


# ================================================================================
# 마틴게일 수열 생성
# ================================================================================

def get_martingale_sequence(length=10):
    """마틴게일 수열 생성 (다음 = 이전 누적합 × 2)"""
    seq = [1]
    cumsum = 1
    for i in range(1, length):
        next_val = cumsum * 2
        seq.append(next_val)
        cumsum += next_val
    return seq


# ================================================================================
# 전략 클래스
# ================================================================================

class RSIMartingaleBacktester:
    def __init__(self, data_file, initial_capital, leverage, max_entries,
                 entry_ratios, tp_percent, sl_percent,
                 fee_rate, start_date, end_date):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.max_entries = max_entries
        self.entry_ratios = entry_ratios
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        self.fee_rate = fee_rate
        self.start_date = start_date
        self.end_date = end_date

        # 상태 변수
        self.capital = initial_capital
        self.base_capital = initial_capital  # 기준 자본 (사이클 시작 시 갱신)
        self.position = None  # 현재 포지션 정보
        self.entries = []  # 진입 내역 [{price, size, value}, ...]
        self.current_entry_level = 0  # 현재 진입 레벨 (0부터 시작)
        self.avg_price = 0  # 평균 진입가
        self.total_size = 0  # 총 포지션 크기
        self.total_value = 0  # 총 포지션 가치
        self.total_entry_fee = 0  # 누적 진입 수수료

        self.trades = []
        self.equity_curve = []
        self.max_level_reached = 0  # 통계용

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

    def get_entry_percent(self, level):
        """해당 레벨의 진입 비율 반환"""
        if level < len(self.entry_ratios):
            return self.entry_ratios[level] / 100.0
        return 0

    def calculate_avg_price(self):
        """평균 진입가 계산"""
        if self.total_size == 0:
            return 0
        return self.total_value / self.total_size

    def add_entry(self, price, timestamp, direction):
        """진입 추가"""
        if self.current_entry_level >= self.max_entries:
            return False

        entry_percent = self.get_entry_percent(self.current_entry_level)
        position_value = self.base_capital * entry_percent * self.leverage
        size = position_value / price

        # 진입 수수료
        entry_fee = position_value * self.fee_rate
        self.total_entry_fee += entry_fee

        # 진입 기록
        entry = {
            'level': self.current_entry_level + 1,
            'price': price,
            'size': size,
            'value': position_value,
            'fee': entry_fee,
            'timestamp': timestamp
        }
        self.entries.append(entry)

        # 포지션 업데이트
        self.total_size += size
        self.total_value += position_value
        self.avg_price = self.calculate_avg_price()

        # 포지션 정보 (첫 진입 시 생성)
        if self.position is None:
            self.position = {
                'direction': direction,
                'first_entry_time': timestamp,
                'first_entry_price': price
            }

        # 최대 레벨 기록
        if self.current_entry_level > self.max_level_reached:
            self.max_level_reached = self.current_entry_level

        level_display = self.current_entry_level + 1
        print(f"   [진입 Lv.{level_display}] {direction} {entry_percent*100:.1f}% = ${position_value:.2f} @ {price:,.1f} | 평단: {self.avg_price:,.1f}")

        self.current_entry_level += 1
        return True

    def close_position(self, exit_price, timestamp, exit_reason):
        """포지션 청산"""
        if self.position is None:
            return

        direction = self.position['direction']

        # PnL 계산
        if direction == 'LONG':
            gross_pnl = (exit_price - self.avg_price) * self.total_size
        else:
            gross_pnl = (self.avg_price - exit_price) * self.total_size

        # 청산 수수료
        exit_fee = self.total_value * self.fee_rate

        # 순 PnL
        total_fees = self.total_entry_fee + exit_fee
        net_pnl = gross_pnl - total_fees

        # 자본 업데이트
        self.capital += net_pnl

        # 거래 기록
        trade = {
            'entry_time': self.position['first_entry_time'],
            'exit_time': timestamp,
            'direction': direction,
            'first_entry_price': self.position['first_entry_price'],
            'avg_price': self.avg_price,
            'exit_price': exit_price,
            'entry_levels': self.current_entry_level,
            'total_size': self.total_size,
            'total_value': self.total_value,
            'gross_pnl': gross_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'exit_reason': exit_reason,
            'capital_after': self.capital
        }
        self.trades.append(trade)

        pnl_pct = (exit_price / self.avg_price - 1) * 100 if direction == 'LONG' else (1 - exit_price / self.avg_price) * 100
        print(f"   [{exit_reason}] @ {exit_price:,.1f} | PnL: ${net_pnl:,.2f} ({pnl_pct:+.2f}%) | Lv.{self.current_entry_level}")

        # 포지션 초기화
        self.reset_position()

        # 기준 자본 갱신 (새 사이클 시작)
        self.base_capital = self.capital

    def reset_position(self):
        """포지션 초기화"""
        self.position = None
        self.entries = []
        self.current_entry_level = 0
        self.avg_price = 0
        self.total_size = 0
        self.total_value = 0
        self.total_entry_fee = 0

    def check_exit(self, row):
        """청산 조건 확인"""
        if self.position is None:
            return

        direction = self.position['direction']
        high_price = row['High']
        low_price = row['Low']
        close_price = row['Close']

        # 익절/손절 가격
        tp_price = self.avg_price * (1 + self.tp_percent) if direction == 'LONG' else self.avg_price * (1 - self.tp_percent)
        sl_price = self.avg_price * (1 - self.sl_percent) if direction == 'LONG' else self.avg_price * (1 + self.sl_percent)

        if direction == 'LONG':
            # 익절 체크
            if high_price >= tp_price:
                self.close_position(tp_price, row['timestamp'], 'TAKE_PROFIT')
                return

            # 손절 체크 (모든 진입 소모 후)
            if self.current_entry_level >= self.max_entries:
                if low_price <= sl_price:
                    # 손절가에 도달
                    self.close_position(sl_price, row['timestamp'], 'STOP_LOSS')
                    return
                elif close_price <= sl_price:
                    # 종가가 손절가 이하
                    self.close_position(close_price, row['timestamp'], 'STOP_LOSS_CLOSE')
                    return

        else:  # SHORT
            # 익절 체크
            if low_price <= tp_price:
                self.close_position(tp_price, row['timestamp'], 'TAKE_PROFIT')
                return

            # 손절 체크 (모든 진입 소모 후)
            if self.current_entry_level >= self.max_entries:
                if high_price >= sl_price:
                    self.close_position(sl_price, row['timestamp'], 'STOP_LOSS')
                    return
                elif close_price >= sl_price:
                    self.close_position(close_price, row['timestamp'], 'STOP_LOSS_CLOSE')
                    return

    def process_bar(self, row, idx, df):
        """봉 처리"""
        # 1. 청산 체크
        if self.position is not None:
            self.check_exit(row)

        # 2. 신호 처리 (새 진입 또는 추가 진입)
        # Double Bullish Divergence → LONG
        if row.get('double_bull_div', False):
            if self.position is None:
                # 첫 진입
                print(f"\n🟢 LONG 신호 @ {row['Close']:,.1f}")
                self.add_entry(row['Close'], row['timestamp'], 'LONG')
            elif self.position['direction'] == 'LONG' and self.current_entry_level < self.max_entries:
                # 추가 진입 (같은 방향 신호)
                print(f"   🟢 추가 LONG 신호 @ {row['Close']:,.1f}")
                self.add_entry(row['Close'], row['timestamp'], 'LONG')

        # Double Bearish Divergence → SHORT
        elif row.get('double_bear_div', False):
            if self.position is None:
                # 첫 진입
                print(f"\n🔴 SHORT 신호 @ {row['Close']:,.1f}")
                self.add_entry(row['Close'], row['timestamp'], 'SHORT')
            elif self.position['direction'] == 'SHORT' and self.current_entry_level < self.max_entries:
                # 추가 진입 (같은 방향 신호)
                print(f"   🔴 추가 SHORT 신호 @ {row['Close']:,.1f}")
                self.add_entry(row['Close'], row['timestamp'], 'SHORT')

        # 자본 곡선 기록
        self.equity_curve.append({
            'timestamp': row['timestamp'],
            'capital': self.capital
        })

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("🚀 RSI Divergence Martingale Strategy 백테스트 시작")
        print("=" * 80)
        print(f"   - 레버리지: {self.leverage}x")
        print(f"   - 최대 진입: {self.max_entries}회")
        print(f"   - 진입 비율: {self.entry_ratios}%")
        print(f"   - 익절: 평단 +{self.tp_percent*100}%")
        print(f"   - 손절: 평단 -{self.sl_percent*100}% (모든 진입 소모 후)")
        print(f"   - 진입 방식: 같은 방향 다이버전스 신호마다 추가 진입")
        print("=" * 80)

        # 데이터 로드
        df = self.load_data()

        # 신호 통계
        double_bull_count = df['double_bull_div'].sum() if 'double_bull_div' in df.columns else 0
        double_bear_count = df['double_bear_div'].sum() if 'double_bear_div' in df.columns else 0
        print(f"\n📊 다이버전스 신호:")
        print(f"   Double Bullish: {double_bull_count}개")
        print(f"   Double Bearish: {double_bear_count}개")

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

        win_rate = len(wins) / total_trades * 100

        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)

        # 진입 레벨 통계
        level_counts = {}
        for t in self.trades:
            lvl = t['entry_levels']
            level_counts[lvl] = level_counts.get(lvl, 0) + 1

        # 최대 낙폭 계산
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['capital']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        print(f"\n총 거래 수: {total_trades}")
        print(f"  - 롱: {len(long_trades)} / 숏: {len(short_trades)}")
        print(f"승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")

        print(f"\n마틴게일 통계:")
        print(f"  - 최대 도달 레벨: Lv.{self.max_level_reached + 1}")
        print(f"\n진입 레벨별 통계:")
        for lvl in sorted(level_counts.keys()):
            print(f"  - Lv.{lvl}: {level_counts[lvl]}회")

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

        # 청산 유형별 분류
        tp_trades = [t for t in self.trades if 'TAKE_PROFIT' in t['exit_reason']]
        sl_trades = [t for t in self.trades if 'STOP_LOSS' in t['exit_reason']]

        print(f"\n청산 유형:")
        print(f"  익절: {len(tp_trades)}회")
        print(f"  손절: {len(sl_trades)}회")

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
    backtester = RSIMartingaleBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        leverage=LEVERAGE,
        max_entries=MAX_ENTRIES,
        entry_ratios=ENTRY_RATIOS,
        tp_percent=TP_PERCENT,
        sl_percent=SL_PERCENT,
        fee_rate=FEE_RATE,
        start_date=START_DATE,
        end_date=END_DATE
    )

    backtester.run()


if __name__ == "__main__":
    main()

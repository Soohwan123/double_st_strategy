"""
RSI + Bollinger Band (RB) Strategy - Backtester V5 (홍콩 크루즈)

전략 설명:
- RSI(10) + BB(200, 2) 조합 전략
- LONG: RSI가 50 상향 돌파 + 가격이 BB 하단 상향 돌파
- SHORT: RSI가 50 하향 돌파 + 가격이 BB 상단 하향 돌파
- 손절: 진입가 -1%
- 익절: 진입가 +1%

홍콩 크루즈 베팅:
- 피보나치 수열로 진입 비율 결정
- 패배 시: 다음 단계로 이동
- 승리 시: 1단계 뒤로
- 2연승 시: 1단계로 리셋

사용법:
    python backtest_rb_strategy.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG: 파라미터 설정
# ================================================================================

# 백테스트 기간
START_DATE = '2023-01-20'
END_DATE = '2025-11-30'

# 데이터 파일 경로
DATA_FILE = 'backtest_data/BTCUSDT_rb_strategy.csv'

# 초기 자본
INITIAL_CAPITAL = 1000  # USDT

# 레버리지 설정
MAX_LEVERAGE = 100   # 최대 레버리지 (100% 초과 시 사용)

# 마틴게일 설정 (이전 누적합 × 2 방식)
# 시작 0.05% → 0.05, 0.1, 0.3, 0.9, 2.7, 8.1, 24.3, 72.9, 218.7, 656.1, 1968.3, 5904.9%
# Lv.1~8: 무레버 / Lv.9~12: 레버리지 사용 (최대 59x)
BASE_PERCENT = 0.0005  # 시작 비율 (0.05%)
MAX_LEVEL = 12       # 최대 레벨 (12레벨 = 59배 레버리지)
# 손절 → 다음 레벨 / 익절 → 1레벨 리셋
# 7레벨 손절 → 7레벨 유지 (익절할 때까지)

# 손절/익절 설정
SL_PERCENT = 0.0035  # 손절: 진입가 -0.5%
TP_PERCENT = 0.0035   # 익절: 진입가 +0.5%

# 수수료 설정
FEE_RATE = 0.000275  # 수수료율 (0.0275%)

# 결과 저장
OUTPUT_CSV = 'backtest_results_rb_strategy.csv'
TRADES_CSV = 'trades_rb_strategy.csv'


# ================================================================================
# 피보나치 수열 생성
# ================================================================================

def get_martingale_sequence(length=10):
    """마틴게일 수열 생성 (다음 = 이전 누적합 × 2)"""
    # 1, 2, 6, 18, 54, 162, 486, ...
    seq = [1]  # 1%
    cumsum = 1
    for i in range(1, length):
        next_val = cumsum * 2
        seq.append(next_val)
        cumsum += next_val
    return seq


# ================================================================================
# 전략 클래스
# ================================================================================

class RBStrategyBacktester:
    def __init__(self, data_file, initial_capital, fee_rate, start_date, end_date):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.start_date = start_date
        self.end_date = end_date

        # 상태 변수
        self.capital = initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []

        # 마틴게일 상태
        self.martingale_sequence = get_martingale_sequence(MAX_LEVEL + 5)
        self.current_level = 0  # 현재 단계 (0부터 시작)
        self.max_level_reached = 0  # 최대 도달 단계 (통계용)
        self.base_capital = initial_capital  # 기준 자본 (1레벨 리셋 시 갱신)
        self.level_locked = False  # 익절 후 레벨 고정 플래그

    def get_current_percent(self):
        """현재 단계의 진입 비율 반환"""
        multiplier = self.martingale_sequence[self.current_level]
        return BASE_PERCENT * multiplier  # 0.0005 * 1 = 0.05%, 0.0005 * 2 = 0.1%...

    def get_current_leverage(self):
        """현재 단계의 레버리지 계산 (자본 초과 시 레버리지 증가)"""
        entry_percent = self.get_current_percent()

        if entry_percent <= 1.0:
            # 자본 100% 이하면 레버리지 1x (현물처럼)
            return 1.0
        else:
            # 자본 초과 시 레버리지 = 필요 비율 (최대 MAX_LEVERAGE)
            return min(entry_percent, MAX_LEVERAGE)

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

    def open_position(self, direction, entry_price, entry_time):
        """포지션 진입 (기준 자본 기준 비율 적용)"""
        # 현재 단계 비율과 레버리지 계산
        entry_percent = self.get_current_percent()
        leverage = self.get_current_leverage()

        # 기준 자본 기준으로 포지션 가치 계산 (레버리지는 마진에만 적용)
        position_value = self.base_capital * entry_percent

        # 실제 마진 = 포지션 가치 / 레버리지
        margin = position_value / leverage
        size = position_value / entry_price

        # 진입 수수료
        entry_fee = position_value * self.fee_rate
        self.capital -= entry_fee

        # 손절/익절가 계산
        if direction == 'LONG':
            sl_price = entry_price * (1 - SL_PERCENT)
            tp_price = entry_price * (1 + TP_PERCENT)
        else:
            sl_price = entry_price * (1 + SL_PERCENT)
            tp_price = entry_price * (1 - TP_PERCENT)

        self.position = {
            'direction': direction,
            'entry_time': entry_time,
            'entry_price': entry_price,
            'size': size,
            'position_value': position_value,
            'margin': margin,
            'leverage': leverage,
            'entry_fee': entry_fee,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'entry_level': self.current_level,
            'entry_percent': entry_percent
        }

        # 최대 레벨 기록
        if self.current_level > self.max_level_reached:
            self.max_level_reached = self.current_level

        level_display = self.current_level + 1

    def close_position(self, exit_price, exit_time, exit_reason):
        """포지션 청산"""
        if self.position is None:
            return

        direction = self.position['direction']
        entry_price = self.position['entry_price']
        size = self.position['size']
        position_value = self.position['position_value']

        # PnL 계산
        if direction == 'LONG':
            gross_pnl = (exit_price - entry_price) * size
        else:
            gross_pnl = (entry_price - exit_price) * size

        # 청산 수수료
        exit_fee = position_value * self.fee_rate
        self.capital -= exit_fee

        # 순 PnL
        total_fees = self.position['entry_fee'] + exit_fee
        net_pnl = gross_pnl - exit_fee

        # 자본에 PnL 반영
        self.capital += gross_pnl

        # 승패 판정 및 마틴게일 레벨 조정
        is_win = net_pnl > 0

        if is_win:
            # 익절
            if self.current_level == 0:
                # 1레벨 익절 → 유지, 기준자본 갱신
                self.base_capital = self.capital
                self.level_locked = False
                level_change = f"→ Lv.1 (유지, 기준${self.base_capital:.0f})"
            elif self.level_locked:
                # 이미 레벨 고정됨 → 현재 레벨 유지
                level_change = f"→ Lv.{self.current_level + 1} (고정 유지)"
            else:
                # 첫 익절 → -1 레벨로 내리고 고정
                self.current_level -= 1
                self.level_locked = True
                level_change = f"→ Lv.{self.current_level + 1} (익절 -1, 고정)"
        else:
            # 손절
            if self.level_locked:
                # 레벨 고정 상태에서 손절 → 1레벨 리셋 + 기준자본 갱신
                self.current_level = 0
                self.base_capital = self.capital
                self.level_locked = False
                level_change = f"→ Lv.1 (리셋, 기준${self.base_capital:.0f})"
            else:
                # 일반 손절: 다음 레벨로 (단, MAX_LEVEL이면 유지)
                if self.current_level >= MAX_LEVEL - 1:
                    level_change = f"→ Lv.{self.current_level + 1} (MAX 유지)"
                else:
                    self.current_level += 1
                    level_change = f"→ Lv.{self.current_level + 1} (손절)"

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': exit_time,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'entry_level': self.position['entry_level'] + 1,
            'entry_percent': self.position['entry_percent'],
            'size': size,
            'position_value': position_value,
            'gross_pnl': gross_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'exit_reason': exit_reason,
            'capital_after': self.capital,
            'is_win': is_win
        }
        self.trades.append(trade)

        pnl_pct = (exit_price / entry_price - 1) * 100 if direction == 'LONG' else (1 - exit_price / entry_price) * 100
        self.position = None

    def check_position(self, row):
        """포지션 관리: 손절, 익절 체크"""
        if self.position is None:
            return

        direction = self.position['direction']
        sl_price = self.position['sl_price']
        tp_price = self.position['tp_price']

        high_price = row['High']
        low_price = row['Low']

        if direction == 'LONG':
            # 익절 체크 (High >= TP)
            if high_price >= tp_price:
                self.close_position(tp_price, row['timestamp'], 'TAKE_PROFIT')
                return

            # 손절 체크 (Low <= SL)
            if low_price <= sl_price:
                self.close_position(sl_price, row['timestamp'], 'STOP_LOSS')
                return

        else:  # SHORT
            # 익절 체크 (Low <= TP)
            if low_price <= tp_price:
                self.close_position(tp_price, row['timestamp'], 'TAKE_PROFIT')
                return

            # 손절 체크 (High >= SL)
            if high_price >= sl_price:
                self.close_position(sl_price, row['timestamp'], 'STOP_LOSS')
                return

    def process_bar(self, row, idx, df):
        """봉 처리"""
        # 1. 기존 포지션 관리
        if self.position is not None:
            self.check_position(row)

        # 2. 새 진입 신호 확인 (포지션 없을 때만)
        # RSI(10) 50 돌파 + BB(200,2) 밴드 돌파 진입
        if self.position is None:
            # long_signal / short_signal 컬럼 사용 (prepare_rsi_bollinger_data.py에서 생성)
            if row.get('long_signal', False):
                entry_price = row['Close']
                self.open_position('LONG', entry_price, row['timestamp'])

            elif row.get('short_signal', False):
                entry_price = row['Close']
                self.open_position('SHORT', entry_price, row['timestamp'])

        # 자본 곡선 기록
        self.equity_curve.append({
            'timestamp': row['timestamp'],
            'capital': self.capital
        })

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("🚀 RB Strategy V5 (마틴게일) 백테스트 시작")
        print(f"   - 진입: RSI(10) 50 돌파 + BB(200,2) 밴드 돌파")
        print(f"   - 마틴게일 수열: {self.martingale_sequence[:MAX_LEVEL]}%")
        print(f"   - 최대 레벨: {MAX_LEVEL} (MAX 손절 시 유지)")
        print(f"   - 레버리지: 자본 이하 1x / 초과 시 최대 {MAX_LEVERAGE}x")
        print(f"   - 손절: 진입가 -{SL_PERCENT*100}%")
        print(f"   - 익절: 진입가 +{TP_PERCENT*100}%")
        print(f"   - 손절 시: 다음 레벨 (익절 후 손절 → 1레벨 리셋)")
        print(f"   - 익절 시: -1 레벨 (1레벨이면 유지, 손절날 때까지 반복)")
        print("=" * 80)

        # 데이터 로드
        df = self.load_data()

        # 신호 통계 출력
        long_count = df['long_signal'].sum() if 'long_signal' in df.columns else 0
        short_count = df['short_signal'].sum() if 'short_signal' in df.columns else 0
        print(f"\n📊 진입 신호:")
        print(f"   LONG: {long_count}개")
        print(f"   SHORT: {short_count}개")

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
        wins = [t for t in self.trades if t['is_win']]
        losses = [t for t in self.trades if not t['is_win']]

        # 롱/숏 분류
        long_trades = [t for t in self.trades if t['direction'] == 'LONG']
        short_trades = [t for t in self.trades if t['direction'] == 'SHORT']

        win_rate = len(wins) / total_trades * 100

        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)

        # 진입 레벨 통계
        level_counts = {}
        for t in self.trades:
            lvl = t['entry_level']
            level_counts[lvl] = level_counts.get(lvl, 0) + 1

        # 최대 낙폭 계산
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['capital']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        # 연속 손실 통계
        max_consecutive_losses = 0
        current_losses = 0
        for t in self.trades:
            if not t['is_win']:
                current_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
            else:
                current_losses = 0

        print(f"\n총 거래 수: {total_trades}")
        print(f"  - 롱: {len(long_trades)} / 숏: {len(short_trades)}")
        print(f"승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")

        print(f"\n마틴게일 통계:")
        print(f"  - 최대 도달 레벨: Lv.{self.max_level_reached + 1}")
        print(f"  - 최대 연속 손실: {max_consecutive_losses}회")
        print(f"\n진입 레벨별 통계:")
        for lvl in sorted(level_counts.keys()):
            pct = self.martingale_sequence[lvl - 1]
            print(f"  - Lv.{lvl} ({pct}%): {level_counts[lvl]}회")

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
        sl_trades = [t for t in self.trades if t['exit_reason'] == 'STOP_LOSS']
        tp_trades = [t for t in self.trades if t['exit_reason'] == 'TAKE_PROFIT']

        print(f"\n청산 유형:")
        print(f"  손절: {len(sl_trades)}회")
        print(f"  익절: {len(tp_trades)}회")

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
    backtester = RBStrategyBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        fee_rate=FEE_RATE,
        start_date=START_DATE,
        end_date=END_DATE
    )

    backtester.run()


if __name__ == "__main__":
    main()

"""
OB + Bollinger Engulfing Strategy - 마틴게일 백테스터

전략 개요:
- Order Block + Bollinger Band 신호로 진입
- 9단계 마틴게일 배팅 시스템
- 레벨별 손익비 조정 (1:1 → 1:0.6)
- 익절 또는 마지막 손절 시 레벨 1로 복귀

마틴게일 배팅 시스템:
| 레벨 | 진입%   | 손절%  | 익절%   | 손익비  |
|------|---------|--------|---------|---------|
| 1    | 1%      | 0.5%   | 0.5%    | 1:1     |
| 2    | 2%      | 0.5%   | 0.475%  | 1:0.95  |
| 3    | 6%      | 0.5%   | 0.45%   | 1:0.9   |
| 4    | 18%     | 0.5%   | 0.425%  | 1:0.85  |
| 5    | 54%     | 0.5%   | 0.4%    | 1:0.8   |
| 6    | 162%    | 0.5%   | 0.375%  | 1:0.75  |
| 7    | 486%    | 0.5%   | 0.35%   | 1:0.7   |
| 8    | 1458%   | 0.5%   | 0.325%  | 1:0.65  |
| 9    | 4375%   | 0.5%   | 0.3%    | 1:0.6   |

레버리지: 100% 이하 = 무레버리지, 이후 필요한 만큼 레버리지 사용
최대 레버리지: 44x (4375% / 100%)

사용법:
    python backtest_ob_bollinger_martingale.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG
# ================================================================================

# 백테스트 기간
START_DATE = '2022-01-01'
END_DATE = '2025-11-30'

# 데이터 파일
DATA_FILE = 'backtest_data/BTCUSDT_ob_bollinger.csv'

# 초기 자본
INITIAL_CAPITAL = 1000.0  # USDT

# 최대 레버리지 (4375% = 약 44배)
MAX_LEVERAGE = 50

# 수수료 설정
MAKER_FEE = 0.0        # 지정가 수수료 없음
TAKER_FEE = 0.000275   # 시장가 수수료 0.0275%

# 마틴게일 배팅 시스템 (9단계)
# 진입 비율: 1, 2, 6, 18, 54, 162, 486, 1458, 4375 (cumsum * 3 패턴)
ENTRY_PERCENTS = [0.01, 0.02, 0.06, 0.18, 0.54, 1.62, 4.86, 14.58, 43.75]

# 손절 거리 (모든 레벨 동일)
SL_PERCENT = 0.005  # 0.5%

# 익절 거리 (레벨별)
TP_PERCENTS = [0.005, 0.00475, 0.0045, 0.00425, 0.004, 0.00375, 0.0035, 0.00325, 0.003]

# 손익비 (참고용)
# RISK_REWARDS = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6]

# 총 레벨 수
MAX_LEVELS = 9

# 결과 파일
OUTPUT_CSV = 'backtest_results_ob_bollinger.csv'
TRADES_CSV = 'trades_ob_bollinger.csv'


# ================================================================================
# 백테스터 클래스
# ================================================================================

class OBBollingerMartingaleBacktester:
    def __init__(self, data_file, initial_capital, start_date, end_date):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.start_date = start_date
        self.end_date = end_date

        # 상태 변수
        self.capital = initial_capital
        self.base_capital = initial_capital  # 마틴게일 사이클 시작 시 기준 자본
        self.position = None  # {'direction': 'LONG'/'SHORT', 'entry_price': ..., ...}
        self.current_level = 1  # 현재 마틴게일 레벨 (1~9)
        self.trades = []
        self.equity_curve = []

    def load_data(self):
        """데이터 로드"""
        print(f"데이터 로드: {self.data_file}")

        df = pd.read_csv(self.data_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # 기간 필터링
        df = df[(df['timestamp'] >= self.start_date) &
                (df['timestamp'] <= self.end_date)]
        df = df.reset_index(drop=True)

        print(f"   기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
        print(f"   데이터 수: {len(df):,} rows")

        return df

    def get_entry_params(self, level):
        """레벨별 진입 파라미터 반환"""
        idx = level - 1
        entry_pct = ENTRY_PERCENTS[idx]
        tp_pct = TP_PERCENTS[idx]
        sl_pct = SL_PERCENT

        return entry_pct, tp_pct, sl_pct

    def calculate_position_size(self, entry_price, level):
        """
        포지션 크기 계산

        - position_value = base_capital * entry_percent
        - 100% 이하: 무레버리지
        - 100% 초과: 레버리지 사용 (최대 MAX_LEVERAGE)
        - BTC 수량 = position_value / entry_price
        """
        entry_pct, _, _ = self.get_entry_params(level)

        # 포지션 가치 (USDT)
        position_value = self.base_capital * entry_pct

        # 필요 레버리지 계산
        if position_value <= self.capital:
            leverage_used = 1
        else:
            leverage_used = min(position_value / self.capital, MAX_LEVERAGE)
            # 실제 사용 가능한 포지션 가치로 조정
            if position_value > self.capital * MAX_LEVERAGE:
                position_value = self.capital * MAX_LEVERAGE

        # BTC 수량
        size = position_value / entry_price

        return size, position_value, leverage_used

    def open_position(self, direction, entry_price, timestamp, level):
        """포지션 오픈"""
        size, position_value, leverage = self.calculate_position_size(entry_price, level)

        # 파라미터 가져오기
        _, tp_pct, sl_pct = self.get_entry_params(level)

        # TP/SL 가격 계산
        if direction == 'LONG':
            tp_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
        else:
            tp_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)

        # 진입 수수료 (시장가로 진입한다고 가정)
        entry_fee = position_value * TAKER_FEE
        self.capital -= entry_fee

        self.position = {
            'direction': direction,
            'entry_price': entry_price,
            'entry_time': timestamp,
            'size': size,
            'position_value': position_value,
            'leverage': leverage,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'entry_fee': entry_fee,
            'level': level
        }

        print(f"\n[Level {level}] {direction} 진입 @ {entry_price:,.1f}")
        print(f"   포지션: ${position_value:,.0f} (레버리지: {leverage:.1f}x)")
        print(f"   TP: {tp_price:,.1f} (+{tp_pct*100:.2f}%) | SL: {sl_price:,.1f} (-{sl_pct*100:.2f}%)")

    def close_position(self, exit_price, timestamp, reason):
        """포지션 청산"""
        if self.position is None:
            return

        direction = self.position['direction']
        entry_price = self.position['entry_price']
        size = self.position['size']
        position_value = self.position['position_value']
        entry_fee = self.position['entry_fee']
        level = self.position['level']

        # PnL 계산
        if direction == 'LONG':
            gross_pnl = (exit_price - entry_price) * size
        else:
            gross_pnl = (entry_price - exit_price) * size

        # 청산 수수료: 익절(TP)은 지정가로 수수료 없음, 손절(SL)은 시장가로 수수료 있음
        if reason == 'TP':
            exit_fee = 0  # 지정가 익절: 수수료 없음
        else:
            exit_fee = position_value * TAKER_FEE  # 시장가 손절: 수수료 있음

        # 순 PnL (entry_fee는 이미 자본에서 차감됨)
        net_pnl = gross_pnl - exit_fee

        # 자본 업데이트
        self.capital += gross_pnl - exit_fee

        # 수익률 계산
        pnl_pct = (exit_price / entry_price - 1) * 100 if direction == 'LONG' else (1 - exit_price / entry_price) * 100

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': timestamp,
            'direction': direction,
            'level': level,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'size': size,
            'position_value': position_value,
            'leverage': self.position['leverage'],
            'tp_price': self.position['tp_price'],
            'sl_price': self.position['sl_price'],
            'gross_pnl': gross_pnl,
            'fees': entry_fee + exit_fee,
            'net_pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'capital_after': self.capital,
            'base_capital': self.base_capital
        }
        self.trades.append(trade)

        result_emoji = "+" if net_pnl > 0 else ""
        print(f"   [{reason}] 청산 @ {exit_price:,.1f} | PnL: ${result_emoji}{net_pnl:,.2f} ({pnl_pct:+.2f}%)")
        print(f"   자본: ${self.capital:,.2f}")

        # 레벨 업데이트
        if reason == 'TP':
            # 익절 → 레벨 1로 복귀, base_capital 갱신
            print(f"   익절! 레벨 1로 복귀 (base_capital: ${self.capital:,.2f})")
            self.current_level = 1
            self.base_capital = self.capital
        elif reason == 'SL':
            if self.current_level >= MAX_LEVELS:
                # 마지막 레벨 손절 → 레벨 1로 복귀
                print(f"   마지막 레벨 손절! 레벨 1로 복귀 (base_capital: ${self.capital:,.2f})")
                self.current_level = 1
                self.base_capital = self.capital
            else:
                # 손절 → 다음 레벨로 진행
                self.current_level += 1
                print(f"   손절! 레벨 {self.current_level}로 진행")

        self.position = None

    def process_bar(self, row, idx, df):
        """봉 처리"""
        timestamp = row['timestamp']
        high_price = row['High']
        low_price = row['Low']
        close_price = row['Close']

        # 포지션이 있는 경우: TP/SL 체크
        if self.position is not None:
            direction = self.position['direction']
            tp_price = self.position['tp_price']
            sl_price = self.position['sl_price']

            if direction == 'LONG':
                # LONG: TP는 High >= tp_price, SL은 Low <= sl_price
                # TP 우선 체크
                if high_price >= tp_price:
                    self.close_position(tp_price, timestamp, 'TP')
                elif low_price <= sl_price:
                    self.close_position(sl_price, timestamp, 'SL')
            else:
                # SHORT: TP는 Low <= tp_price, SL은 High >= sl_price
                # TP 우선 체크
                if low_price <= tp_price:
                    self.close_position(tp_price, timestamp, 'TP')
                elif high_price >= sl_price:
                    self.close_position(sl_price, timestamp, 'SL')

        # 포지션이 없는 경우: 진입 신호 체크
        if self.position is None:
            long_signal = row.get('long_signal', False)
            short_signal = row.get('short_signal', False)

            # 자본이 부족하면 진입하지 않음
            if self.capital <= 0:
                return

            if long_signal:
                # LONG 진입: 종가에 진입
                self.open_position('LONG', close_price, timestamp, self.current_level)

            elif short_signal:
                # SHORT 진입: 종가에 진입
                self.open_position('SHORT', close_price, timestamp, self.current_level)

        # 자본 곡선 기록
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
            'capital': equity,
            'level': self.current_level
        })

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("OB + Bollinger Martingale 백테스트 시작")
        print("=" * 80)
        print(f"초기 자본: ${self.initial_capital:,.2f}")
        print(f"마틴게일 레벨: {MAX_LEVELS}단계")
        print(f"최대 레버리지: {MAX_LEVERAGE}x")

        # 배팅 시스템 출력
        print("\n배팅 시스템:")
        for i in range(MAX_LEVELS):
            print(f"   Level {i+1}: {ENTRY_PERCENTS[i]*100:.1f}% | TP: {TP_PERCENTS[i]*100:.3f}% | SL: {SL_PERCENT*100:.1f}%")

        print("=" * 80)

        # 데이터 로드
        df = self.load_data()

        # 신호 통계
        long_count = df['long_signal'].sum() if 'long_signal' in df.columns else 0
        short_count = df['short_signal'].sum() if 'short_signal' in df.columns else 0
        print(f"\n신호 통계:")
        print(f"   LONG 신호: {long_count}개")
        print(f"   SHORT 신호: {short_count}개")

        # 백테스트 실행
        print("\n백테스트 진행 중...")
        for idx, row in df.iterrows():
            self.process_bar(row, idx, df)

        # 미청산 포지션 처리
        if self.position is not None:
            last_row = df.iloc[-1]
            self.close_position(last_row['Close'], last_row['timestamp'], 'END')

        # 결과 출력
        self.print_results()

        # 결과 저장
        self.save_results()

        return df

    def print_results(self):
        """결과 출력"""
        print("\n" + "=" * 80)
        print("백테스트 결과")
        print("=" * 80)

        total_trades = len(self.trades)
        if total_trades == 0:
            print("거래 없음")
            return

        # 승/패 분류
        wins = [t for t in self.trades if t['net_pnl'] > 0]
        losses = [t for t in self.trades if t['net_pnl'] <= 0]

        # 방향별 분류
        long_trades = [t for t in self.trades if t['direction'] == 'LONG']
        short_trades = [t for t in self.trades if t['direction'] == 'SHORT']
        long_wins = [t for t in long_trades if t['net_pnl'] > 0]
        short_wins = [t for t in short_trades if t['net_pnl'] > 0]

        # 레벨별 분류
        level_stats = {}
        for level in range(1, MAX_LEVELS + 1):
            level_trades = [t for t in self.trades if t['level'] == level]
            level_wins = [t for t in level_trades if t['net_pnl'] > 0]
            level_stats[level] = {
                'total': len(level_trades),
                'wins': len(level_wins),
                'pnl': sum(t['net_pnl'] for t in level_trades)
            }

        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)

        # 최대 낙폭
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['capital']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        print(f"\n총 거래 수: {total_trades}")
        print(f"  - 롱: {len(long_trades)} ({len(long_wins)}승)")
        print(f"  - 숏: {len(short_trades)} ({len(short_wins)}승)")
        print(f"승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")

        print(f"\n레벨별 통계:")
        for level in range(1, MAX_LEVELS + 1):
            stats = level_stats[level]
            if stats['total'] > 0:
                level_wr = stats['wins'] / stats['total'] * 100
                print(f"   Level {level}: {stats['total']}회 | 승률: {level_wr:.1f}% | PnL: ${stats['pnl']:+,.2f}")

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

        # 최대 연속 손실
        consecutive_losses = 0
        max_consecutive = 0
        for t in self.trades:
            if t['net_pnl'] <= 0:
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0
        print(f"최대 연속 손실: {max_consecutive}회")

    def save_results(self):
        """결과 저장"""
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(TRADES_CSV, index=False)
            print(f"\n거래 내역 저장: {TRADES_CSV}")

        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.to_csv(OUTPUT_CSV, index=False)
            print(f"자본 곡선 저장: {OUTPUT_CSV}")


# ================================================================================
# 메인 실행
# ================================================================================

def main():
    backtester = OBBollingerMartingaleBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        start_date=START_DATE,
        end_date=END_DATE
    )

    backtester.run()


if __name__ == "__main__":
    main()

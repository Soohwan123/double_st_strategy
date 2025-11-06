"""
Double SuperTrend Strategy Backtest
두 개의 타임프레임(5분, 1시간)과 각각 두 개의 SuperTrend를 사용하는 전략

전략 설명:
1. 1시간봉 SuperTrend 12/1, 12/3이 모두 같은 방향일 때만 거래
2. 5분봉에서 두 SuperTrend가 모두 반대 → 모두 같은 방향으로 전환 시 진입
3. 손절: 진입 전 30개 봉 최저/최고점
4. 익절: 1:1 이상 + 5분봉 ST(12/1) 반전 시
"""

import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ================================================================================
# CONFIG: 백테스트 설정 (자유롭게 수정 가능)
# ================================================================================

# 손절 설정
LOOKBACK_CANDLES = 30  # 손절가 계산을 위한 과거 캔들 수
INITIAL_STOP_PCT = 0.03  # 데이터 부족시 기본 손절 퍼센트 (3%)

# 레버리지 설정
LOW_LEVERAGE_THRESHOLD = 10  # 이 배수 이하는 안전한 레버리지 사용
MAX_EXCHANGE_LEVERAGE = 100  # 거래소 최대 레버리지
MARGIN_USAGE_PCT = 0.9  # 자본의 몇 %를 증거금으로 사용 (90%)
MARGIN_BUFFER_PCT = 0.95  # 증거금 여유 비율 (95%)

# 백테스트 결과 출력 설정
DEFAULT_OUTPUT_FILE = 'backtest_results.csv'  # 기본 출력 파일명
SECTION_DIVIDER = '=' * 80  # 구분선

# 메인 실행시 기본 설정
DEFAULT_DATA_FILE = 'backtest_data/BTCUSDT_double_st_backtest_data.csv'
DEFAULT_TEST_DAYS = 90  # 기본 테스트 일수
DEFAULT_INITIAL_CAPITAL = 1000  # 기본 초기 자본
DEFAULT_RISK_PER_TRADE = 0.03  # 기본 리스크 (3%)
DEFAULT_FEE_RATE = 0.000275  # 기본 수수료 (0.0275%)

# ================================================================================'


class DoubleSTBacktester:
    def __init__(self, initial_capital=1000, risk_per_trade=0.03, fee_rate=0.000275):
        """
        Parameters:
        - initial_capital: 초기 자본 (USDT)
        - risk_per_trade: 거래당 위험 비율 (3%)
        - fee_rate: 수수료율 (0.0275%)
        """
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.fee_rate = fee_rate

        # 포지션 상태
        self.position = None
        self.trades = []

        # 플래그 시스템
        self.buy_set = False
        self.sell_set = False
        self.buy_ready = False
        self.sell_ready = False

        # 손절 후 재진입 플래그
        self.after_stop_loss_long = False
        self.after_stop_loss_short = False

    def reset_flags(self):
        """플래그 초기화"""
        self.buy_ready = False
        self.sell_ready = False

    def update_flags(self, row):
        """5분봉 SuperTrend 상태에 따라 플래그 업데이트"""
        st_12_1_5m_dir = row['st_12_1_5m_dir']
        st_12_3_5m_dir = row['st_12_3_5m_dir']

        # 두 ST가 모두 같은 방향인지 확인
        both_long = (st_12_1_5m_dir == 1) and (st_12_3_5m_dir == 1)
        both_short = (st_12_1_5m_dir == -1) and (st_12_3_5m_dir == -1)

        # 상태 전환 감지
        # buy_set: 두 ST가 모두 SHORT가 되었을 때 ON (LONG 진입 준비)
        # sell_set: 두 ST가 모두 LONG이 되었을 때 ON (SHORT 진입 준비)

        if both_short:
            # 두 ST가 모두 SHORT
            if not self.buy_set:
                self.buy_set = True
                self.buy_ready = False  # ready 리셋

        elif both_long:
            # 두 ST가 모두 LONG
            if self.buy_set:
                # SHORT 상태였다가 LONG으로 전환 = LONG 진입 신호
                self.buy_ready = True
                self.buy_set = False
                self.sell_set = True  # 이제 SHORT 진입 준비

            elif not self.sell_set:
                # 처음 LONG 상태
                self.sell_set = True
                self.sell_ready = False

        # SHORT 진입 신호
        if both_short and self.sell_set:
            # LONG 상태였다가 SHORT로 전환 = SHORT 진입 신호
            self.sell_ready = True
            self.sell_set = False
            self.buy_set = True  # 이제 LONG 진입 준비

    def check_1h_alignment(self, row):
        """1시간봉 SuperTrend가 모두 같은 방향인지 확인"""
        st_12_1_1h_dir = row['st_12_1_1h_dir']
        st_12_3_1h_dir = row['st_12_3_1h_dir']

        if st_12_1_1h_dir == 1 and st_12_3_1h_dir == 1:
            return 'LONG'
        elif st_12_1_1h_dir == -1 and st_12_3_1h_dir == -1:
            return 'SHORT'
        else:
            return 'NEUTRAL'

    def calculate_stop_loss(self, df, current_idx, direction):
        """진입 전 캔들 기준 손절가 계산"""
        lookback = LOOKBACK_CANDLES
        start_idx = max(0, current_idx - lookback)

        # 충분한 데이터가 없으면 현재가 기준으로 고정 손절 설정
        if current_idx < 5:
            current_price = df.iloc[current_idx]['Close']
            if direction == 'LONG':
                return current_price * (1 - INITIAL_STOP_PCT)  # 기본 손절
            else:
                return current_price * (1 + INITIAL_STOP_PCT)  # 기본 손절

        if direction == 'LONG':
            # 롱: 30개 봉 최저점
            return df.iloc[start_idx:current_idx]['Low'].min()
        else:
            # 숏: 30개 봉 최고점
            return df.iloc[start_idx:current_idx]['High'].max()

    def calculate_position_size(self, entry_price, stop_price):
        """
        리스크 기반 포지션 크기 계산
        risk_amount = capital * risk_per_trade
        position_size = risk_amount / (entry_price - stop_price)
        """
        risk_amount = self.capital * self.risk_per_trade
        price_difference = abs(entry_price - stop_price)

        if price_difference == 0:
            return 0

        # 포지션 크기 (BTC 수량)
        position_size = risk_amount / price_difference

        # 최대 레버리지 제한
        max_position_value = self.capital * MAX_EXCHANGE_LEVERAGE
        max_position_size = max_position_value / entry_price

        return min(position_size, max_position_size)

    def open_position(self, df, idx, direction):
        """포지션 진입"""
        row = df.iloc[idx]
        entry_price = row['Close']
        stop_price = self.calculate_stop_loss(df, idx, direction)

        # 손절가가 현재가보다 불리한 경우 진입하지 않음
        if direction == 'LONG' and stop_price >= entry_price:
            return False
        elif direction == 'SHORT' and stop_price <= entry_price:
            return False

        # 손절 거리 계산 (%)
        stop_distance_pct = abs(entry_price - stop_price) / entry_price

        # 손절 거리가 0이거나 너무 작으면 진입 안함
        if stop_distance_pct < 0.0001:  # 0.01% 미만 (100배 초과 필요)
            return False

        # 1. 리스크 기반 포지션 크기 계산
        risk_amount = self.capital * self.risk_per_trade
        position_value = risk_amount / stop_distance_pct  # 이게 목표 포지션 가치
        position_size = position_value / entry_price

        # 2. 필요한 레버리지 계산
        required_leverage = position_value / self.capital

        # 3. 레버리지가 최대치를 초과하면 포지션 축소
        if required_leverage > MAX_EXCHANGE_LEVERAGE:
            # 최대 레버리지로 낼 수 있는 포지션으로 축소
            position_value = self.capital * MAX_EXCHANGE_LEVERAGE
            position_size = position_value / entry_price
            actual_leverage = MAX_EXCHANGE_LEVERAGE
        else:
            # 안전한 레버리지 설정 (올림 처리)
            import math
            if required_leverage <= 1:
                actual_leverage = 1
            elif required_leverage <= LOW_LEVERAGE_THRESHOLD:
                # 낮은 레버리지일 때는 여유있게 올림
                actual_leverage = math.ceil(required_leverage)
            else:
                # 높은 레버리지일 때도 올림
                actual_leverage = min(math.ceil(required_leverage), MAX_EXCHANGE_LEVERAGE)

        # 4. 필요한 증거금 계산
        required_margin = position_value / actual_leverage

        # 5. 수수료 계산
        entry_fee = entry_price * position_size * self.fee_rate

        # 6. 증거금 + 수수료가 자본을 초과하면 진입 안함
        if required_margin + entry_fee > self.capital:
            return False

        # 익절가 계산 (1:1 risk/reward)
        if direction == 'LONG':
            risk = entry_price - stop_price
            target_price = entry_price + risk
        else:
            risk = stop_price - entry_price
            target_price = entry_price - risk

        # 포지션 대비 자본 배수 (표시용)
        display_leverage = position_value / self.capital

        self.position = {
            'direction': direction,
            'entry_time': row['timestamp'],
            'entry_idx': idx,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'target_price': target_price,
            'position_size': position_size,
            'entry_fee': entry_fee,
            'leverage': display_leverage,  # 자본 대비 포지션 크기
            'exchange_leverage': actual_leverage  # 실제 거래소 레버리지
        }

        # 자본에서 수수료 차감
        self.capital -= entry_fee

        # 플래그 리셋
        self.reset_flags()
        self.after_stop_loss_long = False
        self.after_stop_loss_short = False

        return True

    def check_exit_conditions(self, row):
        """청산 조건 확인"""
        if not self.position:
            return None, 0

        current_price = row['Close']
        high = row['High']
        low = row['Low']

        # 손절/익절 체크
        if self.position['direction'] == 'LONG':
            # 손절 체크
            if low <= self.position['stop_price']:
                exit_price = min(current_price, self.position['stop_price'])
                return 'STOP_LOSS', exit_price

            # 익절 조건: 1:1 이상 + ST(12/1) 반전
            if high >= self.position['target_price']:
                # 1:1 도달
                if row['st_12_1_5m_dir'] == -1:
                    # ST(12/1)이 숏 신호
                    exit_price = max(current_price, self.position['target_price'])
                    return 'TAKE_PROFIT', exit_price

        else:  # SHORT
            # 손절 체크
            if high >= self.position['stop_price']:
                exit_price = max(current_price, self.position['stop_price'])
                return 'STOP_LOSS', exit_price

            # 익절 조건: 1:1 이상 + ST(12/1) 반전
            if low <= self.position['target_price']:
                # 1:1 도달
                if row['st_12_1_5m_dir'] == 1:
                    # ST(12/1)이 롱 신호
                    exit_price = min(current_price, self.position['target_price'])
                    return 'TAKE_PROFIT', exit_price

        return None, 0

    def close_position(self, row, exit_type, exit_price):
        """포지션 청산"""
        if not self.position:
            return

        # 실제 청산가 (슬리피지 고려)
        if exit_price == 0:
            exit_price = row['Close']

        # 수수료 계산
        exit_fee = exit_price * self.position['position_size'] * self.fee_rate

        # PnL 계산
        if self.position['direction'] == 'LONG':
            gross_pnl = (exit_price - self.position['entry_price']) * self.position['position_size']
        else:
            gross_pnl = (self.position['entry_price'] - exit_price) * self.position['position_size']

        net_pnl = gross_pnl - self.position['entry_fee'] - exit_fee

        # 자본 업데이트 (net PnL만 더함)
        self.capital += net_pnl

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': row['timestamp'],
            'direction': self.position['direction'],
            'entry_price': self.position['entry_price'],
            'exit_price': exit_price,
            'stop_price': self.position['stop_price'],
            'target_price': self.position['target_price'],
            'position_size': self.position['position_size'],
            'gross_pnl': gross_pnl,
            'fees': self.position['entry_fee'] + exit_fee,
            'net_pnl': net_pnl,
            'position_multiple': self.position['leverage'],  # 자본 대비 배수
            'exchange_leverage': self.position['exchange_leverage'],  # 실제 거래소 레버리지
            'exit_type': exit_type,
            'capital_after': self.capital
        }
        self.trades.append(trade)

        # 손절 후 재진입 플래그 설정
        if exit_type == 'STOP_LOSS':
            if self.position['direction'] == 'LONG':
                self.after_stop_loss_long = True
            else:
                self.after_stop_loss_short = True

        # 포지션 초기화
        self.position = None

        # 플래그 업데이트 (익절/손절 직후 현재 상태 확인)
        st_12_1_5m_dir = row['st_12_1_5m_dir']
        st_12_3_5m_dir = row['st_12_3_5m_dir']

        both_long = (st_12_1_5m_dir == 1) and (st_12_3_5m_dir == 1)
        both_short = (st_12_1_5m_dir == -1) and (st_12_3_5m_dir == -1)

        if both_short:
            self.buy_set = True
            self.sell_set = False
        elif both_long:
            self.sell_set = True
            self.buy_set = False

        self.buy_ready = False
        self.sell_ready = False

    def run_backtest(self, df):
        """백테스트 실행"""
        print("\n" + SECTION_DIVIDER)
        print("🚀 Double SuperTrend Strategy Backtest")
        print(SECTION_DIVIDER)

        # 데이터프레임에 필요한 데이터 미리 준비
        df = df.copy()

        # 디버깅 정보
        ready_count = 0
        h1_long_count = 0
        h1_short_count = 0

        for idx, row in df.iterrows():
            # 포지션이 있으면 청산 조건 먼저 확인
            if self.position:
                exit_type, exit_price = self.check_exit_conditions(row)
                if exit_type:
                    self.close_position(row, exit_type, exit_price)

            # 플래그 업데이트
            self.update_flags(row)

            # 포지션이 없으면 진입 조건 확인
            if not self.position:
                # 1시간봉 정렬 확인
                h1_alignment = self.check_1h_alignment(row)

                # 디버깅: 1시간봉 정렬 카운트
                if h1_alignment == 'LONG':
                    h1_long_count += 1
                elif h1_alignment == 'SHORT':
                    h1_short_count += 1

                # 디버깅: ready 상태 카운트
                if self.buy_ready:
                    ready_count += 1
                if self.sell_ready:
                    ready_count += 1

                # 5분봉 SuperTrend 상태 확인
                st_12_1_5m_dir = row['st_12_1_5m_dir']
                st_12_3_5m_dir = row['st_12_3_5m_dir']
                both_long_5m = (st_12_1_5m_dir == 1) and (st_12_3_5m_dir == 1)
                both_short_5m = (st_12_1_5m_dir == -1) and (st_12_3_5m_dir == -1)

                # 롱 진입 조건
                if h1_alignment == 'LONG':
                    # 일반 진입: buy_ready 상태
                    if self.buy_ready:
                        print(f"📈 LONG 진입: {row['timestamp']} @ {row['Close']}")
                        self.open_position(df, idx, 'LONG')
                    # 손절 후 재진입: 5분봉 두 ST가 모두 BUY
                    elif self.after_stop_loss_long and both_long_5m:
                        print(f"📈 LONG 재진입(손절후): {row['timestamp']} @ {row['Close']}")
                        self.open_position(df, idx, 'LONG')

                # 숏 진입 조건
                elif h1_alignment == 'SHORT':
                    # 일반 진입: sell_ready 상태
                    if self.sell_ready:
                        print(f"📉 SHORT 진입: {row['timestamp']} @ {row['Close']}")
                        self.open_position(df, idx, 'SHORT')
                    # 손절 후 재진입: 5분봉 두 ST가 모두 SELL
                    elif self.after_stop_loss_short and both_short_5m:
                        print(f"📉 SHORT 재진입(손절후): {row['timestamp']} @ {row['Close']}")
                        self.open_position(df, idx, 'SHORT')

        # 마지막 포지션이 남아있으면 청산
        if self.position:
            self.close_position(df.iloc[-1], 'FORCE_CLOSE', df.iloc[-1]['Close'])

        # 디버깅 정보 출력
        print(f"\n🔍 디버깅 정보:")
        print(f"  1시간봉 LONG 정렬: {h1_long_count:,} 회")
        print(f"  1시간봉 SHORT 정렬: {h1_short_count:,} 회")
        print(f"  Ready 상태 발생: {ready_count:,} 회")

        return self.generate_report()

    def generate_report(self):
        """백테스트 결과 리포트 생성"""
        if not self.trades:
            print("\n❌ 거래 없음")
            return None

        trades_df = pd.DataFrame(self.trades)

        # 통계 계산
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['net_pnl'] > 0])
        losing_trades = len(trades_df[trades_df['net_pnl'] < 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = trades_df['net_pnl'].sum()
        total_fees = trades_df['fees'].sum()

        avg_win = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['net_pnl'] < 0]['net_pnl'].mean() if losing_trades > 0 else 0

        # 최대 낙폭
        cumulative_pnl = trades_df['net_pnl'].cumsum()
        running_max = cumulative_pnl.expanding().max()
        drawdown = running_max - cumulative_pnl
        max_drawdown = drawdown.max()

        final_capital = self.capital
        total_return = ((final_capital - self.initial_capital) / self.initial_capital) * 100

        # 결과 출력
        print("\n" + SECTION_DIVIDER)
        print("📊 백테스트 결과")
        print(SECTION_DIVIDER)
        print(f"\n📈 수익 통계:")
        print(f"  초기 자본: ${self.initial_capital:,.2f}")
        print(f"  최종 자본: ${final_capital:,.2f}")
        print(f"  총 수익률: {total_return:.2f}%")
        print(f"  총 순손익: ${total_pnl:,.2f}")
        print(f"  총 수수료: ${total_fees:,.2f}")

        print(f"\n🎯 거래 통계:")
        print(f"  총 거래 수: {total_trades}")
        print(f"  승리 거래: {winning_trades}")
        print(f"  패배 거래: {losing_trades}")
        print(f"  승률: {win_rate:.2f}%")
        print(f"  평균 수익: ${avg_win:,.2f}")
        print(f"  평균 손실: ${avg_loss:,.2f}")
        print(f"  최대 낙폭: ${max_drawdown:,.2f}")

        # 청산 타입별 통계
        print(f"\n🏁 청산 타입:")
        for exit_type in trades_df['exit_type'].unique():
            count = len(trades_df[trades_df['exit_type'] == exit_type])
            pct = (count / total_trades) * 100
            print(f"  {exit_type}: {count} ({pct:.1f}%)")

        # 거래 내역 저장
        trades_df.to_csv(DEFAULT_OUTPUT_FILE, index=False)
        print(f"\n💾 거래 내역 저장: {DEFAULT_OUTPUT_FILE}")

        return trades_df


def main():
    """메인 실행 함수"""
    # 데이터 로드
    data_file = DEFAULT_DATA_FILE

    print(f"📂 데이터 로드: {data_file}")
    df = pd.read_csv(data_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 백테스트 기간 설정 (최근 N일)
    start_date = df['timestamp'].max() - pd.Timedelta(days=DEFAULT_TEST_DAYS)
    test_df = df[df['timestamp'] >= start_date].copy()
    test_df = test_df.reset_index(drop=True)

    print(f"📅 백테스트 기간: {test_df['timestamp'].min()} ~ {test_df['timestamp'].max()}")
    print(f"📊 데이터 크기: {len(test_df):,} 행")

    # 백테스터 초기화 및 실행
    backtester = DoubleSTBacktester(
        initial_capital=DEFAULT_INITIAL_CAPITAL,
        risk_per_trade=DEFAULT_RISK_PER_TRADE,
        fee_rate=DEFAULT_FEE_RATE
    )

    # 백테스트 실행
    results = backtester.run_backtest(test_df)

    print("\n✅ 백테스트 완료!")


if __name__ == "__main__":
    main()
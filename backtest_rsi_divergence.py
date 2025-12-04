"""
RSI Double Divergence Strategy - Backtester

전략 설명:
- RSI 더블 다이버전스를 이용한 진입 전략
- Double Bullish Divergence → LONG (1:5 손익비)
- Double Bearish Divergence → SHORT (1:1 손익비)
- 진입: 더블 다이버전스 확정 봉 (피벗 확정 3봉 후)
- 손절: 더블 다이버전스 발생 봉의 저점(롱) / 고점(숏)
- 수수료: 0.0275% (익절 시 진입만, 손절 시 진입+청산)
- 포지션 사이징: 매 거래 자본의 1%만 손절되도록 레버리지 조정

사용법:
    python backtest_rsi_divergence.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG: 파라미터 설정 (자유롭게 수정 가능)
# ================================================================================

# 백테스트 기간
START_DATE = '2025-05-01'
END_DATE = '2025-11-30'

# 데이터 파일 경로
DATA_FILE = 'backtest_data/BTCUSDT_rsi_2025_07_11.csv'

# 초기 자본 및 레버리지
INITIAL_CAPITAL = 1000.0  # USDT
MAX_LEVERAGE = 100         # 최대 레버리지 배수

# 포지션 사이징
POSITION_SIZE_PCT = 1.0   # 자본의 몇 %를 사용할지 (1.0 = 100%)
RISK_PER_TRADE = 0.001     # 거래당 리스크 비율 (0.001 = 자본의 0.1%)

# RSI 설정
RSI_LENGTH = 14           # RSI 기간

# Pivot 설정
PIVOT_LEFT = 5            # 피벗 좌측 봉 수 (lbL)
PIVOT_RIGHT = 3           # 피벗 우측 봉 수 (lbR)
RANGE_LOWER = 5           # 피벗 간 최소 거리
RANGE_UPPER = 60          # 피벗 간 최대 거리

# 익절/손절 설정
LONG_TP_RATIO = 1.0       # 롱 익절 비율 (SL 거리 * 비율) - 1:5 손익비
SHORT_TP_RATIO = 1.0      # 숏 익절 비율 (SL 거리 * 비율) - 1:3 손익비

# 수수료 설정
FEE_RATE = 0.000275       # 수수료율 (0.0275%)

# 결과 저장
OUTPUT_CSV = 'backtest_results_rsi_divergence.csv'
TRADES_CSV = 'trades_rsi_divergence.csv'


# ================================================================================
# 피벗 및 다이버전스 감지 함수
# ================================================================================

def find_pivot_lows(series, left, right):
    """
    피벗 로우 찾기 (TradingView ta.pivotlow 방식)

    피벗 로우: 좌측 left개, 우측 right개 봉보다 낮은 지점
    피벗은 right봉 전에 확정됨 (현재 봉 기준 -right 위치)

    Returns:
        Boolean Series: 피벗 로우 발생 여부 (right봉 전 기준)
    """
    pivots = pd.Series(False, index=series.index)

    for i in range(left + right, len(series)):
        pivot_idx = i - right  # 피벗 후보 위치
        pivot_val = series.iloc[pivot_idx]

        # 좌측 left개 봉보다 낮아야 함
        left_check = all(pivot_val < series.iloc[pivot_idx - j] for j in range(1, left + 1))

        # 우측 right개 봉보다 낮거나 같아야 함 (TradingView 방식)
        right_check = all(pivot_val <= series.iloc[pivot_idx + j] for j in range(1, right + 1))

        if left_check and right_check:
            pivots.iloc[i] = True  # 현재 봉에서 피벗 확정

    return pivots


def find_pivot_highs(series, left, right):
    """
    피벗 하이 찾기 (TradingView ta.pivothigh 방식)

    피벗 하이: 좌측 left개, 우측 right개 봉보다 높은 지점

    Returns:
        Boolean Series: 피벗 하이 발생 여부 (right봉 전 기준)
    """
    pivots = pd.Series(False, index=series.index)

    for i in range(left + right, len(series)):
        pivot_idx = i - right
        pivot_val = series.iloc[pivot_idx]

        # 좌측 left개 봉보다 높아야 함
        left_check = all(pivot_val > series.iloc[pivot_idx - j] for j in range(1, left + 1))

        # 우측 right개 봉보다 높거나 같아야 함
        right_check = all(pivot_val >= series.iloc[pivot_idx + j] for j in range(1, right + 1))

        if left_check and right_check:
            pivots.iloc[i] = True

    return pivots


def bars_since(condition_series):
    """
    조건이 마지막으로 True였던 이후 봉 수 계산 (TradingView ta.barssince)
    """
    result = pd.Series(np.nan, index=condition_series.index)
    last_true_idx = -1

    for i in range(len(condition_series)):
        if condition_series.iloc[i]:
            last_true_idx = i
        if last_true_idx >= 0:
            result.iloc[i] = i - last_true_idx

    return result


def value_when(condition_series, value_series, occurrence=1):
    """
    조건이 True였을 때의 값 반환 (TradingView ta.valuewhen)

    Args:
        condition_series: 조건 Boolean Series
        value_series: 값 Series
        occurrence: 몇 번째 이전 True 값인지 (1 = 직전)

    Returns:
        Series: 조건이 True였을 때의 값
    """
    result = pd.Series(np.nan, index=condition_series.index)
    true_indices = []

    for i in range(len(condition_series)):
        if condition_series.iloc[i]:
            true_indices.append(i)

        if len(true_indices) >= occurrence + 1:
            # occurrence번째 이전 True 인덱스의 값
            prev_idx = true_indices[-(occurrence + 1)]
            result.iloc[i] = value_series.iloc[prev_idx]
        elif len(true_indices) >= occurrence:
            # 현재 True이고 이전 True가 있으면
            if condition_series.iloc[i] and len(true_indices) > 1:
                prev_idx = true_indices[-2]
                result.iloc[i] = value_series.iloc[prev_idx]

    return result


# ================================================================================
# 전략 클래스
# ================================================================================

class RSIDivergenceBacktester:
    def __init__(self, data_file, initial_capital, max_leverage, position_size_pct,
                 risk_per_trade, long_tp_ratio, short_tp_ratio, fee_rate, start_date,
                 end_date, pivot_left, pivot_right, range_lower, range_upper):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.max_leverage = max_leverage
        self.position_size_pct = position_size_pct
        self.risk_per_trade = risk_per_trade
        self.long_tp_ratio = long_tp_ratio
        self.short_tp_ratio = short_tp_ratio
        self.fee_rate = fee_rate
        self.start_date = start_date
        self.end_date = end_date
        self.pivot_left = pivot_left
        self.pivot_right = pivot_right
        self.range_lower = range_lower
        self.range_upper = range_upper

        # 상태 변수
        self.capital = initial_capital
        self.position = None
        self.pending_signal = None  # 대기 중인 진입 신호 (3봉 후 진입 예약)
        self.pending_exit = None    # 대기 중인 청산 신호 (롱: 피벗 하이 발생 시 3봉 후 청산)
        self.rsi_touched_overbought = False  # RSI가 과매수(70 이상) 터치 여부 추적
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

    def detect_divergences(self, df):
        """
        RSI 다이버전스 감지

        Returns:
            df with 'bull_signal', 'bear_signal' columns added
        """
        print("📊 다이버전스 감지 중...")

        rsi = df['rsi']
        low = df['Low']
        high = df['High']

        lbL = self.pivot_left
        lbR = self.pivot_right

        # 피벗 찾기
        pl_found = find_pivot_lows(rsi, lbL, lbR)
        ph_found = find_pivot_highs(rsi, lbL, lbR)

        print(f"   피벗 로우: {pl_found.sum()}개")
        print(f"   피벗 하이: {ph_found.sum()}개")

        # 이전 피벗과의 거리 체크 (inRange)
        bars_since_pl = bars_since(pl_found.shift(1).fillna(False))
        bars_since_ph = bars_since(ph_found.shift(1).fillna(False))

        in_range_pl = (self.range_lower <= bars_since_pl) & (bars_since_pl <= self.range_upper)
        in_range_ph = (self.range_lower <= bars_since_ph) & (bars_since_ph <= self.range_upper)

        # 피벗 발생 봉의 RSI 값 (lbR봉 전)
        rsi_at_pivot = rsi.shift(lbR)
        low_at_pivot = low.shift(lbR)
        high_at_pivot = high.shift(lbR)

        # 이전 피벗의 RSI/가격 값
        prev_rsi_low = value_when(pl_found, rsi_at_pivot, 1)
        prev_low = value_when(pl_found, low_at_pivot, 1)

        prev_rsi_high = value_when(ph_found, rsi_at_pivot, 1)
        prev_high = value_when(ph_found, high_at_pivot, 1)

        # Bullish Divergence: 가격 Lower Low + RSI Higher Low
        osc_hl = (rsi_at_pivot > prev_rsi_low) & in_range_pl  # RSI Higher Low
        price_ll = low_at_pivot < prev_low                     # Price Lower Low
        bull_signal = pl_found & osc_hl & price_ll

        # Bearish Divergence: 가격 Higher High + RSI Lower High
        osc_lh = (rsi_at_pivot < prev_rsi_high) & in_range_ph  # RSI Lower High
        price_hh = high_at_pivot > prev_high                    # Price Higher High
        bear_signal = ph_found & osc_lh & price_hh

        df['bull_signal'] = bull_signal
        df['bear_signal'] = bear_signal
        df['pivot_low'] = pl_found
        df['pivot_high'] = ph_found

        print(f"   Bullish Divergence: {bull_signal.sum()}개")
        print(f"   Bearish Divergence: {bear_signal.sum()}개")

        return df

    def calculate_position_size(self, entry_price, sl_price):
        """
        포지션 크기 계산 - 리스크 기반 레버리지 조정

        손절 거리를 기준으로 자본의 RISK_PER_TRADE (1%)만 손실되도록 레버리지 계산

        예시:
        - 자본 $1000, 리스크 1% → 최대 손실 $10
        - 진입가 $100, 손절가 $99 → 손절 거리 1%
        - 레버리지 = 1% / 1% = 1배 (틀림)
        - 실제: 레버리지 10배로 $10,000 포지션
        - $10,000 * 1% 손실 = $100 (X)
        - 올바른 계산: 손실액 = 자본 * 리스크 = $10
        - 포지션 크기 = 손실액 / 손절거리(달러) = $10 / $1 = 10 BTC
        - 포지션 가치 = 10 * $100 = $1000
        - 레버리지 = 포지션가치 / 자본 = $1000 / $1000 = 1배

        수정된 예시 (손절 1% 거리):
        - 자본 $1000, 리스크 1% → 최대 손실 $10
        - 진입가 $100, 손절가 $99 → 손절 거리 $1 (1%)
        - 포지션 크기 = $10 / $1 = 10 단위
        - 포지션 가치 = 10 * $100 = $1000
        - 레버리지 = $1000 / $1000 = 1배
        """
        # 손절까지의 거리 (달러)
        sl_distance = abs(entry_price - sl_price)

        if sl_distance == 0:
            return 0, 0, 0

        # 손절 거리 비율
        sl_distance_pct = sl_distance / entry_price

        # 최대 손실 허용액 (자본의 1%)
        max_loss = self.capital * self.risk_per_trade

        # 포지션 크기 (단위) = 최대손실 / 손절거리(달러)
        size = max_loss / sl_distance

        # 포지션 가치 (달러)
        position_value = size * entry_price

        # 실제 레버리지 계산
        available_capital = self.capital * self.position_size_pct
        leverage = position_value / available_capital

        # 최대 레버리지 제한
        if leverage > self.max_leverage:
            leverage = self.max_leverage
            position_value = available_capital * leverage
            size = position_value / entry_price

        return size, position_value, leverage

    def open_position(self, direction, entry_price, sl_price, tp_price, entry_time, entry_bar_idx):
        """포지션 오픈"""
        size, position_value, leverage = self.calculate_position_size(entry_price, sl_price)

        if size == 0:
            return  # 유효하지 않은 포지션

        # 진입 수수료
        entry_fee = position_value * self.fee_rate

        self.position = {
            'direction': direction,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'entry_bar_idx': entry_bar_idx,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'size': size,
            'position_value': position_value,
            'leverage': leverage,
            'entry_fee': entry_fee
        }

    def close_position(self, exit_price, exit_time, exit_reason):
        """
        포지션 청산

        수수료 규칙:
        - 익절 시 (TAKE_PROFIT): 진입 수수료만 (청산 수수료 없음)
        - 손절 시 (STOP_LOSS): 진입 + 청산 수수료 모두
        """
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

        # 청산 수수료 (익절 시 없음, 손절 시 있음)
        is_take_profit = 'TAKE_PROFIT' in exit_reason
        if is_take_profit:
            exit_fee = 0  # 익절 시 청산 수수료 없음
        else:
            exit_fee = position_value * self.fee_rate  # 손절 시 청산 수수료 발생

        # 순 PnL
        net_pnl = gross_pnl - entry_fee - exit_fee

        # 자본 업데이트
        self.capital += net_pnl

        # 거래 기록
        trade = {
            'entry_time': self.position['entry_time'],
            'exit_time': exit_time,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'sl_price': self.position['sl_price'],
            'tp_price': self.position['tp_price'],
            'size': size,
            'leverage': self.position['leverage'],
            'gross_pnl': gross_pnl,
            'fees': entry_fee + exit_fee,
            'net_pnl': net_pnl,
            'exit_reason': exit_reason,
            'capital_after': self.capital
        }
        self.trades.append(trade)

        self.position = None
        self.pending_exit = None  # 청산 시 대기 중인 익절 신호도 초기화
        self.rsi_touched_overbought = False  # RSI 과매수 터치 초기화

    def check_exit(self, row, idx):
        """
        청산 조건 확인

        봉 진행 중 TP/SL 체크:
        - LONG: High >= TP → 익절, Low <= SL → 손절
        - SHORT: Low <= TP → 익절, High >= SL → 손절

        동시 터치 시 우선순위: 시가 기준으로 판단
        """
        if self.position is None:
            return

        direction = self.position['direction']
        entry_price = self.position['entry_price']
        sl_price = self.position['sl_price']
        tp_price = self.position['tp_price']

        open_price = row['Open']
        high_price = row['High']
        low_price = row['Low']

        exit_price = None
        exit_reason = None

        if direction == 'LONG':
            # 롱: 피벗 하이 기반 익절 (정적 TP 없음, 손절만 체크)
            # 갭 다운 체크 (시가가 SL 이하)
            if open_price <= sl_price:
                exit_price = open_price
                exit_reason = 'STOP_LOSS_GAP'
            elif low_price <= sl_price:
                exit_price = sl_price
                exit_reason = 'STOP_LOSS'

        else:  # SHORT
            # 갭 업 체크 (시가가 SL 이상)
            if open_price >= sl_price:
                exit_price = open_price
                exit_reason = 'STOP_LOSS_GAP'
            # TP와 SL 동시 터치 가능
            elif tp_price is not None and low_price <= tp_price and high_price >= sl_price:
                if open_price <= entry_price:
                    exit_price = tp_price
                    exit_reason = 'TAKE_PROFIT'
                else:
                    exit_price = sl_price
                    exit_reason = 'STOP_LOSS'
            elif tp_price is not None and low_price <= tp_price:
                exit_price = tp_price
                exit_reason = 'TAKE_PROFIT'
            elif high_price >= sl_price:
                exit_price = sl_price
                exit_reason = 'STOP_LOSS'

        if exit_price is not None:
            self.close_position(exit_price, row['timestamp'], exit_reason)

    def process_bar(self, row, idx, df):
        """
        봉 처리

        1. 기존 포지션 청산 체크
        2. 대기 중인 신호 진입 처리
        3. 새 더블 다이버전스 신호 저장 (3봉 후 진입 예약)

        진입 로직:
        - 더블다이버전스 봉 발견 시 → 신호 저장 (손절 라인 = 해당 봉의 저점/고점)
        - 3봉 후 → 해당 봉 종가에 진입

        예시 (10:45에 double_bull_div=True):
        - 10:45: 신호 저장, 손절 = 10:45 Low
        - 11:00 (3봉 후): 11:00 Close에 진입
        """
        lbR = self.pivot_right  # 3봉

        # 0. 롱 포지션일 때: RSI 과매수 터치 후 피벗 하이 익절 로직
        if self.position is not None and self.position['direction'] == 'LONG':
            # RSI 과매수(70 이상) 터치 추적
            rsi_val = row.get('rsi', 50)
            if rsi_val >= 70:
                self.rsi_touched_overbought = True

            # 대기 중인 익절 신호 처리 (피벗 하이 확정 후 3봉)
            if self.pending_exit is not None:
                if idx >= self.pending_exit['signal_bar_idx'] + lbR:
                    # 피벗 하이 확정 3봉 후: 종가에 익절
                    self.close_position(row['Close'], row['timestamp'], 'TAKE_PROFIT_PIVOT_HIGH')
                    self.pending_exit = None
                    self.rsi_touched_overbought = False

            # RSI 과매수 터치 후 피벗 하이 발생 시 익절 예약
            elif self.rsi_touched_overbought and row.get('pivot_high', False):
                self.pending_exit = {
                    'signal_bar_idx': idx,
                    'signal_time': row['timestamp']
                }

        # 1. 청산 체크 (손절)
        if self.position is not None:
            self.check_exit(row, idx)

        # 2. 대기 중인 신호 진입 처리 (포지션 없을 때만)
        if self.position is None and self.pending_signal is not None:
            signal = self.pending_signal

            # 신호 발생 후 lbR봉이 지났는지 확인
            if idx >= signal['signal_bar_idx'] + lbR:
                entry_price = row['Close']  # 현재 봉 종가에 진입
                sl_price = signal['sl_price']

                if signal['direction'] == 'LONG':
                    distance = entry_price - sl_price
                    if distance > 0:
                        # 롱: 피벗 하이 기반 익절 (정적 TP 없음)
                        tp_price = None
                        self.open_position('LONG', entry_price, sl_price, tp_price,
                                          row['timestamp'], idx)
                        self.rsi_touched_overbought = False  # 롱 진입 시 RSI 과매수 터치 초기화
                else:  # SHORT
                    distance = sl_price - entry_price
                    if distance > 0:
                        tp_price = entry_price - distance * self.short_tp_ratio
                        self.open_position('SHORT', entry_price, sl_price, tp_price,
                                          row['timestamp'], idx)

                self.pending_signal = None  # 신호 소비

        # 3. 새 더블 다이버전스 신호 저장 (포지션 없고, 대기 신호 없을 때만)
        if self.position is None and self.pending_signal is None:
            # Double Bullish Divergence → LONG 예약
            if row.get('double_bull_div', False):
                self.pending_signal = {
                    'direction': 'LONG',
                    'signal_bar_idx': idx,
                    'sl_price': row['Low'],  # 더블다이버전스 봉의 저점
                    'signal_time': row['timestamp']
                }

            # Double Bearish Divergence → SHORT 예약
            elif row.get('double_bear_div', False):
                self.pending_signal = {
                    'direction': 'SHORT',
                    'signal_bar_idx': idx,
                    'sl_price': row['High'],  # 더블다이버전스 봉의 고점
                    'signal_time': row['timestamp']
                }

        # 자본 곡선 기록
        self.equity_curve.append({
            'timestamp': row['timestamp'],
            'capital': self.capital
        })

    def run(self):
        """백테스트 실행"""
        print("\n" + "=" * 80)
        print("🚀 RSI Double Divergence Strategy 백테스트 시작")
        print("=" * 80)

        # 데이터 로드 (CSV에서 더블 다이버전스 컬럼 직접 사용)
        df = self.load_data()

        # 더블 다이버전스 통계 출력
        double_bull_count = df['double_bull_div'].sum() if 'double_bull_div' in df.columns else 0
        double_bear_count = df['double_bear_div'].sum() if 'double_bear_div' in df.columns else 0
        print(f"\n📊 더블 다이버전스 신호:")
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

        # 롱/숏 승패 분류
        long_wins = [t for t in long_trades if t['net_pnl'] > 0]
        long_losses = [t for t in long_trades if t['net_pnl'] <= 0]
        short_wins = [t for t in short_trades if t['net_pnl'] > 0]
        short_losses = [t for t in short_trades if t['net_pnl'] <= 0]

        win_rate = len(wins) / total_trades * 100
        long_win_rate = len(long_wins) / len(long_trades) * 100 if long_trades else 0
        short_win_rate = len(short_wins) / len(short_trades) * 100 if short_trades else 0

        total_pnl = sum(t['net_pnl'] for t in self.trades)
        total_fees = sum(t['fees'] for t in self.trades)

        # 최대 낙폭 계산
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['peak'] = equity_df['capital'].cummax()
        equity_df['drawdown'] = (equity_df['peak'] - equity_df['capital']) / equity_df['peak'] * 100
        max_drawdown = equity_df['drawdown'].max()

        print(f"\n총 거래 수: {total_trades}")
        print(f"  - 롱: {len(long_trades)} / 숏: {len(short_trades)}")
        print(f"승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")
        print(f"\n롱 승률: {long_win_rate:.1f}% ({len(long_wins)}승 / {len(long_losses)}패)")
        print(f"숏 승률: {short_win_rate:.1f}% ({len(short_wins)}승 / {len(short_losses)}패)")
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

        # 익절/손절 비율
        tp_trades = [t for t in self.trades if 'TAKE_PROFIT' in t['exit_reason']]
        sl_trades = [t for t in self.trades if 'STOP_LOSS' in t['exit_reason']]
        print(f"\n익절 청산: {len(tp_trades)}회")
        print(f"손절 청산: {len(sl_trades)}회")

        # 레버리지 통계
        leverages = [t['leverage'] for t in self.trades]
        avg_leverage = sum(leverages) / len(leverages)
        min_leverage = min(leverages)
        max_leverage = max(leverages)
        print(f"\n레버리지 (리스크 기반 동적 조정):")
        print(f"  평균: {avg_leverage:.2f}x")
        print(f"  최소: {min_leverage:.2f}x / 최대: {max_leverage:.2f}x")

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
    backtester = RSIDivergenceBacktester(
        data_file=DATA_FILE,
        initial_capital=INITIAL_CAPITAL,
        max_leverage=MAX_LEVERAGE,
        position_size_pct=POSITION_SIZE_PCT,
        risk_per_trade=RISK_PER_TRADE,
        long_tp_ratio=LONG_TP_RATIO,
        short_tp_ratio=SHORT_TP_RATIO,
        fee_rate=FEE_RATE,
        start_date=START_DATE,
        end_date=END_DATE,
        pivot_left=PIVOT_LEFT,
        pivot_right=PIVOT_RIGHT,
        range_lower=RANGE_LOWER,
        range_upper=RANGE_UPPER
    )

    backtester.run()


if __name__ == "__main__":
    main()

"""
Hyper Scalper Strategy Backtester V2
EMA25/100/200 + ADX + Retest (LONG & SHORT)
손절: 최근 50봉 최저가(LONG) / 최고가(SHORT)

LONG 진입 조건:
1. bullTrend: close > EMA200 AND EMA25 > EMA100 > EMA200 (정배열)
2. strongTrend: ADX >= 30
3. hadLowBelowFast: 최근 5봉 내 저가가 EMA25 아래였던 적 있음
4. reclaimLong: 현재 종가 > EMA25
- 익절: 진입가 + ATR * TP_ATR_MULT
- 손절: 최근 50봉 최저가

SHORT 진입 조건:
1. bearTrend: close < EMA200 AND EMA25 < EMA100 < EMA200 (역배열)
2. strongTrend: ADX >= 30
3. hadHighAboveFast: 최근 5봉 내 고가가 EMA25 위였던 적 있음
4. reclaimShort: 현재 종가 < EMA25
- 익절: 진입가 - ATR * TP_ATR_MULT
- 손절: 최근 50봉 최고가
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ============================================
# 파라미터 설정
# ============================================
INITIAL_CAPITAL = 1000.0
MAX_LEVERAGE = 90
RISK_PER_TRADE = 0.06  # 5% 리스크

# 거래 방향: 'BOTH', 'LONG', 'SHORT'
TRADE_DIRECTION = 'BOTH'

# 출금 설정
WITHDRAWAL_ENABLED = False    # 출금 기능 ON/OFF
WITHDRAWAL_MULTIPLIER = 100   # 시작자금의 N배 도달 시 출금
WITHDRAWAL_RATIO = 0.5       # 출금 비율 (50%)

# EMA 설정
EMA_FAST = 25
EMA_MID = 100
EMA_SLOW = 200

# ADX 설정
ADX_LENGTH = 14
ADX_THRESHOLD = 32.0

# Retest 설정
RETEST_LOOKBACK = 8

# 손절 설정
SL_LOOKBACK = 29  # 손절가 계산용 lookback 봉 수
MAX_SL_DISTANCE = 0.035  # 4%

# ATR 설정
ATR_LENGTH = 10
TP_ATR_MULT_LONG = 4.3   # 롱 익절 ATR 배수
TP_ATR_MULT_SHORT = 4.3  # 숏 익절 ATR 배수

# 수수료
MAKER_FEE = 0.0002
TAKER_FEE = 0.0005

fee_protection = True  # 수수료 보호 기능 활성화 여부

# ============================================
# 백테스트 기간 설정
# ============================================
START_DATE = '2020-07-01'
END_DATE = '2025-12-31'


# ============================================
# TradingView 호환 지표 계산 함수
# ============================================

def calculate_ema(series: pd.Series, length: int) -> pd.Series:
    """TradingView EMA 계산"""
    return series.ewm(span=length, adjust=False).mean()


def calculate_rma(series: pd.Series, length: int) -> pd.Series:
    """TradingView RMA (Wilder's Moving Average) 계산"""
    alpha = 1.0 / length
    result = np.zeros(len(series))
    result[:] = np.nan

    if len(series) >= length:
        result[length - 1] = series.iloc[:length].mean()
        for i in range(length, len(series)):
            result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]

    return pd.Series(result, index=series.index)


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """TradingView ATR 계산 (RMA 기반)"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return calculate_rma(tr, length)


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """
    TradingView ADX 계산
    ta.dmi(adxLen, adxLen) 와 동일
    """
    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    # Smoothed with RMA
    atr = calculate_rma(tr, length)
    plus_di = 100 * calculate_rma(plus_dm, length) / atr
    minus_di = 100 * calculate_rma(minus_dm, length) / atr

    # ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = calculate_rma(dx, length)

    return adx


# ============================================
# 백테스터 클래스
# ============================================

class HyperScalperBacktester:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.capital = INITIAL_CAPITAL
        self.trades = []

        # 포지션 상태
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.entry_idx = None
        self.entry_size = None
        self.take_profit = None
        self.stop_loss = None
        self.leverage = None

        # 출금 추적
        self.base_capital = INITIAL_CAPITAL  # 현재 사이클 기준 자금
        self.total_withdrawn = 0.0           # 총 출금액
        self.withdrawals = []                # 출금 기록

        # 지표 계산
        self._calculate_indicators()

    def _calculate_indicators(self):
        """지표 계산"""
        # EMA
        self.df['ema_fast'] = calculate_ema(self.df['close'], EMA_FAST)
        self.df['ema_mid'] = calculate_ema(self.df['close'], EMA_MID)
        self.df['ema_slow'] = calculate_ema(self.df['close'], EMA_SLOW)

        # ADX
        self.df['adx'] = calculate_adx(self.df['high'], self.df['low'], self.df['close'], ADX_LENGTH)

        # ATR
        self.df['atr'] = calculate_atr(self.df['high'], self.df['low'], self.df['close'], ATR_LENGTH)

        # Trend conditions
        self.df['bull_trend'] = (
            (self.df['close'] > self.df['ema_slow']) &
            (self.df['ema_fast'] > self.df['ema_mid']) &
            (self.df['ema_mid'] > self.df['ema_slow'])
        )
        self.df['bear_trend'] = (
            (self.df['close'] < self.df['ema_slow']) &
            (self.df['ema_fast'] < self.df['ema_mid']) &
            (self.df['ema_mid'] < self.df['ema_slow'])
        )
        self.df['strong_trend'] = self.df['adx'] >= ADX_THRESHOLD

        # LONG Retest logic: 최근 N봉 내 저가가 EMA25 아래였던 적 있음
        self.df['low_minus_ema_fast'] = self.df['low'] - self.df['ema_fast']
        self.df['had_low_below_fast'] = self.df['low_minus_ema_fast'].rolling(window=RETEST_LOOKBACK).min() < 0

        # SHORT Retest logic: 최근 N봉 내 고가가 EMA25 위였던 적 있음
        self.df['high_minus_ema_fast'] = self.df['high'] - self.df['ema_fast']
        self.df['had_high_above_fast'] = self.df['high_minus_ema_fast'].rolling(window=RETEST_LOOKBACK).max() > 0

        # Reclaim
        self.df['reclaim_long'] = self.df['close'] > self.df['ema_fast']
        self.df['reclaim_short'] = self.df['close'] < self.df['ema_fast']

        # Long signal
        self.df['long_signal'] = (
            self.df['bull_trend'] &
            self.df['strong_trend'] &
            self.df['had_low_below_fast'] &
            self.df['reclaim_long']
        )

        # Short signal
        self.df['short_signal'] = (
            self.df['bear_trend'] &
            self.df['strong_trend'] &
            self.df['had_high_above_fast'] &
            self.df['reclaim_short']
        )

    def calculate_leverage(self, entry_price: float, stop_loss: float) -> float:
        """손절 거리 기반 레버리지 계산"""
        sl_distance_pct = abs(entry_price - stop_loss) / entry_price

        # 진입 수수료(TAKER) + 손절 수수료(TAKER) 포함
        effective_sl = sl_distance_pct + TAKER_FEE * 2

        leverage = RISK_PER_TRADE / effective_sl
        leverage = min(leverage, MAX_LEVERAGE)
        leverage = max(leverage, 1)

        return round(leverage, 2)

    def execute_entry(self, idx: int, direction: str):
        """진입 실행"""
        row = self.df.iloc[idx]

        self.entry_price = row['close']
        self.entry_time = row['timestamp']
        self.entry_idx = idx
        self.position = direction

        # 익절가 설정 (ATR 기반 + 진입 수수료 보전 x2)
        fee_offset = 0
        if( fee_protection == True ):
            fee_offset = self.entry_price * (TAKER_FEE * 2 + MAKER_FEE)
        else:
            fee_offset = 0

        if direction == 'LONG':
            self.take_profit = self.entry_price + row['atr'] * TP_ATR_MULT_LONG + fee_offset
        else:  # SHORT
            self.take_profit = self.entry_price - row['atr'] * TP_ATR_MULT_SHORT - fee_offset

        # 손절가 설정: 최근 N봉 최저가(LONG) / 최고가(SHORT)
        lookback_start = max(0, idx - SL_LOOKBACK)
        lookback_data = self.df.iloc[lookback_start:idx + 1]

        if direction == 'LONG':
            self.stop_loss = lookback_data['low'].min()
        else:  # SHORT
            self.stop_loss = lookback_data['high'].max()

        # [TEST] SL 거리 3% 캡 - 결과 이상하면 삭제
        sl_distance = abs(self.entry_price - self.stop_loss) / self.entry_price
        if sl_distance > MAX_SL_DISTANCE:
            if direction == 'LONG':
                self.stop_loss = self.entry_price * (1 - MAX_SL_DISTANCE)
            else:  # SHORT
                self.stop_loss = self.entry_price * (1 + MAX_SL_DISTANCE)

        # 레버리지 계산: 손절가와의 거리 기준
        self.leverage = self.calculate_leverage(self.entry_price, self.stop_loss)

        # 포지션 크기 계산
        position_value = self.capital * self.leverage
        self.entry_size = position_value / self.entry_price

    def check_exit(self, idx: int) -> tuple:
        """
        청산/손절/익절 체크
        Returns: (should_exit, exit_price, reason)
        우선순위: 청산(LIQ) > 손절(SL) > 익절(TP)
        """
        row = self.df.iloc[idx]

        # 청산가 계산 (레버리지 기준)
        # 예: 20배 → 5% 역행 시 청산
        liq_distance = 1.0 / self.leverage

        if self.position == 'LONG':
            liq_price = self.entry_price * (1 - liq_distance)

            # 청산 체크 (최우선)
            if row['low'] <= liq_price:
                return True, liq_price, 'LIQ'
            # 손절
            if row['low'] <= self.stop_loss:
                return True, self.stop_loss, 'SL'
            # 익절
            if row['high'] >= self.take_profit:
                return True, self.take_profit, 'TP'
        else:  # SHORT
            liq_price = self.entry_price * (1 + liq_distance)

            # 청산 체크 (최우선)
            if row['high'] >= liq_price:
                return True, liq_price, 'LIQ'
            # 손절
            if row['high'] >= self.stop_loss:
                return True, self.stop_loss, 'SL'
            # 익절
            if row['low'] <= self.take_profit:
                return True, self.take_profit, 'TP'

        return False, None, None

    def execute_exit(self, exit_price: float, reason: str) -> dict:
        """청산 실행"""
        if self.position == 'LONG':
            pnl = (exit_price - self.entry_price) * self.entry_size
        else:  # SHORT
            pnl = (self.entry_price - exit_price) * self.entry_size

        # 수수료: 진입(TAKER) + 청산(SL/LIQ=TAKER, TP=MAKER)
        entry_fee = self.entry_price * self.entry_size * TAKER_FEE
        if reason in ['SL', 'LIQ']:
            exit_fee = exit_price * self.entry_size * TAKER_FEE
        else:
            exit_fee = exit_price * self.entry_size * MAKER_FEE

        total_fee = entry_fee + exit_fee
        net_pnl = pnl - total_fee
        self.capital += net_pnl

        return {
            'exit_price': exit_price,
            'pnl': net_pnl
        }

    def close_position(self, result: dict, idx: int, reason: str):
        """포지션 청산 및 거래 기록"""
        row = self.df.iloc[idx]

        trade = {
            'entry_time': self.entry_time,
            'exit_time': row['timestamp'],
            'direction': self.position,
            'entry_price': self.entry_price,
            'exit_price': result['exit_price'],
            'take_profit': self.take_profit,
            'stop_loss': self.stop_loss,
            'leverage': self.leverage,
            'size': self.entry_size,
            'reason': reason,
            'pnl': result['pnl'],
            'balance': self.capital
        }
        self.trades.append(trade)

        # 포지션 초기화
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.entry_idx = None
        self.entry_size = None
        self.take_profit = None
        self.stop_loss = None
        self.leverage = None

    def check_withdrawal(self, timestamp):
        """출금 체크: 기준자금의 N배 도달 시 절반 출금"""
        if not WITHDRAWAL_ENABLED:
            return

        target = self.base_capital * WITHDRAWAL_MULTIPLIER
        if self.capital >= target:
            withdraw_amount = self.capital * WITHDRAWAL_RATIO
            self.capital -= withdraw_amount
            self.total_withdrawn += withdraw_amount

            self.withdrawals.append({
                'timestamp': timestamp,
                'base_capital': self.base_capital,
                'balance_before': self.capital + withdraw_amount,
                'withdrawn': withdraw_amount,
                'balance_after': self.capital,
                'total_withdrawn': self.total_withdrawn
            })

            # 남은 금액을 새 기준자금으로 설정
            self.base_capital = self.capital
            print(f"[WITHDRAWAL] {timestamp}: {withdraw_amount:.2f} USDT 출금 → 잔액: {self.capital:.2f} USDT (총 출금: {self.total_withdrawn:.2f})")

    def run(self):
        """백테스트 실행"""
        print(f"Starting backtest with {len(self.df)} candles")
        print(f"Initial capital: {INITIAL_CAPITAL} USDT")
        print("-" * 50)

        for idx in range(1, len(self.df)):
            row = self.df.iloc[idx]

            # 포지션이 있을 때
            if self.position is not None:
                # 진입봉에서는 체크 안함
                if idx <= self.entry_idx:
                    continue

                # 손절/익절 체크
                should_exit, exit_price, reason = self.check_exit(idx)
                if should_exit:
                    result = self.execute_exit(exit_price, reason)
                    self.close_position(result, idx, reason)
                    self.check_withdrawal(row['timestamp'])
                    continue

            # 포지션이 없을 때 진입 확인
            else:
                if row['long_signal'] and not pd.isna(row['atr']):
                    if TRADE_DIRECTION in ['BOTH', 'LONG']:
                        self.execute_entry(idx, 'LONG')
                elif row['short_signal'] and not pd.isna(row['atr']):
                    if TRADE_DIRECTION in ['BOTH', 'SHORT']:
                        self.execute_entry(idx, 'SHORT')

        # 백테스트 종료 시 열린 포지션 처리
        if self.position is not None:
            last_row = self.df.iloc[-1]
            exit_price = last_row['close']
            result = self.execute_exit(exit_price, 'END')
            self.close_position(result, len(self.df) - 1, 'END')

        self._print_results()
        return self.trades

    def _print_results(self):
        """결과 출력"""
        print("\n" + "=" * 50)
        print("BACKTEST RESULTS")
        print("=" * 50)

        total_trades = len(self.trades)
        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in self.trades)

        # LONG/SHORT 분리
        long_trades = [t for t in self.trades if t['direction'] == 'LONG']
        short_trades = [t for t in self.trades if t['direction'] == 'SHORT']
        long_wins = [t for t in long_trades if t['pnl'] > 0]
        short_wins = [t for t in short_trades if t['pnl'] > 0]

        # 청산(LIQ) 횟수
        liquidations = [t for t in self.trades if t['reason'] == 'LIQ']

        print(f"Total Trades: {total_trades}")
        print(f"  - Long: {len(long_trades)} (Win: {len(long_wins)})")
        print(f"  - Short: {len(short_trades)} (Win: {len(short_wins)})")
        print(f"Wins: {len(wins)}")
        print(f"Losses: {len(losses)}")
        if len(liquidations) > 0:
            print(f"Liquidations: {len(liquidations)} (!!)")

        if total_trades > 0:
            win_rate = len(wins) / total_trades * 100
            print(f"Win Rate: {win_rate:.2f}%")

        if len(long_trades) > 0:
            long_win_rate = len(long_wins) / len(long_trades) * 100
            long_pnl = sum(t['pnl'] for t in long_trades)
            print(f"  - Long Win Rate: {long_win_rate:.2f}%, PnL: {long_pnl:.2f} USDT")

        if len(short_trades) > 0:
            short_win_rate = len(short_wins) / len(short_trades) * 100
            short_pnl = sum(t['pnl'] for t in short_trades)
            print(f"  - Short Win Rate: {short_win_rate:.2f}%, PnL: {short_pnl:.2f} USDT")

        # MDD 계산
        if total_trades > 0:
            peak = INITIAL_CAPITAL
            max_drawdown = 0
            for t in self.trades:
                if t['balance'] > peak:
                    peak = t['balance']
                drawdown = (peak - t['balance']) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            print(f"\nMDD: {max_drawdown * 100:.2f}%")

        print(f"Total PnL: {total_pnl:.2f} USDT")
        print(f"Final Capital: {self.capital:.2f} USDT")
        print(f"Return: {(self.capital / INITIAL_CAPITAL - 1) * 100:.2f}%")

        # 출금 정보
        if WITHDRAWAL_ENABLED and self.total_withdrawn > 0:
            print(f"\n--- Withdrawal Summary ---")
            print(f"Total Withdrawn: {self.total_withdrawn:.2f} USDT")
            print(f"Withdrawal Count: {len(self.withdrawals)}")
            print(f"Final + Withdrawn: {self.capital + self.total_withdrawn:.2f} USDT")
            print(f"Actual Return: {((self.capital + self.total_withdrawn) / INITIAL_CAPITAL - 1) * 100:.2f}%")

    def save_trades(self, filename: str):
        """거래 내역 CSV 저장"""
        if not self.trades:
            print("No trades to save")
            return

        df = pd.DataFrame(self.trades)
        df.to_csv(filename, index=False)
        print(f"Trades saved to {filename}")

    def save_data_with_indicators(self, filename: str):
        """지표가 포함된 데이터 저장"""
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                'ema_fast', 'ema_mid', 'ema_slow', 'adx', 'atr', 'long_signal', 'short_signal']
        self.df[cols].to_csv(filename, index=False)
        print(f"Data with indicators saved to {filename}")


# ============================================
# 메인 실행
# ============================================

if __name__ == "__main__":
    # 데이터 로드
    print("Loading data...")
    df = pd.read_csv('historical_data/BTCUSDT_15m_raw.csv')

    # 컬럼명 소문자로 변환
    df.columns = df.columns.str.lower()

    # timestamp 컬럼 처리
    if 'timestamp' not in df.columns and 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    elif 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    print(f"Full data: {len(df)} candles")
    print(f"Full date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    # 기간 필터링
    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)

    print(f"\nFiltered data: {len(df)} candles")
    print(f"Backtest period: {START_DATE} to {END_DATE}")

    # 백테스터 실행
    backtester = HyperScalperBacktester(df)
    trades = backtester.run()

    # 결과 저장
    backtester.save_trades('trades_hyper_scalper_v2.csv')
    backtester.save_data_with_indicators('data_with_hyper_scalper_v2.csv')

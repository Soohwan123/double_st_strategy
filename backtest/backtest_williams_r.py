"""
Williams %R + EMA Momentum Strategy Backtester (BTC 5m)
%R이 과매도에서 반등 + EMA 위 → LONG
%R이 과매수에서 하락 + EMA 아래 → SHORT

LONG 진입 조건:
1. ADX >= ADX_THRESHOLD (추세 강도 확인)
2. %R[prev] < WR_THRESH AND %R[curr] > WR_THRESH (과매도 탈출 크로스)
3. close > EMA50 (상승 추세 필터)
- 익절: 진입가 + ATR * TP_ATR_MULT + fee_offset
- 손절: 최근 SL_LOOKBACK봉 최저가

SHORT 진입 조건:
1. ADX >= ADX_THRESHOLD
2. %R[prev] > WR_OVERBOUGHT AND %R[curr] < WR_OVERBOUGHT (과매수 진입 크로스)
3. close < EMA50 (하락 추세 필터)
- 익절: 진입가 - ATR * TP_ATR_MULT - fee_offset
- 손절: 최근 SL_LOOKBACK봉 최고가
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ============================================
# 파라미터 설정
# ============================================
INITIAL_CAPITAL = 10000.0
MAX_LEVERAGE = 100
RISK_PER_TRADE = 0.07

TRADE_DIRECTION = 'BOTH'

# 출금 설정
WITHDRAWAL_ENABLED = False
WITHDRAWAL_MULTIPLIER = 100
WITHDRAWAL_RATIO = 0.5

# ADX 설정
ADX_LENGTH = 14
ADX_THRESHOLD = 50.0

# Williams %R 설정
WR_PERIOD = 7
WR_THRESH = -80        # 과매도 기준 (이 아래면 과매도)
WR_OVERBOUGHT = -20    # 과매수 기준 (-100 - WR_THRESH = -20)

# EMA 추세 필터
EMA_TREND = 50

# 손절 설정
SL_LOOKBACK = 20
MAX_SL_DISTANCE = 0.03

# ATR 설정
ATR_LENGTH = 14
TP_ATR_MULT = 10.0

# 수수료
MAKER_FEE = 0.0002
TAKER_FEE = 0.0005
fee_protection = True

# ============================================
# 백테스트 기간 설정
# ============================================
START_DATE = '2020-01-01'
END_DATE = '2026-03-05'


# ============================================
# TradingView 호환 지표 계산 함수
# ============================================

def calculate_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def calculate_rma(series: pd.Series, length: int) -> pd.Series:
    alpha = 1.0 / length
    result = np.zeros(len(series))
    result[:] = np.nan
    if len(series) >= length:
        result[length - 1] = series.iloc[:length].mean()
        for i in range(length, len(series)):
            result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=series.index)


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return calculate_rma(tr, length)


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    atr = calculate_rma(tr, length)
    plus_di = 100 * calculate_rma(plus_dm, length) / atr
    minus_di = 100 * calculate_rma(minus_dm, length) / atr

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = calculate_rma(dx, length)
    return adx


def calculate_williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    wr = pd.Series(np.nan, index=close.index)
    for i in range(period - 1, len(close)):
        hh = high.iloc[i - period + 1:i + 1].max()
        ll = low.iloc[i - period + 1:i + 1].min()
        if hh - ll > 0:
            wr.iloc[i] = -100 * (hh - close.iloc[i]) / (hh - ll)
        else:
            wr.iloc[i] = -50.0
    return wr


# ============================================
# 백테스터 클래스
# ============================================

class WilliamsRBacktester:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.capital = INITIAL_CAPITAL
        self.trades = []

        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.entry_idx = None
        self.entry_size = None
        self.take_profit = None
        self.stop_loss = None
        self.leverage = None

        self.base_capital = INITIAL_CAPITAL
        self.total_withdrawn = 0.0
        self.withdrawals = []

        self._calculate_indicators()

    def _calculate_indicators(self):
        # ADX
        self.df['adx'] = calculate_adx(self.df['high'], self.df['low'], self.df['close'], ADX_LENGTH)
        # ATR
        self.df['atr'] = calculate_atr(self.df['high'], self.df['low'], self.df['close'], ATR_LENGTH)
        # EMA
        self.df['ema'] = calculate_ema(self.df['close'], EMA_TREND)
        # Williams %R
        self.df['wr'] = calculate_williams_r(self.df['high'], self.df['low'], self.df['close'], WR_PERIOD)

        # SL lookback
        self.df['sl_low'] = self.df['low'].rolling(window=SL_LOOKBACK + 1, min_periods=1).min()
        self.df['sl_high'] = self.df['high'].rolling(window=SL_LOOKBACK + 1, min_periods=1).max()

    def calculate_leverage(self, entry_price: float, stop_loss: float) -> float:
        sl_distance_pct = abs(entry_price - stop_loss) / entry_price
        effective_sl = sl_distance_pct + TAKER_FEE * 2
        leverage = RISK_PER_TRADE / effective_sl
        leverage = min(leverage, MAX_LEVERAGE)
        leverage = max(leverage, 1)
        return round(leverage, 2)

    def execute_entry(self, idx: int, direction: str):
        row = self.df.iloc[idx]
        self.entry_price = row['close']
        self.entry_time = row['timestamp']
        self.entry_idx = idx
        self.position = direction

        fee_offset = 0
        if fee_protection:
            fee_offset = self.entry_price * (TAKER_FEE * 2 + MAKER_FEE)

        if direction == 'LONG':
            self.take_profit = self.entry_price + row['atr'] * TP_ATR_MULT + fee_offset
        else:
            self.take_profit = self.entry_price - row['atr'] * TP_ATR_MULT - fee_offset

        if direction == 'LONG':
            self.stop_loss = row['sl_low']
        else:
            self.stop_loss = row['sl_high']

        # SL >= entry 방지
        if direction == 'LONG' and self.stop_loss >= self.entry_price:
            self.stop_loss = self.entry_price * (1 - 0.001)
        elif direction == 'SHORT' and self.stop_loss <= self.entry_price:
            self.stop_loss = self.entry_price * (1 + 0.001)

        # SL 거리 캡
        sl_distance = abs(self.entry_price - self.stop_loss) / self.entry_price
        if sl_distance > MAX_SL_DISTANCE:
            if direction == 'LONG':
                self.stop_loss = self.entry_price * (1 - MAX_SL_DISTANCE)
            else:
                self.stop_loss = self.entry_price * (1 + MAX_SL_DISTANCE)

        self.leverage = self.calculate_leverage(self.entry_price, self.stop_loss)
        position_value = self.capital * self.leverage
        self.entry_size = position_value / self.entry_price

    def check_exit(self, idx: int) -> tuple:
        row = self.df.iloc[idx]
        liq_distance = 1.0 / self.leverage

        if self.position == 'LONG':
            liq_price = self.entry_price * (1 - liq_distance)
            if row['low'] <= liq_price:
                return True, liq_price, 'LIQ'
            if row['low'] <= self.stop_loss:
                return True, self.stop_loss, 'SL'
            if row['high'] >= self.take_profit:
                return True, self.take_profit, 'TP'
        else:
            liq_price = self.entry_price * (1 + liq_distance)
            if row['high'] >= liq_price:
                return True, liq_price, 'LIQ'
            if row['high'] >= self.stop_loss:
                return True, self.stop_loss, 'SL'
            if row['low'] <= self.take_profit:
                return True, self.take_profit, 'TP'

        return False, None, None

    def execute_exit(self, exit_price: float, reason: str) -> dict:
        if self.position == 'LONG':
            pnl = (exit_price - self.entry_price) * self.entry_size
        else:
            pnl = (self.entry_price - exit_price) * self.entry_size

        entry_fee = self.entry_price * self.entry_size * TAKER_FEE
        if reason in ['SL', 'LIQ']:
            exit_fee = exit_price * self.entry_size * TAKER_FEE
        else:
            exit_fee = exit_price * self.entry_size * MAKER_FEE

        total_fee = entry_fee + exit_fee
        net_pnl = pnl - total_fee
        self.capital += net_pnl

        return {'exit_price': exit_price, 'pnl': net_pnl}

    def close_position(self, result: dict, idx: int, reason: str):
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

        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.entry_idx = None
        self.entry_size = None
        self.take_profit = None
        self.stop_loss = None
        self.leverage = None

    def check_withdrawal(self, timestamp):
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
            self.base_capital = self.capital
            print(f"[WITHDRAWAL] {timestamp}: {withdraw_amount:.2f} USDT 출금 → 잔액: {self.capital:.2f} USDT (총 출금: {self.total_withdrawn:.2f})")

    def run(self):
        print(f"Starting backtest with {len(self.df)} candles")
        print(f"Initial capital: {INITIAL_CAPITAL} USDT")
        print(f"Strategy: Williams %R({WR_PERIOD}) + EMA({EMA_TREND})")
        print(f"Params: ADX>={ADX_THRESHOLD}, TP={TP_ATR_MULT}xATR, SL_LB={SL_LOOKBACK}, RISK={RISK_PER_TRADE*100}%")
        print(f"WR Thresh={WR_THRESH}, Overbought={WR_OVERBOUGHT}")
        print("-" * 50)

        start_idx = max(SL_LOOKBACK + 1, WR_PERIOD + 5, EMA_TREND + 5)

        for idx in range(start_idx, len(self.df)):
            row = self.df.iloc[idx]

            if self.position is not None:
                if idx <= self.entry_idx:
                    continue
                should_exit, exit_price, reason = self.check_exit(idx)
                if should_exit:
                    result = self.execute_exit(exit_price, reason)
                    self.close_position(result, idx, reason)
                    self.check_withdrawal(row['timestamp'])
                    continue
            else:
                if pd.isna(row['atr']) or pd.isna(row['adx']) or row['adx'] < ADX_THRESHOLD:
                    continue
                if pd.isna(row['wr']) or pd.isna(row['ema']):
                    continue

                prev = self.df.iloc[idx - 1]
                if pd.isna(prev['wr']):
                    continue

                # LONG: %R crosses above thresh from below + price > EMA
                long_sig = (prev['wr'] < WR_THRESH and
                           row['wr'] > WR_THRESH and
                           row['close'] > row['ema'])

                # SHORT: %R crosses below overbought from above + price < EMA
                short_sig = (prev['wr'] > WR_OVERBOUGHT and
                            row['wr'] < WR_OVERBOUGHT and
                            row['close'] < row['ema'])

                if long_sig and TRADE_DIRECTION in ['BOTH', 'LONG']:
                    self.execute_entry(idx, 'LONG')
                elif short_sig and TRADE_DIRECTION in ['BOTH', 'SHORT']:
                    self.execute_entry(idx, 'SHORT')

        if self.position is not None:
            last_row = self.df.iloc[-1]
            result = self.execute_exit(last_row['close'], 'END')
            self.close_position(result, len(self.df) - 1, 'END')

        self._print_results()
        return self.trades

    def _print_results(self):
        print("\n" + "=" * 50)
        print("BACKTEST RESULTS")
        print("=" * 50)

        total_trades = len(self.trades)
        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in self.trades)

        long_trades = [t for t in self.trades if t['direction'] == 'LONG']
        short_trades = [t for t in self.trades if t['direction'] == 'SHORT']
        long_wins = [t for t in long_trades if t['pnl'] > 0]
        short_wins = [t for t in short_trades if t['pnl'] > 0]
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

        if WITHDRAWAL_ENABLED and self.total_withdrawn > 0:
            print(f"\n--- Withdrawal Summary ---")
            print(f"Total Withdrawn: {self.total_withdrawn:.2f} USDT")
            print(f"Withdrawal Count: {len(self.withdrawals)}")
            print(f"Final + Withdrawn: {self.capital + self.total_withdrawn:.2f} USDT")
            print(f"Actual Return: {((self.capital + self.total_withdrawn) / INITIAL_CAPITAL - 1) * 100:.2f}%")

    def save_trades(self, filename: str):
        if not self.trades:
            print("No trades to save")
            return
        df = pd.DataFrame(self.trades)
        df.to_csv(filename, index=False)
        print(f"Trades saved to {filename}")


# ============================================
# 메인 실행
# ============================================

if __name__ == "__main__":
    print("Loading data...")
    df = pd.read_csv('historical_data/BTCUSDT_5m_futures.csv')
    df.columns = df.columns.str.lower()

    if 'timestamp' not in df.columns and 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    elif 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    print(f"Full data: {len(df)} candles")
    print(f"Full date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)

    print(f"\nFiltered data: {len(df)} candles")
    print(f"Backtest period: {START_DATE} to {END_DATE}")

    backtester = WilliamsRBacktester(df)
    trades = backtester.run()
    backtester.save_trades('trades_williams_r.csv')

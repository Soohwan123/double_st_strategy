"""
BTC 15m VWAP Momentum Convergence Strategy Backtester
Daily VWAP + EMA 21/50 + MACD(12,26,9) + ADX Filter

LONG 진입 조건:
1. 가격(close) > Daily VWAP (매수세 우위)
2. EMA21 > EMA50 (정배열)
3. MACD 히스토그램이 음→양 전환 (모멘텀 확인)
4. ADX >= ADX_THRESHOLD (강한 추세)
- 손절: 최근 N봉 최저가
- 익절: 진입가 + ATR * TP_ATR_MULT

SHORT 진입 조건:
1. 가격(close) < Daily VWAP
2. EMA21 < EMA50 (역배열)
3. MACD 히스토그램이 양→음 전환
4. ADX >= ADX_THRESHOLD
- 손절: 최근 N봉 최고가
- 익절: 진입가 - ATR * TP_ATR_MULT
"""

import pandas as pd
import numpy as np


# ============================================
# 파라미터 설정 (Fine-tuned 최적값)
# ============================================
INITIAL_CAPITAL = 11000.0
MAX_LEVERAGE = 90
RISK_PER_TRADE = 0.07

TRADE_DIRECTION = 'BOTH'

# EMA 설정
EMA_FAST = 21
EMA_SLOW = 50

# MACD 설정
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ADX 설정
ADX_LENGTH = 14
ADX_THRESHOLD = 33

# 손절 설정
SL_LOOKBACK = 10
MAX_SL_DISTANCE = 0.027

# ATR 설정 (익절용)
ATR_LENGTH = 14
TP_ATR_MULT_LONG = 8.6
TP_ATR_MULT_SHORT = 8.6

# 수수료
MAKER_FEE = 0.0002
TAKER_FEE = 0.0005
fee_protection = True

# ============================================
# 백테스트 기간
# ============================================
START_DATE = '2019-01-05'
END_DATE = '2026-02-20'


# ============================================
# 지표 계산 함수
# ============================================

def calculate_rma(series: pd.Series, length: int) -> pd.Series:
    alpha = 1.0 / length
    result = np.zeros(len(series))
    result[:] = np.nan
    if len(series) >= length:
        result[length - 1] = series.iloc[:length].mean()
        for i in range(length, len(series)):
            result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=series.index)


def calculate_atr(high, low, close, length):
    prev_close = close.shift(1)
    tr = pd.concat([high - low, abs(high - prev_close), abs(low - prev_close)], axis=1).max(axis=1)
    return calculate_rma(tr, length)


def calculate_adx(high, low, close, length):
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    prev_close = close.shift(1)
    tr = pd.concat([high - low, abs(high - prev_close), abs(low - prev_close)], axis=1).max(axis=1)

    atr_val = calculate_rma(tr, length)
    plus_di_raw = calculate_rma(plus_dm, length)
    minus_di_raw = calculate_rma(minus_dm, length)

    plus_di = pd.Series(np.where(atr_val > 0, 100 * plus_di_raw / atr_val, 0.0), index=high.index)
    minus_di = pd.Series(np.where(atr_val > 0, 100 * minus_di_raw / atr_val, 0.0), index=high.index)

    di_sum = plus_di + minus_di
    dx = pd.Series(np.where(di_sum > 0, 100 * abs(plus_di - minus_di) / di_sum, 0.0), index=high.index)
    adx = calculate_rma(dx, length)
    return adx


def calculate_daily_vwap(df):
    """Daily VWAP (UTC 00:00 리셋)"""
    df = df.copy()
    df['date'] = df['timestamp'].dt.date
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['tp_vol'] = df['typical_price'] * df['volume']
    df['cum_tp_vol'] = df.groupby('date')['tp_vol'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_tp_vol'] / df['cum_vol'], np.nan)
    return df['vwap']


# ============================================
# 백테스터 클래스
# ============================================

class VWAPMomentumBacktester:
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

        self._calculate_indicators()

    def _calculate_indicators(self):
        # VWAP
        self.df['vwap'] = calculate_daily_vwap(self.df)

        # EMA
        self.df['ema_fast'] = self.df['close'].ewm(span=EMA_FAST, adjust=False).mean()
        self.df['ema_slow'] = self.df['close'].ewm(span=EMA_SLOW, adjust=False).mean()

        # MACD
        ema12 = self.df['close'].ewm(span=MACD_FAST, adjust=False).mean()
        ema26 = self.df['close'].ewm(span=MACD_SLOW, adjust=False).mean()
        self.df['macd_line'] = ema12 - ema26
        self.df['macd_signal'] = self.df['macd_line'].ewm(span=MACD_SIGNAL, adjust=False).mean()
        self.df['macd_hist'] = self.df['macd_line'] - self.df['macd_signal']

        # MACD 히스토그램 교차 신호
        prev_hist = self.df['macd_hist'].shift(1)
        self.df['macd_long_cross'] = (prev_hist <= 0) & (self.df['macd_hist'] > 0)
        self.df['macd_short_cross'] = (prev_hist >= 0) & (self.df['macd_hist'] < 0)

        # ATR
        self.df['atr'] = calculate_atr(self.df['high'], self.df['low'], self.df['close'], ATR_LENGTH)

        # ADX
        self.df['adx'] = calculate_adx(self.df['high'], self.df['low'], self.df['close'], ADX_LENGTH)

        # Trend
        self.df['bull_trend'] = (self.df['close'] > self.df['vwap']) & (self.df['ema_fast'] > self.df['ema_slow'])
        self.df['bear_trend'] = (self.df['close'] < self.df['vwap']) & (self.df['ema_fast'] < self.df['ema_slow'])

    def calculate_leverage(self, entry_price, stop_loss):
        sl_distance_pct = abs(entry_price - stop_loss) / entry_price
        effective_sl = sl_distance_pct + TAKER_FEE * 2
        leverage = RISK_PER_TRADE / effective_sl
        return round(max(1, min(leverage, MAX_LEVERAGE)), 2)

    def execute_entry(self, idx, direction):
        row = self.df.iloc[idx]
        self.entry_price = row['close']
        self.entry_time = row['timestamp']
        self.entry_idx = idx
        self.position = direction

        # SL: N봉 최저/최고
        lb_start = max(0, idx - SL_LOOKBACK)
        lb_data = self.df.iloc[lb_start:idx + 1]

        if direction == 'LONG':
            self.stop_loss = lb_data['low'].min()
            if self.stop_loss >= self.entry_price:
                self.stop_loss = self.entry_price * (1 - 0.001)
        else:
            self.stop_loss = lb_data['high'].max()
            if self.stop_loss <= self.entry_price:
                self.stop_loss = self.entry_price * (1 + 0.001)

        sl_distance = abs(self.entry_price - self.stop_loss) / self.entry_price
        if sl_distance > MAX_SL_DISTANCE:
            if direction == 'LONG':
                self.stop_loss = self.entry_price * (1 - MAX_SL_DISTANCE)
            else:
                self.stop_loss = self.entry_price * (1 + MAX_SL_DISTANCE)

        self.leverage = self.calculate_leverage(self.entry_price, self.stop_loss)
        self.entry_size = self.capital * self.leverage / self.entry_price

        fee_offset = self.entry_price * (TAKER_FEE * 2 + MAKER_FEE) if fee_protection else 0
        if direction == 'LONG':
            self.take_profit = self.entry_price + row['atr'] * TP_ATR_MULT_LONG + fee_offset
        else:
            self.take_profit = self.entry_price - row['atr'] * TP_ATR_MULT_SHORT - fee_offset

    def check_exit(self, idx):
        row = self.df.iloc[idx]
        liq_dist = 1.0 / self.leverage

        if self.position == 'LONG':
            liq_p = self.entry_price * (1 - liq_dist)
            if row['low'] <= liq_p: return True, liq_p, 'LIQ'
            if row['low'] <= self.stop_loss: return True, self.stop_loss, 'SL'
            if row['high'] >= self.take_profit: return True, self.take_profit, 'TP'
        else:
            liq_p = self.entry_price * (1 + liq_dist)
            if row['high'] >= liq_p: return True, liq_p, 'LIQ'
            if row['high'] >= self.stop_loss: return True, self.stop_loss, 'SL'
            if row['low'] <= self.take_profit: return True, self.take_profit, 'TP'
        return False, None, None

    def execute_exit(self, exit_price, reason):
        if self.position == 'LONG':
            pnl = (exit_price - self.entry_price) * self.entry_size
        else:
            pnl = (self.entry_price - exit_price) * self.entry_size

        e_fee = self.entry_price * self.entry_size * TAKER_FEE
        x_fee = exit_price * self.entry_size * (TAKER_FEE if reason in ['SL', 'LIQ'] else MAKER_FEE)
        net_pnl = pnl - e_fee - x_fee
        self.capital += net_pnl
        return {'exit_price': exit_price, 'pnl': net_pnl}

    def close_position(self, result, idx, reason):
        row = self.df.iloc[idx]
        self.trades.append({
            'entry_time': self.entry_time, 'exit_time': row['timestamp'],
            'direction': self.position, 'entry_price': self.entry_price,
            'exit_price': result['exit_price'], 'take_profit': self.take_profit,
            'stop_loss': self.stop_loss, 'leverage': self.leverage,
            'size': self.entry_size, 'reason': reason,
            'pnl': result['pnl'], 'balance': self.capital
        })
        self.position = self.entry_price = self.entry_time = None
        self.entry_idx = self.entry_size = self.take_profit = None
        self.stop_loss = self.leverage = None

    def run(self):
        print(f"Starting backtest with {len(self.df)} candles")
        print(f"VWAP Momentum: Daily VWAP + EMA{EMA_FAST}/{EMA_SLOW} + MACD({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) + ADX>={ADX_THRESHOLD}")
        print(f"SL: {SL_LOOKBACK}봉 lookback, TP: ATR*{TP_ATR_MULT_LONG}, RISK: {RISK_PER_TRADE*100}%")
        print("-" * 60)

        for idx in range(SL_LOOKBACK + 1, len(self.df)):
            row = self.df.iloc[idx]

            if self.position is not None:
                if idx <= self.entry_idx:
                    continue
                should_exit, exit_price, reason = self.check_exit(idx)
                if should_exit:
                    result = self.execute_exit(exit_price, reason)
                    self.close_position(result, idx, reason)
                    continue
            else:
                if pd.isna(row['atr']) or pd.isna(row['vwap']) or pd.isna(row['macd_hist']):
                    continue
                if pd.isna(row['adx']) or row['adx'] < ADX_THRESHOLD:
                    continue

                if row['bull_trend'] and row['macd_long_cross']:
                    if TRADE_DIRECTION in ['BOTH', 'LONG']:
                        self.execute_entry(idx, 'LONG')
                elif row['bear_trend'] and row['macd_short_cross']:
                    if TRADE_DIRECTION in ['BOTH', 'SHORT']:
                        self.execute_entry(idx, 'SHORT')

        if self.position is not None:
            result = self.execute_exit(self.df.iloc[-1]['close'], 'END')
            self.close_position(result, len(self.df) - 1, 'END')

        self._print_results()
        return self.trades

    def _print_results(self):
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS - VWAP Momentum + ADX Filter")
        print("=" * 60)

        total = len(self.trades)
        wins = [t for t in self.trades if t['pnl'] > 0]
        long_t = [t for t in self.trades if t['direction'] == 'LONG']
        short_t = [t for t in self.trades if t['direction'] == 'SHORT']
        liqs = [t for t in self.trades if t['reason'] == 'LIQ']
        tps = [t for t in self.trades if t['reason'] == 'TP']
        sls = [t for t in self.trades if t['reason'] == 'SL']

        print(f"Total Trades: {total}")
        print(f"  Long: {len(long_t)} (Win: {len([t for t in long_t if t['pnl']>0])})")
        print(f"  Short: {len(short_t)} (Win: {len([t for t in short_t if t['pnl']>0])})")
        print(f"  TP: {len(tps)} | SL: {len(sls)} | LIQ: {len(liqs)}")
        if total > 0:
            print(f"Win Rate: {len(wins)/total*100:.2f}%")
            avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
            avg_loss = np.mean([t['pnl'] for t in self.trades if t['pnl'] <= 0]) if len(self.trades) > len(wins) else 0
            print(f"Avg Win: {avg_win:.2f} USDT | Avg Loss: {avg_loss:.2f} USDT")
            if avg_loss != 0:
                print(f"Profit Factor: {abs(avg_win * len(wins)) / abs(avg_loss * (total - len(wins))):.2f}")
            peak = INITIAL_CAPITAL
            mdd = 0
            for t in self.trades:
                if t['balance'] > peak: peak = t['balance']
                dd = (peak - t['balance']) / peak
                if dd > mdd: mdd = dd
            print(f"MDD: {mdd*100:.2f}%")
        print(f"Total PnL: {sum(t['pnl'] for t in self.trades):.2f} USDT")
        print(f"Final Capital: {self.capital:.2f} USDT")
        print(f"Return: {(self.capital/INITIAL_CAPITAL-1)*100:.2f}%")

    def save_trades(self, filename):
        if self.trades:
            pd.DataFrame(self.trades).to_csv(filename, index=False)
            print(f"Trades saved to {filename}")


# ============================================
# 메인
# ============================================
if __name__ == "__main__":
    print("Loading data...")
    df = pd.read_csv('historical_data/BTCUSDT_15m_raw.csv')
    df.columns = df.columns.str.lower()
    if 'timestamp' not in df.columns and 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    elif 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    first_real = df.index[(df['high'] != df['low'])][0] if (df['high'] != df['low']).any() else 0
    if first_real > 0:
        print(f"Skipping {first_real} dummy rows")
        df = df.iloc[first_real:].reset_index(drop=True)

    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)
    print(f"Data: {len(df)} candles ({START_DATE} ~ {END_DATE})")

    bt = VWAPMomentumBacktester(df)
    bt.run()
    bt.save_trades('trades_vwap_momentum_15m.csv')


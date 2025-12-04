"""
MA Distance 전략 백테스트

전략 개요:
- 롱 전용 전략
- 이격도(MA50-MA200 거리 %) 기반 진입
- 이격도 -2.0% 이하 → -1.5% 이하 회복 + 50SMA 위 마감 시 진입
- 시나리오 1: 200선 터치 → 절반 매도 → 1시간봉 200SMA 익절
- 시나리오 2: 물타기 및 90% 덜어내기 반복

사용법:
    python backtest_ma_distance.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os

# ================================================================================
# CONFIG
# ================================================================================

# 입력 파일
INPUT_FILE = 'backtest_data/BTCUSDT_sma_mtf.csv'

# 출력 파일
OUTPUT_TRADES = 'backtest_data/trades_ma_distance.csv'

# 초기 자본
INITIAL_CAPITAL = 1000

# 수수료 (시장가/지정가 모두 수수료 발생)
TAKER_FEE = 0.000275  # 0.0275%

# 진입 설정
FIRST_ENTRY_RATIO = 0.10       # 첫 진입: 자본의 10%
FIRST_ENTRY_LEVERAGE = 5       # 첫 진입 레버리지
SECOND_ENTRY_RATIO = 0.90      # 두 번째 진입: 자본의 90%
SECOND_ENTRY_LEVERAGE = 10     # 두 번째 진입 레버리지

# 이격도 기준
DISTANCE_TRIGGER = -2.0        # 플래그 ON 조건
DISTANCE_READY = -1.5          # 진입 준비 조건

# 익절/손절
BREAKEVEN_BUFFER = 0.0005      # 본절 + 0.05%
TAKE_PROFIT_BUFFER = 0.0001    # 평단가 + 0.01% 에서 90% 덜어내기
LOOKBACK_BARS = 100            # 손절가 계산용 lookback

# 데이터 기간
START_DATE = '2025-01-01'
END_DATE = '2025-12-31'


# ================================================================================
# 백테스터 클래스
# ================================================================================

class MADistanceBacktester:
    def __init__(self, df):
        self.df = df.reset_index(drop=True)
        self.capital = INITIAL_CAPITAL
        self.base_capital = INITIAL_CAPITAL  # 기준 자본 (손절 후 리셋)

        # 상태 변수
        self.flag_triggered = False      # 이격도 -2.0% 이하 찍었는지
        self.ready_to_enter = False      # 진입 준비 상태
        self.min_distance = 0            # 이격도 최저점 추적

        # 포지션
        self.position = None             # {'entry_price', 'btc_amount', 'entry_value', 'entry_bar'}
        self.first_entry_done = False    # 첫 진입 완료 여부
        self.second_entry_done = False   # 두 번째 진입 완료 여부
        self.sold_50_vwma = False        # VWMA에서 50% 익절 여부
        self.sold_25_200 = False         # 200SMA에서 25% 익절 여부
        self.initial_btc_amount = 0      # 최초 진입 시 BTC 수량 (비율 계산용)
        self.partial_sold = False        # 90% 덜어내기 여부
        self.stop_loss_price = None      # 손절가

        # 물타기 상태
        self.water_entry_active = False  # 물타기 진입 활성화
        self.water_entry_price = None    # 물타기 진입가
        self.dropped_below_50 = False    # 50선 아래로 떨어졌는지 여부

        # 거래 기록
        self.trades = []
        self.trade_id = 0

    def calculate_distance(self, row):
        """이격도 계산: (SMA50 - SMA200) / SMA200 * 100"""
        return (row['sma_50'] - row['sma_200']) / row['sma_200'] * 100

    def get_lookback_low(self, current_idx):
        """현재 인덱스로부터 LOOKBACK_BARS 이전까지의 최저가"""
        start_idx = max(0, current_idx - LOOKBACK_BARS)
        return self.df.loc[start_idx:current_idx, 'Low'].min()

    def calculate_avg_entry_price(self):
        """평균 진입가 계산"""
        if self.position is None:
            return None
        return self.position['entry_value'] / self.position['btc_amount']

    def record_trade(self, timestamp, action, price, btc_amount, value, reason, pnl=0):
        """거래 기록"""
        self.trades.append({
            'trade_id': self.trade_id,
            'timestamp': timestamp,
            'action': action,
            'price': price,
            'btc_amount': btc_amount,
            'value': value,
            'reason': reason,
            'pnl': pnl,
            'capital': self.capital,
            'position_btc': self.position['btc_amount'] if self.position else 0,
            'avg_entry': self.calculate_avg_entry_price() if self.position else 0
        })

    def enter_position(self, row, idx, entry_ratio, leverage, reason):
        """포지션 진입"""
        entry_price = row['Close']
        entry_value = self.base_capital * entry_ratio * leverage
        btc_amount = entry_value / entry_price

        # 수수료 계산 (진입)
        entry_fee = entry_value * TAKER_FEE
        self.capital -= entry_fee

        if self.position is None:
            self.position = {
                'entry_price': entry_price,
                'btc_amount': btc_amount,
                'entry_value': entry_value,
                'entry_bar': idx
            }
        else:
            # 기존 포지션에 추가 (평단가 재계산)
            total_value = self.position['entry_value'] + entry_value
            total_btc = self.position['btc_amount'] + btc_amount
            self.position['entry_value'] = total_value
            self.position['btc_amount'] = total_btc
            self.position['entry_price'] = total_value / total_btc

        self.record_trade(row['timestamp'], 'ENTRY', entry_price, btc_amount, entry_value, reason)
        print(f"   [{reason}] 진입 @ {entry_price:,.1f} | {btc_amount:.6f} BTC | 수수료: ${entry_fee:.2f}")

    def close_position(self, row, btc_to_sell, reason, exit_price=None):
        """포지션 청산 (일부 또는 전체)"""
        if self.position is None:
            return 0

        if exit_price is None:
            exit_price = row['Close']

        # 청산할 BTC 수량
        btc_to_sell = min(btc_to_sell, self.position['btc_amount'])
        exit_value = btc_to_sell * exit_price

        # 진입 비용 비례 계산
        entry_cost_ratio = btc_to_sell / self.position['btc_amount']
        entry_cost = self.position['entry_value'] * entry_cost_ratio

        # 수수료 계산 (청산)
        exit_fee = exit_value * TAKER_FEE

        # PnL 계산
        gross_pnl = exit_value - entry_cost
        net_pnl = gross_pnl - exit_fee

        self.capital += net_pnl

        # 포지션 업데이트
        self.position['btc_amount'] -= btc_to_sell
        self.position['entry_value'] -= entry_cost

        if self.position['btc_amount'] <= 0.00000001:
            self.position = None

        self.record_trade(row['timestamp'], 'EXIT', exit_price, btc_to_sell, exit_value, reason, net_pnl)
        pnl_pct = (net_pnl / entry_cost) * 100 if entry_cost > 0 else 0
        print(f"   [{reason}] 청산 @ {exit_price:,.1f} | {btc_to_sell:.6f} BTC | PnL: ${net_pnl:.2f} ({pnl_pct:+.2f}%)")

        return net_pnl

    def reset_state(self, keep_flag=False):
        """상태 초기화"""
        if not keep_flag:
            self.flag_triggered = False
        self.ready_to_enter = False
        self.min_distance = 0
        self.first_entry_done = False
        self.second_entry_done = False
        self.touched_200 = False
        self.sold_half = False
        self.partial_sold = False
        self.stop_loss_price = None
        self.sold_50_vwma = False
        self.sold_25_200 = False
        self.initial_btc_amount = 0
        self.water_entry_active = False
        self.water_entry_price = None
        self.dropped_below_50 = False
        self.trade_id += 1

    def process_bar(self, idx, row):
        """봉 처리"""
        distance = self.calculate_distance(row)
        close = row['Close']
        high = row['High']
        low = row['Low']
        sma_50 = row['sma_50']
        vwma_100 = row['vwma_100']
        sma_200 = row['sma_200']
        sma_200_15m = row['sma_200_15m']
        sma_200_1h = row['sma_200_1h']
        sma_200_4h = row['sma_200_4h']

        # ========================================
        # STEP 0: 손절 체크 (포지션이 있을 때만)
        # ========================================
        if self.position and self.stop_loss_price:
            if low <= self.stop_loss_price:
                # 손절 발동
                print(f"\n[{row['timestamp']}] 손절 발동!")
                self.close_position(row, self.position['btc_amount'], 'STOP_LOSS', self.stop_loss_price)
                self.base_capital = self.capital  # 기준 자본 리셋
                self.reset_state(keep_flag=False)  # 이격도 -2.0% 다시 찍어야 함
                print(f"   자본: ${self.capital:.2f} | 이격도 -2.0% 대기 상태로 전환")
                return

        # ========================================
        # STEP 1: 포지션 있을 때 - 익절/청산 로직
        # ========================================
        if self.position:
            avg_entry = self.calculate_avg_entry_price()

            # --- 1단계 익절: VWMA(100)에서 50% 익절 ---
            if not self.sold_50_vwma:
                # VWMA가 진입가보다 위에 있고, 가격이 VWMA에 도달
                if vwma_100 > avg_entry and high >= vwma_100:
                    sell_btc = self.initial_btc_amount * 0.50
                    if sell_btc > 0 and sell_btc <= self.position['btc_amount']:
                        print(f"\n[{row['timestamp']}] VWMA(100) 도달! 50% 익절 @ {vwma_100:,.1f}")
                        self.close_position(row, sell_btc, 'TP_50_VWMA', vwma_100)
                        self.sold_50_vwma = True

            # --- 1단계 익절 후 진입가로 돌아오면 본절+0.01% 청산 ---
            if self.sold_50_vwma and not self.sold_25_200 and self.position:
                breakeven_price = avg_entry * (1 + 0.0001)  # 본절+0.01%
                if low <= avg_entry:
                    print(f"\n[{row['timestamp']}] 1단계 익절 후 진입가 복귀, 본절 청산")
                    self.close_position(row, self.position['btc_amount'], 'BREAKEVEN_AFTER_VWMA', breakeven_price)
                    self.base_capital = self.capital
                    self.reset_state()
                    return

            # --- 2단계 익절: 200 SMA에서 25% 익절 ---
            if self.sold_50_vwma and not self.sold_25_200 and self.position:
                if high >= sma_200:
                    sell_btc = self.initial_btc_amount * 0.25
                    if sell_btc > 0 and sell_btc <= self.position['btc_amount']:
                        print(f"\n[{row['timestamp']}] 200 SMA 도달! 25% 익절 @ {sma_200:,.1f}")
                        self.close_position(row, sell_btc, 'TP_25_200SMA', sma_200)
                        self.sold_25_200 = True

            # --- 3단계 익절: MTF 200SMA 중 가장 낮은 곳에서 나머지 전량 익절 ---
            if self.sold_50_vwma and self.sold_25_200 and self.position:
                current_price = close

                # 현재가보다 위에 있는 MTF SMA 중 가장 낮은 것 찾기
                candidates = []
                if sma_200_15m > current_price:
                    candidates.append(('15m', sma_200_15m))
                if sma_200_1h > current_price:
                    candidates.append(('1h', sma_200_1h))
                if sma_200_4h > current_price:
                    candidates.append(('4h', sma_200_4h))

                if candidates:
                    candidates.sort(key=lambda x: x[1])
                    target_price = candidates[0][1]
                    tf_name = candidates[0][0]

                    if high >= target_price:
                        print(f"\n[{row['timestamp']}] {tf_name} 200SMA 도달! 나머지 전량 익절 @ {target_price:,.1f}")
                        self.close_position(row, self.position['btc_amount'], f'TP_FULL_{tf_name.upper()}', target_price)
                        self.base_capital = self.capital
                        self.reset_state()
                        return
                else:
                    # 모든 MTF SMA가 현재가보다 아래 → 즉시 전량 익절
                    print(f"\n[{row['timestamp']}] MTF SMA 모두 현재가 아래, 즉시 전량 익절")
                    self.close_position(row, self.position['btc_amount'], 'TP_FULL_NO_TARGET', close)
                    self.base_capital = self.capital
                    self.reset_state()
                    return

                # 2단계 익절 후 진입가로 돌아오면 본절 청산
                if low <= avg_entry:
                    breakeven_price = avg_entry * (1 + 0.0001)
                    print(f"\n[{row['timestamp']}] 2단계 익절 후 진입가 복귀, 본절 청산")
                    self.close_position(row, self.position['btc_amount'], 'BREAKEVEN_AFTER_200', breakeven_price)
                    self.base_capital = self.capital
                    self.reset_state()
                    return

            # --- 시나리오 2: VWMA 익절 전에 50선 아래로 떨어졌다가 다시 올라오면 물타기 ---
            if self.first_entry_done and not self.sold_50_vwma and not self.second_entry_done:
                # 먼저 50선 아래로 떨어졌는지 체크
                if close < sma_50:
                    self.dropped_below_50 = True

                # 50선 아래로 떨어졌다가 다시 50선 위로 올라왔을 때만 물타기
                if self.dropped_below_50 and close > sma_50:
                    # 두 번째 진입 (90% * 10레버리지)
                    print(f"\n[{row['timestamp']}] 시나리오2: 물타기 진입")
                    self.enter_position(row, idx, SECOND_ENTRY_RATIO, SECOND_ENTRY_LEVERAGE, '2ND_ENTRY')
                    self.second_entry_done = True
                    # 물타기 후 전체 BTC 수량 갱신
                    self.initial_btc_amount = self.position['btc_amount']

                    # 손절가 설정: 100봉 전 최저점
                    self.stop_loss_price = self.get_lookback_low(idx)
                    print(f"   손절가 설정: ${self.stop_loss_price:,.1f}")

            # --- 두 번째 진입 후: 90% 덜어내기 ---
            if self.second_entry_done and not self.partial_sold:
                avg_entry = self.calculate_avg_entry_price()
                take_profit_price = avg_entry * (1 + TAKE_PROFIT_BUFFER)

                if high >= take_profit_price:
                    # 90% 덜어내기
                    sell_btc = self.position['btc_amount'] * 0.9
                    print(f"\n[{row['timestamp']}] 평단+0.01% 도달, 90% 덜어내기")
                    self.close_position(row, sell_btc, 'PARTIAL_90_SELL', take_profit_price)
                    self.partial_sold = True
                    self.water_entry_active = True

            # --- 덜어낸 후 평단가 아래로 하락 → 물타기 반복 ---
            if self.partial_sold and self.water_entry_active and self.position:
                avg_entry = self.calculate_avg_entry_price()

                # 손절가와 평단가 중간 지점
                mid_price = (self.stop_loss_price + avg_entry) / 2

                if low <= mid_price:
                    # 중간 지점에서 물타기 (방금 덜어낸 양 다시 진입)
                    print(f"\n[{row['timestamp']}] 손절가-평단가 중간 물타기")
                    # 90% 물량 다시 진입
                    self.enter_position(row, idx, SECOND_ENTRY_RATIO * 0.9, SECOND_ENTRY_LEVERAGE, 'WATER_ENTRY')
                    self.partial_sold = False  # 다시 덜어내기 가능 상태

            return

        # ========================================
        # STEP 2: 포지션 없을 때 - 진입 조건 체크
        # ========================================

        # --- 이격도 -2.0% 이하 체크 (플래그 ON) ---
        if distance <= DISTANCE_TRIGGER:
            if not self.flag_triggered:
                self.flag_triggered = True
                self.min_distance = distance
                print(f"\n[{row['timestamp']}] 이격도 {distance:.2f}% <= -2.0% | 플래그 ON")
            else:
                # 최저점 추적
                if distance < self.min_distance:
                    self.min_distance = distance

        # --- 이격도 회복 체크 (진입 준비) ---
        if self.flag_triggered and distance >= DISTANCE_READY:
            if not self.ready_to_enter:
                self.ready_to_enter = True
                print(f"[{row['timestamp']}] 이격도 {distance:.2f}% >= -1.5% | 진입 준비 완료")

        # --- 진입 조건: 이격도 -1.5% 이하 AND 50SMA 위 마감 AND 1시간봉 RSI <= 30 ---
        rsi_1h = row['rsi_14_1h']
        if self.ready_to_enter and distance <= 0 and close > sma_50 and rsi_1h <= 30:
            print(f"\n[{row['timestamp']}] 진입 조건 충족!")
            print(f"   이격도: {distance:.2f}% | Close: {close:,.1f} > SMA50: {sma_50:,.1f} | RSI(1h): {rsi_1h:.1f}")

            # 첫 진입 (10% * 5레버리지)
            self.enter_position(row, idx, FIRST_ENTRY_RATIO, FIRST_ENTRY_LEVERAGE, '1ST_ENTRY')
            self.first_entry_done = True
            # 최초 BTC 수량 저장 (익절 비율 계산용)
            self.initial_btc_amount = self.position['btc_amount']

    def run(self):
        """백테스트 실행"""
        print("=" * 80)
        print("MA Distance 전략 백테스트 시작")
        print("=" * 80)
        print(f"초기 자본: ${INITIAL_CAPITAL:,.2f}")
        print(f"이격도 트리거: {DISTANCE_TRIGGER}% | 진입 준비: {DISTANCE_READY}%")
        print(f"첫 진입: {FIRST_ENTRY_RATIO*100}% × {FIRST_ENTRY_LEVERAGE}x")
        print(f"물타기: {SECOND_ENTRY_RATIO*100}% × {SECOND_ENTRY_LEVERAGE}x")
        print("=" * 80)

        for idx, row in self.df.iterrows():
            self.process_bar(idx, row)

        # 미청산 포지션 처리
        if self.position:
            print(f"\n[종료] 미청산 포지션 청산")
            last_row = self.df.iloc[-1]
            self.close_position(last_row, self.position['btc_amount'], 'END_OF_DATA')

        self.print_results()
        self.save_trades()

    def print_results(self):
        """결과 출력"""
        print("\n" + "=" * 80)
        print("백테스트 결과")
        print("=" * 80)

        # 거래 통계
        if not self.trades:
            print("거래 없음")
            return

        trades_df = pd.DataFrame(self.trades)
        exits = trades_df[trades_df['action'] == 'EXIT']

        total_trades = len(exits)
        winning_trades = len(exits[exits['pnl'] > 0])
        losing_trades = len(exits[exits['pnl'] < 0])

        total_pnl = exits['pnl'].sum()
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        print(f"최종 자본: ${self.capital:,.2f}")
        print(f"총 수익: ${total_pnl:,.2f} ({(self.capital/INITIAL_CAPITAL-1)*100:+.2f}%)")
        print(f"\n거래 통계:")
        print(f"   총 청산 횟수: {total_trades}")
        print(f"   승리: {winning_trades} | 패배: {losing_trades}")
        print(f"   승률: {win_rate:.1f}%")

        if winning_trades > 0:
            avg_win = exits[exits['pnl'] > 0]['pnl'].mean()
            print(f"   평균 이익: ${avg_win:.2f}")
        if losing_trades > 0:
            avg_loss = exits[exits['pnl'] < 0]['pnl'].mean()
            print(f"   평균 손실: ${avg_loss:.2f}")

    def save_trades(self):
        """거래 기록 저장"""
        if self.trades:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(OUTPUT_TRADES, index=False)
            print(f"\n거래 기록 저장: {OUTPUT_TRADES}")


# ================================================================================
# 메인
# ================================================================================

def main():
    # 데이터 로드
    print(f"데이터 로드: {INPUT_FILE}")
    df = pd.read_csv(INPUT_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 기간 필터링
    df = df[(df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)]
    df = df.reset_index(drop=True)

    print(f"   기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print(f"   데이터 수: {len(df):,} rows")

    # 이격도 계산 및 통계
    df['ma_distance'] = (df['sma_50'] - df['sma_200']) / df['sma_200'] * 100
    print(f"\n이격도 통계:")
    print(f"   최소: {df['ma_distance'].min():.2f}%")
    print(f"   최대: {df['ma_distance'].max():.2f}%")
    print(f"   평균: {df['ma_distance'].mean():.2f}%")
    print(f"   -2.0% 이하 횟수: {(df['ma_distance'] <= -2.0).sum()}")

    # 백테스트 실행
    backtester = MADistanceBacktester(df)
    backtester.run()


if __name__ == "__main__":
    main()

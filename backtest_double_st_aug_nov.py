"""
Double SuperTrend Strategy Backtest - 설정 가능한 기간
수수료 0.0275%, 리스크 3%, 손절/익절 동적 설정

실행:
    python backtest_double_st_aug_nov.py
"""

import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 기존 백테스터 클래스 import
from backtest_double_st import DoubleSTBacktester

# ================================================================================
# CONFIG: 모든 설정 값 (자유롭게 수정 가능)
# ================================================================================

# 데이터 파일 설정
DATA_FILE = 'backtest_data_2025/BTCUSDT_double_st_2025_01_01.csv'  # 데이터 파일 경로
PREPARE_SCRIPT = 'prepare_backtest_data.py'  # 데이터 준비 스크립트 이름

# 백테스트 기간 설정
START_DATE = '2020-03-01'  # 백테스트 시작 날짜
END_DATE = '2025-11-05'    # 백테스트 종료 날짜

# 백테스터 파라미터
INITIAL_CAPITAL = 1000      # 초기 자본 (USDT)
RISK_PER_TRADE = 0.01       # 거래당 리스크 (3%)
FEE_RATE = 0.000275         # 수수료율 (0.0275%)

# 출력 파일 설정
OUTPUT_CSV = 'backtest_results_2025.csv'  # 결과 저장 파일명

# 출력 메시지 설정
TITLE_MESSAGE = 'Double SuperTrend Strategy - 백테스트'  # 제목
SECTION_DIVIDER = '=' * 80  # 구분선

# ================================================================================


def main():
    """백테스트 실행"""
    print("\n" + SECTION_DIVIDER)
    print(f"🚀 {TITLE_MESSAGE}")
    print(f"   기간: {START_DATE} ~ {END_DATE}")
    print(SECTION_DIVIDER)

    # 데이터 파일 경로
    data_file = DATA_FILE

    try:
        print(f"\n📂 데이터 로드: {data_file}")
        df = pd.read_csv(data_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    except FileNotFoundError:
        print(f"❌ 파일을 찾을 수 없습니다: {data_file}")
        print(f"먼저 {PREPARE_SCRIPT}를 실행하세요.")
        return

    # 데이터 필터링
    start_date = START_DATE
    end_date = END_DATE

    test_df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)].copy()
    test_df = test_df.reset_index(drop=True)

    if len(test_df) == 0:
        print(f"❌ 해당 기간 데이터가 없습니다: {start_date} ~ {end_date}")
        return

    print(f"📅 백테스트 기간: {test_df['timestamp'].min()} ~ {test_df['timestamp'].max()}")
    print(f"📊 데이터 크기: {len(test_df):,} 행")

    # 백테스터 초기화
    backtester = DoubleSTBacktester(
        initial_capital=INITIAL_CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        fee_rate=FEE_RATE
    )

    # 백테스트 실행
    results = backtester.run_backtest(test_df)

    # 추가 분석
    if results is not None and len(results) > 0:
        print("\n" + "="*80)
        print("📊 추가 분석")
        print("="*80)

        # 월별 수익률 계산
        results['entry_month'] = pd.to_datetime(results['entry_time']).dt.to_period('M')
        monthly_pnl = results.groupby('entry_month')['net_pnl'].sum()

        print("\n📅 월별 손익:")
        for month, pnl in monthly_pnl.items():
            print(f"  {month}: ${pnl:,.2f}")

        # 방향별 통계
        long_trades = results[results['direction'] == 'LONG']
        short_trades = results[results['direction'] == 'SHORT']

        print(f"\n📈 방향별 통계:")
        print(f"  롱 거래: {len(long_trades)} ({len(long_trades)/len(results)*100:.1f}%)")
        print(f"  숏 거래: {len(short_trades)} ({len(short_trades)/len(results)*100:.1f}%)")

        if len(long_trades) > 0:
            long_win_rate = len(long_trades[long_trades['net_pnl'] > 0]) / len(long_trades) * 100
            print(f"  롱 승률: {long_win_rate:.2f}%")

        if len(short_trades) > 0:
            short_win_rate = len(short_trades[short_trades['net_pnl'] > 0]) / len(short_trades) * 100
            print(f"  숏 승률: {short_win_rate:.2f}%")

        # 최대 연속 승/패
        results['is_win'] = results['net_pnl'] > 0
        win_streak = 0
        loss_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        current_streak = 0
        current_is_win = None

        for is_win in results['is_win']:
            if current_is_win is None or is_win != current_is_win:
                if current_is_win is True:
                    max_win_streak = max(max_win_streak, current_streak)
                elif current_is_win is False:
                    max_loss_streak = max(max_loss_streak, current_streak)
                current_streak = 1
                current_is_win = is_win
            else:
                current_streak += 1

        # 마지막 streak 체크
        if current_is_win is True:
            max_win_streak = max(max_win_streak, current_streak)
        elif current_is_win is False:
            max_loss_streak = max(max_loss_streak, current_streak)

        print(f"\n🔥 연속 거래:")
        print(f"  최대 연속 승리: {max_win_streak}")
        print(f"  최대 연속 패배: {max_loss_streak}")

        # CSV 파일 저장
        results.to_csv(OUTPUT_CSV, index=False)
        print(f"\n💾 상세 거래 내역 저장: {OUTPUT_CSV}")

    print("\n✅ 백테스트 완료!")


if __name__ == "__main__":
    main()
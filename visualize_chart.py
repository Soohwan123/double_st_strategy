"""
RB Strategy 차트 시각화 스크립트

캔들 차트, 볼린저 밴드, 진입 신호를 시각화합니다.

사용법:
    python visualize_chart.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import numpy as np

# ================================================================================
# CONFIG
# ================================================================================

DATA_FILE = 'backtest_data/BTCUSDT_rb_strategy.csv'

# 시각화할 기간 (최근 N개 봉)
NUM_BARS = 200

# 특정 날짜 범위로 시각화 (None이면 최근 NUM_BARS 사용)
START_DATE = '2024-01-04 10:00'
END_DATE = '2024-01-05 00:00'

# 차트 크기
FIG_WIDTH = 20
FIG_HEIGHT = 10


# ================================================================================
# 차트 그리기 함수
# ================================================================================

def draw_candlestick(ax, df):
    """캔들스틱 차트 그리기"""
    width = 0.6  # 캔들 폭
    width2 = 0.1  # 심지 폭

    up = df[df['Close'] >= df['Open']]
    down = df[df['Close'] < df['Open']]

    # 상승 캔들 (녹색)
    ax.bar(up.index, up['Close'] - up['Open'], width, bottom=up['Open'], color='green', alpha=0.8)
    ax.bar(up.index, up['High'] - up['Close'], width2, bottom=up['Close'], color='green', alpha=0.8)
    ax.bar(up.index, up['Low'] - up['Open'], width2, bottom=up['Open'], color='green', alpha=0.8)

    # 하락 캔들 (빨간색)
    ax.bar(down.index, down['Close'] - down['Open'], width, bottom=down['Open'], color='red', alpha=0.8)
    ax.bar(down.index, down['High'] - down['Open'], width2, bottom=down['Open'], color='red', alpha=0.8)
    ax.bar(down.index, down['Low'] - down['Close'], width2, bottom=down['Close'], color='red', alpha=0.8)


def draw_bollinger_bands(ax, df):
    """볼린저 밴드 그리기"""
    ax.plot(df.index, df['bb_basis'], color='orange', linewidth=1, label='BB Basis (200)')
    ax.plot(df.index, df['bb_upper'], color='blue', linewidth=1, linestyle='--', label='BB Upper')
    ax.plot(df.index, df['bb_lower'], color='blue', linewidth=1, linestyle='--', label='BB Lower')
    ax.fill_between(df.index, df['bb_upper'], df['bb_lower'], alpha=0.1, color='blue')


def draw_signals(ax, df):
    """진입 신호 그리기"""
    # LONG 신호 (녹색 삼각형)
    long_signals = df[df['long_signal'] == True]
    if len(long_signals) > 0:
        ax.scatter(long_signals.index, long_signals['Low'] * 0.999,
                   marker='^', color='lime', s=200, label=f'LONG Signal ({len(long_signals)})', zorder=5)

    # SHORT 신호 (빨간색 삼각형)
    short_signals = df[df['short_signal'] == True]
    if len(short_signals) > 0:
        ax.scatter(short_signals.index, short_signals['High'] * 1.001,
                   marker='v', color='magenta', s=200, label=f'SHORT Signal ({len(short_signals)})', zorder=5)


def draw_rsi(ax, df):
    """RSI 그리기"""
    ax.plot(df.index, df['rsi'], color='purple', linewidth=1, label='RSI(6)')
    ax.axhline(y=50, color='gray', linestyle='--', linewidth=0.5)
    ax.axhline(y=70, color='red', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.axhline(y=30, color='green', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.fill_between(df.index, 30, 70, alpha=0.1, color='gray')
    ax.set_ylim(0, 100)
    ax.set_ylabel('RSI')
    ax.legend(loc='upper left')


def main():
    """메인 함수"""
    print("📊 차트 시각화 시작...")

    # 데이터 로드
    df = pd.read_csv(DATA_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp')

    print(f"   데이터 로드 완료: {len(df):,} rows")
    print(f"   기간: {df.index.min()} ~ {df.index.max()}")

    # 기간 필터링
    if START_DATE and END_DATE:
        df = df[(df.index >= START_DATE) & (df.index <= END_DATE)]
        print(f"   필터링 후: {len(df):,} rows")
    else:
        # 최근 NUM_BARS만 사용
        df = df.tail(NUM_BARS)
        print(f"   최근 {NUM_BARS}개 봉 사용")

    # 인덱스 리셋 (x축을 숫자로)
    df = df.reset_index()

    # 신호 통계
    long_count = df['long_signal'].sum()
    short_count = df['short_signal'].sum()
    print(f"   LONG 신호: {long_count}개")
    print(f"   SHORT 신호: {short_count}개")

    # Figure 생성 (2개 subplot: 가격 + RSI)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(FIG_WIDTH, FIG_HEIGHT),
                                    gridspec_kw={'height_ratios': [3, 1]}, sharex=True)

    # 캔들스틱 차트
    draw_candlestick(ax1, df)

    # 볼린저 밴드
    draw_bollinger_bands(ax1, df)

    # 진입 신호
    draw_signals(ax1, df)

    # 가격 차트 설정
    ax1.set_ylabel('Price')
    ax1.set_title(f'RB Strategy - BB(200,2) + RSI(6)\n{df["timestamp"].iloc[0]} ~ {df["timestamp"].iloc[-1]}')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # RSI 차트
    draw_rsi(ax2, df)
    ax2.grid(True, alpha=0.3)

    # x축 라벨 (시간)
    # 10개 간격으로 라벨 표시
    step = max(1, len(df) // 10)
    ax2.set_xticks(df.index[::step])
    ax2.set_xticklabels([t.strftime('%m-%d %H:%M') for t in df['timestamp'].iloc[::step]], rotation=45)
    ax2.set_xlabel('Time')

    plt.tight_layout()

    # 저장
    output_file = 'rb_strategy_chart.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✅ 차트 저장: {output_file}")

    # 화면 표시
    plt.show()


if __name__ == "__main__":
    main()

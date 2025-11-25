"""
Rolling Window BB 계산 정확도 검증

전체 데이터셋 vs 200개 Rolling Window 비교
"""

import pandas as pd
import numpy as np

# 테스트용 간단한 데이터 생성
np.random.seed(42)
prices = 100 + np.cumsum(np.random.randn(1000) * 0.5)

df_full = pd.DataFrame({'Close': prices})

# BB 계산 함수
def calculate_bb(close_series, length=20, std_dev=2):
    sma = close_series.rolling(window=length).mean()
    std = close_series.rolling(window=length).std(ddof=0)
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    return sma, upper, lower

# 1. 전체 데이터로 계산
sma_full, upper_full, lower_full = calculate_bb(df_full['Close'])

print("=" * 80)
print("Rolling Window BB 계산 정확도 검증")
print("=" * 80)

# 2. 마지막 200개만 잘라서 계산 (라이브 매매 시뮬레이션)
df_window = df_full.tail(200).reset_index(drop=True)
sma_window, upper_window, lower_window = calculate_bb(df_window['Close'])

# 3. 비교 (마지막 180~200번째, BB(20)이 계산된 구간)
print("\n📊 비교 대상:")
print(f"   전체 데이터: {len(df_full)} 봉")
print(f"   Rolling Window: {len(df_window)} 봉")
print(f"   비교 구간: Window의 마지막 20개 (180~200번째)")

print("\n✅ 결과 비교 (마지막 5개 봉):")
print("-" * 80)
print(f"{'Index':<8} {'Full SMA':<15} {'Window SMA':<15} {'차이':<15}")
print("-" * 80)

for i in range(5):
    idx_full = len(df_full) - 5 + i
    idx_window = len(df_window) - 5 + i

    sma_f = sma_full.iloc[idx_full]
    sma_w = sma_window.iloc[idx_window]
    diff = abs(sma_f - sma_w)

    print(f"{idx_full:<8} {sma_f:<15.8f} {sma_w:<15.8f} {diff:<15.10f}")

print("\n📈 Upper Band 비교:")
print("-" * 80)
for i in range(5):
    idx_full = len(df_full) - 5 + i
    idx_window = len(df_window) - 5 + i

    upper_f = upper_full.iloc[idx_full]
    upper_w = upper_window.iloc[idx_window]
    diff = abs(upper_f - upper_w)

    print(f"{idx_full:<8} {upper_f:<15.8f} {upper_w:<15.8f} {diff:<15.10f}")

print("\n📉 Lower Band 비교:")
print("-" * 80)
for i in range(5):
    idx_full = len(df_full) - 5 + i
    idx_window = len(df_window) - 5 + i

    lower_f = lower_full.iloc[idx_full]
    lower_w = lower_window.iloc[idx_window]
    diff = abs(lower_f - lower_w)

    print(f"{idx_full:<8} {lower_f:<15.8f} {lower_w:<15.8f} {diff:<15.10f}")

# 최대 오차 확인
max_diff_sma = max([abs(sma_full.iloc[len(df_full) - 5 + i] -
                         sma_window.iloc[len(df_window) - 5 + i])
                    for i in range(5)])

print("\n" + "=" * 80)
print("🎯 결론:")
print("=" * 80)
print(f"최대 오차: {max_diff_sma:.15f}")
if max_diff_sma < 1e-10:
    print("✅ 완전히 동일함 (부동소수점 오차 범위 내)")
else:
    print("⚠️ 차이가 있음")

print("\n💡 해석:")
print("   - pandas의 rolling() 함수는 항상 최근 N개 데이터만 사용")
print("   - 따라서 전체 데이터든 rolling window든 결과는 동일")
print("   - 라이브 매매 시 200-300개 봉 유지로 충분")
print(f"   - BB(20,2) 최소 필요: 20개 → 200개면 10배 여유")
print(f"   - BB(4,4) 최소 필요: 4개 → 200개면 50배 여유")

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# CSV 로드
df_v2 = pd.read_csv('trades_hyper_scalper_v2.csv', parse_dates=['entry_time', 'exit_time'])
df_usdc = pd.read_csv('trades_hyper_scalper_v2_usdc_incremental.csv', parse_dates=['entry_time', 'exit_time'])

fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=False)

# --- V2 (USDT) ---
ax1 = axes[0]
ax1.plot(df_v2['exit_time'], df_v2['balance'], color='#2196F3', linewidth=1.2)
ax1.set_title('Hyper Scalper V2 (BTCUSDT) - Equity Curve', fontsize=14, fontweight='bold')
ax1.set_ylabel('Balance (USDT)', fontsize=12)
ax1.axhline(y=df_v2['balance'].iloc[0], color='gray', linestyle='--', alpha=0.5, label=f'Start: {df_v2["balance"].iloc[0]:,.0f}')
ax1.text(df_v2['exit_time'].iloc[-1], df_v2['balance'].iloc[-1],
         f'  {df_v2["balance"].iloc[-1]:,.0f}', va='center', fontsize=9, color='#2196F3')
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

# --- V2 USDC Incremental ---
ax2 = axes[1]
ax2.plot(df_usdc['exit_time'], df_usdc['balance'], color='#4CAF50', linewidth=1.2)
ax2.set_title('Hyper Scalper V2 USDC (Incremental) - Equity Curve', fontsize=14, fontweight='bold')
ax2.set_ylabel('Balance (USDC)', fontsize=12)
ax2.axhline(y=df_usdc['balance'].iloc[0], color='gray', linestyle='--', alpha=0.5, label=f'Start: {df_usdc["balance"].iloc[0]:,.0f}')
ax2.text(df_usdc['exit_time'].iloc[-1], df_usdc['balance'].iloc[-1],
         f'  {df_usdc["balance"].iloc[-1]:,.0f}', va='center', fontsize=9, color='#4CAF50')
ax2.legend(loc='upper left')
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

plt.tight_layout()
plt.savefig('equity_curve.png', dpi=150, bbox_inches='tight')
print('Saved: equity_curve.png')
plt.show()

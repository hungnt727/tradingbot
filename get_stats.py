import pandas as pd
df = pd.read_csv('output/simple_backtest_top300_15m.csv')
print(f"Total Trades: {len(df)}")
wins = (df['pnl_pct'] > 0).sum()
print(f"Win Rate: {wins/len(df)*100:.1f}% ({wins}W / {len(df)-wins}L)")
print(f"Total PnL: {df['pnl_pct'].sum()*100:.2f}%")
print("Exit Reasons:")
print(df['exit_reason'].value_counts())

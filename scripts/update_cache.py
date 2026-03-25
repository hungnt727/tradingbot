import ccxt
import json
import os
try:
    ex = ccxt.bybit()
    tickers = ex.fetch_tickers()
    # Filter for USDT pairs and sort by quote volume
    valid_tickers = {k: v for k, v in tickers.items() if '/USDT' in k and v.get('quoteVolume')}
    sorted_tickers = sorted(valid_tickers.items(), key=lambda x: float(x[1]['quoteVolume']), reverse=True)
    top_300 = [m.split(':')[0] for m, _ in sorted_tickers][:300]
    
    os.makedirs('data', exist_ok=True)
    with open('data/top_300_cache.json', 'w') as f:
        json.dump(top_300, f, indent=2)
    print(f'Successfully cached {len(top_300)} symbols.')
except Exception as e:
    print(f'Error: {e}')

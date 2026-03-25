from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    res = conn.execute(text("SELECT symbol, count(1) as cnt FROM ohlcv WHERE timeframe='1h' GROUP BY symbol ORDER BY cnt DESC LIMIT 10"))
    for row in res:
        print(f"{row[0]}: {row[1]} candles")

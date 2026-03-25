from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

def check():
    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        res = conn.execute(text("SELECT symbol, timeframe, count(*) FROM ohlcv GROUP BY symbol, timeframe"))
        rows = res.all()
        if not rows:
            print("No data in ohlcv table.")
        for row in rows:
            print(f"Symbol: {row[0]}, Timeframe: {row[1]}, Count: {row[2]}")

if __name__ == "__main__":
    check()

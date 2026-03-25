from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.begin() as conn:
    conn.execute(text('TRUNCATE TABLE ohlcv'))
print("Table truncated.")

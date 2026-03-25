import os
import requests
import pandas as pd
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
import sys

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.storage.timescale_client import TimescaleClient
from data.crawler.bybit_crawler import BybitCrawler

load_dotenv()

def get_top_coins(limit=300):
    cmc_key = os.getenv("CMC_API_KEY")
    if not cmc_key:
        logger.warning("CMC_API_KEY không có. Chỉ dùng BTC, ETH, SOL.")
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': cmc_key}
    try:
        response = requests.get(url, headers=headers, params={'limit': limit})
        data = response.json()
        return [f"{d['symbol']}/USDT" for d in data['data']]
    except Exception as e:
        logger.error(f"Lỗi CMC: {e}")
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

def backfill():
    db_url = os.getenv("DATABASE_URL")
    db = TimescaleClient(db_url)
    crawler = BybitCrawler()
    
    symbols = get_top_coins(300)
    logger.info(f"Bắt đầu kiểm tra và backfill 15m cho {len(symbols)} coin...")

    from sqlalchemy import create_engine, text
    engine = create_engine(db_url)
    
    for symbol in symbols:
        try:
            # Check current count for 15m
            with engine.connect() as conn:
                res = conn.execute(text("SELECT count(*) FROM ohlcv WHERE symbol=:s AND timeframe='15m'"), {"s": symbol}).scalar()
            
            if res >= 900:
                # logger.info(f"[{symbol}] Đã đủ dữ liệu ({res} nến).")
                continue
                
            logger.info(f"[{symbol}] Thiếu dữ liệu (hiện có {res}). Đang tải 1000 nến 15m...")
            df = crawler.fetch_latest_candles(symbol, "15m", limit=1000)
            if df.empty:
                logger.warning(f"[{symbol}] Không lấy được dữ liệu nến.")
                continue
                
            records = crawler.df_to_records(df)
            db.upsert_ohlcv(records)
            logger.success(f"[{symbol}] Đã nạp 1000 nến.")
        except Exception as e:
            logger.error(f"Lỗi [{symbol}]: {e}")

if __name__ == "__main__":
    backfill()

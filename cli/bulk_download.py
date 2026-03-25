"""
Script hỗ trợ tải dữ liệu OHLCV hàng loạt cho Top N Coins
Giúp chuẩn bị dữ liệu cho quá trình Backtest đa khung thời gian.
"""
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from loguru import logger
from data.storage.timescale_client import TimescaleClient
from data.crawler.bybit_crawler import BybitCrawler
from cli.run_distribution_signal_bot import get_top_coins
from dotenv import load_dotenv

load_dotenv()

@click.command()
@click.option("--top", type=int, default=50, help="Số lượng Top coin cần tải.")
@click.option("--days", type=int, default=180, help="Lịch sử bao nhiêu ngày? (Mặc định 180 ngày ~ 6 tháng)")
@click.option("--timeframes", type=str, default="1d,1h", help="Các khung thời gian cần tải, cách nhau bởi dấu phẩy")
def main(top, days, timeframes):
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tradingbot")
    db = TimescaleClient(database_url)
    db.init_db()
    
    crawler = BybitCrawler(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", "")
    )
    
    logger.info(f"Đang lấy danh sách Top {top} coins...")
    top_symbols = get_top_coins(limit=top)
    logger.info(f"Tìm thấy: {len(top_symbols)} symbols (Ví dụ: {top_symbols[:3]}...)")
    
    tf_list = timeframes.split(',')
    start_date = datetime.utcnow() - timedelta(days=days)
    
    for i, symbol_base in enumerate(top_symbols):
        symbol = f"{symbol_base}/USDT:USDT"
        logger.info(f"[{i+1}/{len(top_symbols)}] Đang xử lý {symbol}...")
        
        for tf in tf_list:
            tf = tf.strip()
            try:
                # Tải khối lượng data
                df = crawler.fetch_ohlcv_historical(symbol, tf, since=start_date)
                if df.empty:
                    # Rất nhiều coin bị Bybit crawler từ chối format này, thử format trơn
                    df = crawler.fetch_ohlcv_historical(f"{symbol_base}USDT", tf, since=start_date)
                
                if not df.empty:
                    records = crawler.df_to_records(df)
                    # Mapping standard symbol format để ghi vào DB
                    for r in records:
                        r['symbol'] = symbol_base  # Lưu gọn "BTC", "ETH" vào DB
                        
                    count = db.upsert_ohlcv(records)
                    logger.success(f"  -> Lưu thành công {count} nến {tf} cho {symbol_base}.")
                else:
                    logger.warning(f"  -> Bỏ qua {symbol_base} {tf}: Không có dữ liệu.")
                    
            except Exception as e:
                logger.error(f"  -> Lỗi khi tải {symbol_base} {tf}: {e}")
                
            time.sleep(0.2) # Chống bị ban API rates

    logger.info("🎉 HOÀN TẤT TẢI DỮ LIỆU BULK!")

if __name__ == "__main__":
    main()

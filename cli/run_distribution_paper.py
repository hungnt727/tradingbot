"""
Distribution Strategy Paper Trading - Chạy paper trading cho chiến lược phân phối đỉnh.
"""
import os
import sys
import json
import requests
import pandas as pd
import sys
import select

# Platform-specific keyboard input
if os.name == 'nt':
    import msvcrt
import time
import argparse
from datetime import datetime, timedelta
from loguru import logger
from dotenv import load_dotenv

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.crawler.scheduler import DataScheduler
from data.crawler.bybit_crawler import BybitCrawler
from paper_trading.engine import PaperTradingEngine
from strategies.distribution_strategy import DistributionStrategy
from utils.telegram_bot import TelegramBot
from cli.run_paper_top_300 import (
    get_top_coins, 
    filter_bybit_symbols,
    parse_timeframe_to_minutes,
    send_hourly_report as send_hourly_report_generic
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'top_300_cache.json')


def send_distribution_report(portfolio, bot):
    """Job to send hourly summary to Telegram for Distribution Strategy."""
    try:
        stats = portfolio.get_hourly_stats()
        
        # Tổng kết toàn bộ
        all = stats['all']
        all_winrate = (all['wins'] / all['total'] * 100) if all['total'] > 0 else 0
        all_msg = (
            f"📊 <b>DISTRIBUTION STRATEGY - TỔNG KẾT</b>\n"
            f"Lệnh: {all['total']} | Win: {all['wins']} | Loss: {all['losses']} | WR: {all_winrate:.1f}%\n"
            f"PnL: {all['pnl_usd']:+.2f}$ ({all['pnl_pct']:+.2f}%)\n"
            f"TP1: {all['tp1_count']} | TP2: {all['tp2_count']} | SL: {all['sl_count']} | Timeout: {all['timeout_count']}"
        )
        
        # Kết quả 1 giờ qua
        hourly = stats['hourly']
        hourly_winrate = (hourly['wins'] / hourly['total'] * 100) if hourly['total'] > 0 else 0
        hourly_msg = (
            f"⏰ <b>1 GIỜ QUA</b>\n"
            f"Lệnh: {hourly['total']} | Win: {hourly['wins']} | Loss: {hourly['losses']} | WR: {hourly_winrate:.1f}%\n"
            f"PnL: {hourly['pnl_usd']:+.2f}$ ({hourly['pnl_pct']:+.2f}%)"
        )
        
        # Lệnh đang mở
        open_msg = f"🔓 <b>ĐANG MỞ</b>: {stats['open_count']} lệnh"
        
        # Distribution-specific stats
        dist_msg = ""
        if hasattr(portfolio, 'get_distribution_stats'):
            dist_stats = portfolio.get_distribution_stats()
            if dist_stats:
                dist_msg = (
                    f"\n📈 <b>DISTRIBUTION STATS</b>\n"
                    f"Avg Range Position: {dist_stats.get('avg_range_position', 0):.2f}\n"
                    f"Avg Distribution Score: {dist_stats.get('avg_score', 0):.1f}"
                )
        
        # Gửi tin nhắn
        bot.send_message(f"{all_msg}\n\n{hourly_msg}\n\n{open_msg}{dist_msg}")
        
    except Exception as e:
        logger.error(f"Reporting job failed: {e}")


def db_clear_data(symbols, timeframe="1d"):
    """Delete existing data and OPEN trades for symbols to ensure clean state."""
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL)
    logger.info(f"Đã xóa dữ liệu {timeframe} và lệnh OPEN cho {len(symbols)} coin...")
    with engine.begin() as conn:
        # Clear trades
        logger.info("Xóa toàn bộ lịch sử lệnh (TOTAL RESET)...")
        conn.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
        
        # Clear OHLCV for relevant symbols
        conn.execute(
            text("DELETE FROM ohlcv WHERE timeframe = :tf AND symbol IN :symbols"),
            {"tf": timeframe, "symbols": tuple(symbols)}
        )
    logger.success("Đã dọn dẹp Database.")


def perform_initial_backfill(crawler, db, symbols, timeframe="1d"):
    """Fetch candles for each symbol before starting the live loop."""
    logger.info(f"Bắt đầu Backfill 100 nen {timeframe} cho {len(symbols)} coin...")
    count = 0
    for symbol in symbols:
        try:
            df = crawler.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
            if not df.empty:
                records = crawler.df_to_records(df)
                db.upsert_ohlcv(records)
                count += 1
                if count % 50 == 0:
                    logger.info(f"Đã backfill {count}/{len(symbols)} coin...")
        except Exception as e:
            logger.error(f"Lỗi backfill {symbol}: {e}")
    logger.success(f"Hoàn tất Backfill cho {count} coin.")


def main():
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set in .env")
        return

    # 1. Initialize Components
    parser = argparse.ArgumentParser(description="Distribution Strategy Paper Trading")
    parser.add_argument("--top", type=int, default=300, help="Số lượng top coin muốn chạy (mặc định 300)")
    parser.add_argument("--timeframe", type=str, default="1d", help="Khung thời gian giao dịch (mặc định 1d)")
    args = parser.parse_args()

    strategy = DistributionStrategy()
    
    # Override timeframe if specified
    if args.timeframe:
        strategy.timeframe = args.timeframe
        logger.info(f"Đã đặt TimeFrame: {strategy.timeframe}, HTF: {strategy.htf_timeframe}")

    bot = TelegramBot()
    scheduler = DataScheduler(DATABASE_URL)
    
    # Register Bybit Crawler
    crawler = BybitCrawler(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    scheduler.add_exchange(crawler)
    
    # 2. Get Symbols & Setup Data
    logger.info(f"Đang lấy Top {args.top} Coins...")
    all_symbols = get_top_coins(limit=args.top)

    # Filter by Bybit Support
    symbols = filter_bybit_symbols(crawler, all_symbols)

    # Cleanup and Backfill before starting scheduler
    scheduler.db.init_db()
    db_clear_data(symbols, args.timeframe)
    bot.send_message(
        f"🧹 <b>Distribution Strategy đã reset.</b>\n"
        f"Đang chuẩn bị backfill dữ liệu cho {len(symbols)} coin ({strategy.timeframe})..."
    )
    perform_initial_backfill(crawler, scheduler.db, symbols, args.timeframe)
    
    # Immediate Signal Scan
    logger.info(f"🔍 Đang thực hiện kiểm tra tín hiệu cho {len(symbols)} coin ({strategy.timeframe})...")
    engine = PaperTradingEngine(DATABASE_URL, strategy, symbols, exchange="bybit")
    try:
        engine._run_cycle()
    except Exception as e:
        logger.error(f"Lỗi khi quét tín hiệu ban đầu: {e}")
    
    # Report Initial Signal Summary
    from sqlalchemy import text
    with scheduler.db.engine.connect() as conn:
        long_c = conn.execute(text("SELECT count(*) FROM trades WHERE side = 'LONG'")).scalar()
        short_c = conn.execute(text("SELECT count(*) FROM trades WHERE side = 'SHORT'")).scalar()
    
    bot.send_message(
        f"✅ <b>Hoàn tất quét tín hiệu Distribution!</b>\n"
        f"- 🟢 Long: {long_c}\n"
        f"- 🔴 Short: {short_c}\n"
        f"🚀 Đã mở lệnh cho {long_c + short_c} cặp tiềm năng.\n"
        f"📊 Chiến lược: Distribution Phase Detection ({strategy.timeframe})"
    )
    logger.success(f"Hoàn tất quét tín hiệu ban đầu: {long_c} Long, {short_c} Short.")

    # 3. Setup Scheduler Jobs
    for sym in symbols:
        try:
            scheduler.add_job("bybit", sym, strategy.timeframe)
        except:
            continue
    
    # Paper Trading Job (Every 1 minute)
    cooldown = parse_timeframe_to_minutes(args.timeframe)
    engine = PaperTradingEngine(
        DATABASE_URL, 
        strategy, 
        symbols, 
        exchange="bybit", 
        sleep_seconds=0, 
        cooldown_minutes=cooldown
    )
    scheduler.add_custom_job(
        func=engine._run_cycle,
        cron_kwargs={"minute": "*"},
        job_id="distribution_paper_trading",
        name="Distribution Paper Trading Loop"
    )
    
    # Hourly Report Job
    scheduler.add_custom_job(
        func=lambda: send_distribution_report(engine.portfolio, bot),
        cron_kwargs={"minute": "0"},
        job_id="hourly_telegram_report",
        name="Telegram Hourly Summary"
    )
    
    # 4. Start
    bot.send_message(
        f"🚀 <b>Distribution Strategy ({strategy.timeframe}) đã khởi động!</b>\n"
        f"Đã lọc & backfill {len(symbols)} Coin hỗ trợ trên Bybit.\n"
        f"Chiến lược: Phát hiện giai đoạn phân phối đỉnh\n"
        f"Báo cáo mỗi 1h."
    )
    scheduler.start()
    
    print("\n" + "="*60)
    print(f"DISTRIBUTION BOT ĐANG CHẠY TRÊN {len(symbols)} COIN ({strategy.timeframe})")
    print(f">> Nhấn phim 'q' để DỪNG bot một cách an toàn.")
    print("="*60 + "\n")
    
    try:
        while True:
            if sys.platform == 'win32':
                if msvcrt.kbhit():
                    key = msvcrt.getch().lower()
                    if key == b'q':
                        logger.warning("Phím 'q' được nhấn. Đang dừng bot...")
                        break
            else:
                # Linux/Unix - use select for non-blocking input
                if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                    key = sys.stdin.read(1)
                    if key.lower() == 'q':
                        logger.warning("Phím 'q' được nhấn. Đang dừng bot...")
                        break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.warning("Nhận tín hiệu Ctrl+C. Đang dừng bot...")
    
    scheduler.stop()
    print("\n✅ Bot đã dừng hoàn toàn. Hẹn gặp lại!")


if __name__ == "__main__":
    main()

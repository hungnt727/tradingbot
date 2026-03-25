"""
Master script to run Paper Trading for Top 300 coins.
Features:
- Incremental Data Syncing (Scheduler)
- Paper Trading Engine (Optimized SonicR logic)
- Hourly Telegram Reporting
"""
import os
import sys
import json
import requests
import pandas as pd

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
from strategies.sonicr_strategy import SonicRStrategy
from utils.telegram_bot import TelegramBot

load_dotenv()

CMC_API_KEY = os.getenv("CMC_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'top_300_cache.json')

def get_top_coins(limit=300, source="auto"):
    """
    Fetch top coins by market cap.
    
    Args:
        limit: Number of top coins to fetch (default 300)
        source: "coingecko", "coinmarketcap", or "auto" (try file cache first, then coingecko, then cmc)
    
    Returns:
        List of symbols like ["BTC/USDT", "ETH/USDT", ...]
    """
    # 1. Try to load from cache file first if source is "auto" or "file"
    if source in ("auto", "file"):
        cached = _load_cached_coins()
        if cached:
            logger.info(f"Loaded {len(cached)} coins from cache file")
            return cached[:limit]
    
    # 2. Try CoinGecko if source is "auto" or "coingecko"
    if source in ("auto", "coingecko"):
        coins = _fetch_from_coingecko(limit)
        if coins:
            _save_cached_coins(coins)
            return coins
        if source == "coingecko":
            logger.error("CoinGecko fetch failed and source=coingecko specified")
            return []
    
    # 3. Try CoinMarketCap if source is "auto" or "coinmarketcap"
    if source in ("auto", "coinmarketcap"):
        coins = _fetch_from_coinmarketcap(limit)
        if coins:
            _save_cached_coins(coins)
            return coins
        if source == "coinmarketcap":
            logger.error("CoinMarketCap fetch failed and source=coinmarketcap specified")
            return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    
    # 4. Final fallback
    logger.warning("All sources failed. Using fallback coins.")
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
def parse_timeframe_to_minutes(tf_str):
    """Convert timeframe string (e.g., '1m', '5m', '1h') to integer minutes."""
    if not tf_str:
        return 15
    unit = tf_str[-1].lower()
    try:
        val = int(tf_str[:-1])
    except ValueError:
        return 15
        
    if unit == 'm':
        return val
    elif unit == 'h':
        return val * 60
    elif unit == 'd':
        return val * 1440
    return 15



def _load_cached_coins():
    """Load coins from local cache file."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                coins = data.get('coins', [])
                timestamp = data.get('timestamp', 0)
                # Check if cache is less than 48 hours old (more lenient)
                import time
                if time.time() - timestamp < 172800:  # 48 hours
                    logger.debug(f"Cache file found: {CACHE_FILE}")
                    return coins
                else:
                    logger.info("Cache file expired (older than 24 hours)")
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
    return None


def _save_cached_coins(coins):
    """Save coins to local cache file."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        import time
        data = {
            'coins': coins,
            'timestamp': time.time(),
            'source': 'coingecko_or_cmc'
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(coins)} coins to cache: {CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


def _fetch_from_coingecko(limit=300):
    """Fetch top coins from CoinGecko API (no API key required)."""
    logger.info(f"Fetching top {limit} coins from CoinGecko...")
    
    all_coins = []
    per_page = 250  # Max allowed by CoinGecko
    
    try:
        # Page 1: Get first 250 coins
        url1 = f"https://api.coingecko.com/api/v3/coins/markets"
        params1 = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': per_page,
            'page': 1
        }
        response1 = requests.get(url1, params=params1, timeout=30)
        
        if response1.status_code == 200:
            data1 = response1.json()
            for coin in data1:
                symbol = coin.get('symbol', '').upper()
                if symbol:
                    all_coins.append(f"{symbol}/USDT")
            logger.info(f"CoinGecko page 1: Got {len(data1)} coins")
        else:
            logger.error(f"CoinGecko page 1 failed: {response1.status_code}")
            return None
        
        # If we need more than 250, get page 2
        if limit > per_page:
            params2 = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': limit - per_page,
                'page': 2
            }
            response2 = requests.get(url1, params=params2, timeout=30)
            
            if response2.status_code == 200:
                data2 = response2.json()
                for coin in data2:
                    symbol = coin.get('symbol', '').upper()
                    if symbol:
                        all_coins.append(f"{symbol}/USDT")
                logger.info(f"CoinGecko page 2: Got {len(data2)} coins")
        
        logger.success(f"CoinGecko: Total {len(all_coins)} coins fetched")
        return all_coins
        
    except Exception as e:
        logger.error(f"Failed to fetch from CoinGecko: {e}")
        return None


def _fetch_from_coinmarketcap(limit=300):
    """Fetch top coins from CoinMarketCap API."""
    if not CMC_API_KEY:
        logger.warning("CMC_API_KEY not set, skipping CoinMarketCap")
        return None
    
    logger.info(f"Fetching top {limit} coins from CoinMarketCap...")
    
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    parameters = {'start': '1', 'limit': str(limit), 'convert': 'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, params=parameters, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            coins = [f"{d['symbol']}/USDT" for d in data.get('data', [])]
            logger.success(f"CoinMarketCap: {len(coins)} coins fetched")
            return coins
        else:
            logger.error(f"CoinMarketCap failed: {response.status_code} - {response.text[:200]}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to fetch from CoinMarketCap: {e}")
        return None


# Backward compatibility - default to auto mode
def get_top_coins_legacy(limit=300):
    """Legacy function for backward compatibility."""
    return get_top_coins(limit=limit, source="auto")

def get_top_coins_v2(limit=300):
    """Fallback-first coin fetcher."""
    coins = []
    try:
        # Try CMC/CG first, but highly likely to fail due to quota
        coins = get_top_coins(limit, source="auto")
    except Exception:
        coins = []
        
    if not coins or len(coins) < 10: # Fallback happened in get_top_coins
        # Force read from my new cache specifically
        try:
            alt_cache = os.path.join(os.path.dirname(__file__), '..', 'data', 'top_300_cache.json')
            if os.path.exists(alt_cache):
                with open(alt_cache, 'r') as f:
                    coins = json.load(f)
                logger.info(f"Using hard fallback: {len(coins)} coins from top_300_cache.json")
        except Exception:
            pass
            
    if not coins:
        coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        
    return list(coins)[:limit]

def send_hourly_report(portfolio, bot):
    """Job to send hourly summary to Telegram."""
    try:
        stats = portfolio.get_hourly_stats()
        
        # Tổng kết toàn bộ
        all = stats['all']
        all_winrate = (all['wins'] / all['total'] * 100) if all['total'] > 0 else 0
        all_msg = (
            f"📊 <b>TỔNG KẾT TOÀN BỘ</b>\n"
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
            f"PnL: {hourly['pnl_usd']:+.2f}$ ({hourly['pnl_pct']:+.2f}%)\n"
            f"TP1: {hourly['tp1_count']} | TP2: {hourly['tp2_count']} | SL: {hourly['sl_count']} | Timeout: {hourly['timeout_count']}"
        )
        
        # Lệnh đang mở
        open_msg = f"🔓 <b>ĐANG MỞ</b>: {stats['open_count']} lệnh"
        
        # Gửi tin nhắn
        bot.send_message(f"{all_msg}\n\n{hourly_msg}\n\n{open_msg}")
        
    except Exception as e:
        logger.error(f"Reporting job failed: {e}")

def db_clear_data(symbols, timeframe="15m"):
    """Delete existing data and OPEN trades for symbols to ensure clean state."""
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL)
    logger.info(f"Da xoa du lieu {timeframe} va lenh OPEN cu cho {len(symbols)} coin...")
    with engine.begin() as conn:
        # Clear OHLCV for the selected symbols to force a fresh backfill if desired
        # If we want a 100% fresh start, we could truncate OHLCV, but that's expensive.
        # Clearing trades is mandatory for the "reset counts" request.
        logger.info("Xóa toàn bộ lịch sử lệnh (TOTAL RESET)...")
        conn.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
        
        # Clear OHLCV only for relevant symbols
        conn.execute(
            text("DELETE FROM ohlcv WHERE timeframe = :tf AND symbol IN :symbols"),
            {"tf": timeframe, "symbols": tuple(symbols)}
        )
    logger.success("Đã dọn dẹp Database.")

def perform_initial_backfill(crawler, db, symbols, timeframe="15m"):
    """Fetch 1000 candles for each symbol before starting the live loop."""
    logger.info(f"Bat dau Backfill 1000 nen {timeframe} cho {len(symbols)} coin...")
    count = 0
    for symbol in symbols:
        try:
            df = crawler.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
            if not df.empty:
                records = crawler.df_to_records(df)
                db.upsert_ohlcv(records)
                count += 1
                if count % 50 == 0:
                    logger.info(f"Đã backfill {count}/{len(symbols)} coin...")
        except Exception as e:
            logger.error(f"Lỗi backfill {symbol}: {e}")
    logger.success(f"Hoàn tất Backfill cho {count} coin.")

def filter_bybit_symbols(crawler, symbols):
    """Filter CMC symbols to only those supported by Bybit."""
    logger.info("Đang kiểm tra danh sách niêm yết trên Bybit...")
    try:
        markets = crawler.exchange.load_markets()
        market_type = getattr(crawler, 'market_type', 'linear') # linear (perp) or spot
        supported = []
        
        for sym in symbols:
            found = False
            # Check by key first
            if sym in markets:
                info = markets[sym]
                # Match type
                m_type = info.get('type')
                if market_type == 'linear':
                    if m_type in ['swap', 'future'] and info.get('linear'):
                        found = True
                elif market_type == 'spot':
                    if m_type == 'spot':
                        found = True
            
            if not found:
                # Check variants (e.g. sym:USDT)
                alt_sym = f"{sym}:USDT"
                if alt_sym in markets:
                    info = markets[alt_sym]
                    m_type = info.get('type')
                    if market_type == 'linear' and m_type in ['swap', 'future']:
                        found = True
                        sym = alt_sym # Use the exact key
            
            if found:
                supported.append(sym)

        logger.info(f"Lọc xong: {len(supported)}/{len(symbols)} coin khớp với market_type '{market_type}' trên Bybit.")
        return supported
    except Exception as e:
        logger.error(f"Lỗi khi load markets từ Bybit: {e}")
        return symbols[:50] # Fallback to a small set if error

def main():
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set in .env")
        return

    # 1. Initialize Components
    parser = argparse.ArgumentParser(description="SonicR Paper Trading Master Script")
    parser.add_argument("--top", type=int, default=300, help="Số lượng top coin muốn chạy (mặc định 300)")
    parser.add_argument("--timeframe", type=str, default="15m", help="Khung thời gian giao dịch (mặc định 15m)")
    args = parser.parse_args()

    strategy = SonicRStrategy()
    
    # NEW: Resolve dynamic HTF mapping from YAML
    timeframe_mapping = strategy.config.get("timeframe_mapping", {})
    if args.timeframe in timeframe_mapping:
        strategy.timeframe = args.timeframe
        strategy.htf_timeframe = timeframe_mapping[args.timeframe]
        # Re-apply config for the new timeframe
        strategy.apply_timeframe_config()
        logger.info(f"Da dat TimeFrame: {strategy.timeframe}, HTF: {strategy.htf_timeframe}")
    else:
        logger.warning(f"Khung thoi gian {args.timeframe} khong co trong mapping. Su dung mac dinh: {strategy.timeframe}/{strategy.htf_timeframe}")

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

    # NEW: Filter by Bybit Support
    symbols = filter_bybit_symbols(crawler, all_symbols)

    # Cleanup and Backfill before starting scheduler
    db_clear_data(symbols, args.timeframe)
    bot.send_message(f"🧹 <b>Hệ thống đã reset.</b> Đang chuẩn bị backfill dữ liệu cho {len(symbols)} coin ({strategy.timeframe})... Vui lòng đợi.")
    perform_initial_backfill(crawler, scheduler.db, symbols, args.timeframe)
    
    # NEW: Immediate Signal Scan
    logger.info(f"🔍 Đang thực hiện kiểm tra tín hiệu lập tức cho {len(symbols)} coin ({strategy.timeframe})...")
    engine = PaperTradingEngine(DATABASE_URL, strategy, symbols, exchange="bybit")
    try:
        engine._run_cycle()
    except Exception as e:
        logger.error(f"Lỗi khi quét tín hiệu ban đầu: {e}")
    
    # NEW: Report Initial Signal Summary
    from sqlalchemy import text
    with scheduler.db.engine.connect() as conn:
        long_c = conn.execute(text("SELECT count(*) FROM trades WHERE side = 'LONG'")).scalar()
        short_c = conn.execute(text("SELECT count(*) FROM trades WHERE side = 'SHORT'")).scalar()
    
    bot.send_message(
        f"✅ <b>Hoàn tất quét tín hiệu ban đầu!</b>\n"
        f"- 🟢 Long: {long_c}\n"
        f"- 🔴 Short: {short_c}\n"
        f"🚀 Đã mở lệnh cho {long_c + short_c} cặp tiềm năng."
    )
    logger.success(f"Hoàn tất quét tín hiệu ban đầu: {long_c} Long, {short_c} Short.")

    # 3. Setup Scheduler Jobs
    for sym in symbols:
        try:
            scheduler.add_job("bybit", sym, strategy.timeframe)
        except:
            continue
            
    # B. Paper Trading Job (Every 1 minute)
    cooldown = parse_timeframe_to_minutes(args.timeframe)
    engine = PaperTradingEngine(DATABASE_URL, strategy, symbols, exchange="bybit", sleep_seconds=0, cooldown_minutes=cooldown)
    scheduler.add_custom_job(
        func=engine._run_cycle,
        cron_kwargs={"minute": "*"},
        job_id="paper_trading_engine",
        name="SonicR Paper Trading Loop"
    )
    
    # C. Hourly Report Job
    scheduler.add_custom_job(
        func=lambda: send_hourly_report(engine.portfolio, bot),
        cron_kwargs={"minute": "0"},
        job_id="hourly_telegram_report",
        name="Telegram Hourly Summary"
    )
    
    # 4. Start
    bot.send_message(f"🚀 <b>TradingBot SonicR ({strategy.timeframe}) đã khởi động!</b>\nĐã lọc & backfill {len(symbols)} Coin hỗ trợ trên Bybit.\nBáo cáo mỗi 1h.")
    scheduler.start()
    
    print("\n" + "="*50)
    print(f"BOT DANG CHAY TREN {len(symbols)} COIN ({strategy.timeframe} - CHE DO PAPER)")
    print(">> Nhan phim 'q' de DUNG bot mot cach an toan.")
    print("="*50 + "\n")
    
    try:
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch().lower()
                if key == b'q':
                    logger.warning("Phím 'q' được nhấn. Đang dừng bot...")
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.warning("Nhận tín hiệu Ctrl+C. Đang dừng bot...")
    
    scheduler.stop()
    print("\n✅ Bot đã dừng hoàn toàn. Hẹn gặp lại!")



if __name__ == "__main__":
    main()

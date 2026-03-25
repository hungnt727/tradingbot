"""
Distribution Strategy Signal Bot - Gui tin hieu SHORT dua tren chien luoc phan phoi dinh.

Bot nay:
- Khong su dung Docker hay database
- Din ky (mac dinh 1 gio) crawl du lieu live tu Bybit
- Phan tich va gui tin hieu SHORT toi Telegram
- Cach lay du lieu giong voi run_distribution_paper.py
"""
import os
import sys
import json
import time
import argparse
import threading
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from dotenv import load_dotenv

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.crawler.bybit_crawler import BybitCrawler
from strategies.distribution_strategy import DistributionStrategy
from utils.telegram_bot import TelegramBot

load_dotenv()

# Cache file cho top coins
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'top_300_cache.json')

def get_top_coins(limit: int = 300) -> list[str]:
    """
    Lấy danh sách top coins từ CoinMarketCap API hoặc cache.
    """
    cache_max_age = 6 * 3600  # 6 hours
    
    # Try load from cache first
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cache_time = cache_data.get('timestamp', 0)
            if time.time() - cache_time < cache_max_age:
                symbols = cache_data.get('symbols', [])
                logger.info(f"Loaded {len(symbols)} symbols from cache")
                return symbols[:limit]
        except Exception as e:
            logger.warning(f"Cache load failed: {e}")
    
    # Fetch from CoinMarketCap
    try:
        import requests
        api_key = os.getenv('CMC_API_KEY')
        if not api_key:
            raise ValueError("CMC_API_KEY not set in .env")
        
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': api_key,
        }
        params = {
            'start': '1',
            'limit': str(limit),
            'convert': 'USDT'
        }
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        symbols = []
        for coin in data.get('data', []):
            symbol = coin.get('symbol', '').upper()
            if symbol:
                symbols.append(symbol)
        
        # Save to cache
        cache_data = {
            'timestamp': time.time(),
            'symbols': symbols
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        
        logger.info(f"Fetched {len(symbols)} symbols from CoinMarketCap")
        return symbols
        
    except Exception as e:
        logger.error(f"CoinMarketCap API failed: {e}")
        # Return default top coins as fallback
        return [
            "BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "DOT", "MATIC", "SHIB",
            "LTC", "TRX", "AVAX", "LINK", "ATOM", "UNI", "XMR", "ETC", "XLM", "BCH",
            "ALGO", "NEAR", "VET", "FIL", "ICP", "APE", "SAND", "MANA", "AXS", "THETA",
            "EGLD", "HBAR", "XTZ", "AAVE", "EOS", "FTM", "FLOW", "ZEC", "HIVE", "KCS",
            "CRO", "GRT", "STX", "RUNE", "KAVA", "COMP", "BAT", "ENJ", "MINA", "ONE",
            "CHZ", "LRC", "SKL", "STORJ", "SUSHI", "SNX", "YFI", "CRV", "MKR", "BADGER",
        ]


def filter_bybit_symbols(crawler: BybitCrawler, symbols: list[str]) -> list[str]:
    """
    Filter CMC symbols to only those supported by Bybit linear perpetual markets.
    Symbols from CMC are like 'BTC', 'ETH'. Bybit markets are like 'BTC/USDT:USDT'.
    """
    logger.info("Filtering symbols supported on Bybit...")
    try:
        markets = crawler.exchange.load_markets()
        market_type = getattr(crawler, 'market_type', 'linear')  # linear (perp) or spot
        supported = []
        
        for sym in symbols:
            found = False
            exact_sym = None
            
            # Check various formats Bybit might use
            # CMC returns: BTC, ETH
            # Bybit linear perpetual: BTC/USDT:USDT, ETH/USDT:USDT
            variants = [
                f"{sym}/USDT:USDT",  # Primary format for linear perpetuals
                f"{sym}:USDT",        # Alternative format
                f"{sym}/USDT",        # Spot format
            ]
            
            for variant in variants:
                if variant in markets:
                    info = markets[variant]
                    m_type = info.get('type')
                    if market_type == 'linear':
                        if m_type in ['swap', 'future'] and info.get('linear'):
                            found = True
                            exact_sym = variant
                            break
                    elif market_type == 'spot':
                        if m_type == 'spot':
                            found = True
                            exact_sym = variant
                            break
            
            if found and exact_sym:
                supported.append(exact_sym)
        
        logger.info(f"Filtered {len(supported)}/{len(symbols)} symbols for market_type '{market_type}' on Bybit")
        return supported
        
    except Exception as e:
        logger.error(f"Error filtering Bybit symbols: {e}")
        return symbols[:50]  # Fallback


class DistributionSignalBot:
    """
    Bot gửi tín hiệu Distribution (SHORT) định kỳ tới Telegram.
    """
    
    def __init__(
        self,
        interval_hours: float = 1.0,
        top_coins: int = 100,
        timeframe: str = "1d",
        lookback_candles: int = 300,
    ):
        self.interval_hours = interval_hours
        self.interval_seconds = int(interval_hours * 3600)
        self.top_coins = top_coins
        self.timeframe = timeframe
        self.lookback_candles = lookback_candles
        
        # Initialize components
        self.strategy = DistributionStrategy()
        self.strategy.timeframe = timeframe
        
        self.crawler = BybitCrawler(
            api_key=os.getenv("BYBIT_API_KEY", ""),
            api_secret=os.getenv("BYBIT_SECRET", ""),
        )
        
        self.telegram = TelegramBot()
        
        # Track last signals to avoid duplicates
        self.last_signals: dict[str, dict] = {}
        
        # Get symbols
        self.symbols: list[str] = []
        
        logger.info(
            f"[SignalBot] Initialized - Interval: {interval_hours}h, "
            f"Top: {top_coins}, TF: {timeframe}"
        )
    
    def _get_symbols(self) -> list[str]:
        """Lấy danh sách symbols từ cache hoặc API."""
        top_symbols = get_top_coins(limit=self.top_coins)
        return filter_bybit_symbols(self.crawler, top_symbols)
    
    def _scan_signal(self, df) -> Optional[dict]:
        """
        Quét tín hiệu từ DataFrame.
        Trả về dict chứa thông tin signal hoặc None nếu không có signal.
        """
        try:
            # Compute indicators
            df = self.strategy.compute_indicators(df)
            
            # Generate signals
            df = self.strategy.generate_signals(df, is_live=True)
            
            # Get latest signal
            if len(df) < self.strategy.min_candles_required:
                return None
            
            last_row = df.iloc[-1]
            
            # Check if there's a SHORT signal
            if last_row['signal'] == -1:
                return {
                    'symbol': df.iloc[-1].get('symbol', 'UNKNOWN'),
                    'side': 'SHORT',
                    'price': float(last_row['close']),
                    'range_position': float(last_row['range_position']),
                    'distribution_score': int(last_row['distribution_score']),
                    'entry_reason': last_row.get('entry_reason', ''),
                    'ema_bearish': bool(last_row['ema_bearish_alignment']),
                    'rsi_bearish': bool(last_row['rsi_bearish']),
                    'volume_spike': bool(last_row['volume_spike']),
                    'swing_high': float(last_row['swing_high']),
                    'swing_low': float(last_row['swing_low']),
                    'upper_zone': float(last_row['upper_zone']),
                    'atr': float(last_row['atr']) if 'atr' in last_row else None,
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error scanning signal: {e}")
            return None
    
    def _fetch_and_scan(self, symbol: str) -> Optional[dict]:
        """Fetch data for a symbol and scan for signals."""
        try:
            df = self.crawler.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=self.lookback_candles)
            if df.empty or len(df) < self.strategy.min_candles_required:
                return None
            
            # Add symbol to dataframe for tracking
            df['symbol'] = symbol
            
            return self._scan_signal(df)
            
        except Exception as e:
            logger.debug(f"Error fetching {symbol}: {e}")
            return None
    
    def _format_price(self, price: float) -> str:
        """Dynamic price formatting."""
        if price is None:
            return "N/A"
        if price >= 100:
            return f"{price:.2f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.01:
            return f"{price:.6f}"
        return f"{price:.8f}"
    
    def _is_new_signal(self, symbol: str, signal_data: dict) -> bool:
        """Kiểm tra xem signal có phải là signal mới không."""
        if symbol not in self.last_signals:
            return True
        
        last = self.last_signals[symbol]
        # Signal is new if price or score changed significantly
        price_change = abs(signal_data['price'] - last['price']) / last['price'] > 0.01
        return price_change
    
    def run_cycle(self) -> list[dict]:
        """
        Thực hiện một chu kỳ quét tín hiệu.
        Trả về danh sách các signals mới.
        """
        logger.info(f"[SignalBot] Starting signal scan for {len(self.symbols)} symbols...")
        
        new_signals = []
        scan_count = 0
        error_count = 0
        
        for symbol in self.symbols:
            try:
                signal = self._fetch_and_scan(symbol)
                scan_count += 1
                
                if signal and self._is_new_signal(symbol, signal):
                    self.last_signals[symbol] = signal
                    new_signals.append(signal)
                    logger.info(
                        f"[SignalBot] {signal['side']} @ {symbol.replace('/USDT:USDT', '')} "
                        f"${signal['price']:.4f} (score: {signal['distribution_score']})"
                    )
                
                # Rate limiting
                time.sleep(0.2)
                
            except Exception as e:
                error_count += 1
                logger.debug(f"Error scanning {symbol}: {e}")
                continue
        
        logger.info(
            f"[SignalBot] Scan complete: {scan_count} scanned, "
            f"{len(new_signals)} new signals, {error_count} errors"
        )
        
        return new_signals
    
    def _format_signal_message(self, signals: list[dict]) -> str:
        """Format danh sách signals thành message Telegram."""
        if not signals:
            return None
        
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Header
        msg = (
            f"📊 <b>DISTRIBUTION SIGNALS</b>\n"
            f"⏰ Cập nhật: {timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
        # Sort by distribution score (highest first)
        sorted_signals = sorted(signals, key=lambda x: x['distribution_score'], reverse=True)
        
        for sig in sorted_signals:
            symbol = sig['symbol'].replace('/USDT:USDT', '')
            price = self._format_price(sig['price'])
            score = sig['distribution_score']
            range_pos = sig['range_position']
            
            # Entry reasons
            reasons = []
            if sig.get('ema_bearish'):
                reasons.append("EMA👇")
            if sig.get('rsi_bearish'):
                reasons.append("RSI<50")
            if sig.get('volume_spike'):
                reasons.append("VOL↑")
            
            reasons_str = " | ".join(reasons) if reasons else "upper_zone"
            
            # Entry/Exit info
            atr = sig.get('atr')
            if atr:
                sl = sig['price'] + (atr * 2)
                sl_str = f"SL: ${self._format_price(sl)}"
            else:
                sl_str = f"SL: {sig['price'] * 1.05:.4f} (+5%)"
            
            msg += (
                f"🔴 <b>{symbol} - SHORT</b>\n"
                f"   💰 Price: ${price}\n"
                f"   📈 Range Pos: {range_pos:.0%}\n"
                f"   🎯 Score: {score}/100\n"
                f"   📋 Reason: {reasons_str}\n"
                f"   🛡️ {sl_str}\n\n"
            )
        
        # Footer
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Chiến lược: Distribution Phase Detection ({self.timeframe})\n"
            f"Tổng signals: {len(signals)}</i>"
        )
        
        return msg
    
    def _format_summary_message(self, total_scanned: int, new_signals: int) -> str:
        """Format summary message khi không có signal mới."""
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return (
            f"🔍 <b>DISTRIBUTION SCAN COMPLETE</b>\n"
            f"⏰ {timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Đã quét: {total_scanned} coins\n"
            f"🆕 Signals mới: {new_signals}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Chiến lược: Distribution ({self.timeframe})\n"
            f"Không có tín hiệu SHORT mới</i>"
        )
    
    def send_signals(self, new_signals: list[dict]):
        """Gửi signals tới Telegram."""
        if new_signals:
            message = self._format_signal_message(new_signals)
            if message:
                self.telegram.send_message(message)
                logger.info(f"[SignalBot] Sent {len(new_signals)} signals to Telegram")
        else:
            # Still send a summary even if no new signals
            if self.telegram.enabled:
                message = self._format_summary_message(len(self.symbols), 0)
                self.telegram.send_message(message)
    
    def _run_loop(self):
        """Internal loop handler."""
        while self._running:
            try:
                new_signals = self.run_cycle()
                self.send_signals(new_signals)
            except Exception as e:
                logger.error(f"[SignalBot] Cycle error: {e}")
            
            # Wait for next interval (check every second for shutdown)
            for _ in range(self.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)
    
    def start(self):
        """Bắt đầu bot."""
        logger.info("[SignalBot] Starting...")
        
        # Get symbols
        self.symbols = self._get_symbols()
        logger.info(f"[SignalBot] Loaded {len(self.symbols)} symbols")
        
        # Send startup message
        self.telegram.send_message(
            f"🚀 <b>Distribution Signal Bot đã khởi động!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Chiến lược: Distribution Phase Detection\n"
            f"⏰ Interval: {self.interval_hours} giờ\n"
            f"📈 Timeframe: {self.timeframe}\n"
            f"🪙 Số coins: {len(self.symbols)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Đang quét tín hiệu...</i>"
        )
        
        # Run initial scan
        logger.info("[SignalBot] Running initial scan...")
        new_signals = self.run_cycle()
        self.send_signals(new_signals)
        
        # Start scheduled loop
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"[SignalBot] Started - Next scan in {self.interval_hours}h")
    
    def stop(self):
        """Dừng bot."""
        logger.info("[SignalBot] Stopping...")
        self._running = False
        
        if hasattr(self, '_thread'):
            self._thread.join(timeout=5)
        
        self.telegram.send_message(
            "🛑 <b>Distribution Signal Bot đã dừng!</b>\n"
            f"⏰ Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        
        logger.info("[SignalBot] Stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Distribution Strategy Signal Bot - Send SHORT signals to Telegram"
    )
    parser.add_argument(
        "--interval", 
        type=float, 
        default=1.0, 
        help="Interval between scans in hours (default: 1.0)"
    )
    parser.add_argument(
        "--top", 
        type=int, 
        default=100, 
        help="Number of top coins to scan (default: 100)"
    )
    parser.add_argument(
        "--timeframe", 
        type=str, 
        default="1d", 
        help="Timeframe for strategy (default: 1d)"
    )
    parser.add_argument(
        "--lookback", 
        type=int, 
        default=300, 
        help="Number of candles to lookback (default: 300, min 200 for distribution strategy)"
    )
    parser.add_argument(
        "--oneshot", 
        action="store_true", 
        help="Run single scan and exit"
    )
    
    args = parser.parse_args()
    
    # Initialize bot
    bot = DistributionSignalBot(
        interval_hours=args.interval,
        top_coins=args.top,
        timeframe=args.timeframe,
        lookback_candles=args.lookback,
    )
    
    if args.oneshot:
        # Run single scan and exit
        logger.info("[SignalBot] Running one-shot mode...")
        # Load symbols for oneshot mode
        bot.symbols = bot._get_symbols()
        logger.info(f"[SignalBot] Loaded {len(bot.symbols)} symbols")
        new_signals = bot.run_cycle()
        bot.send_signals(new_signals)
        return
    
    # Start continuous mode
    bot.start()
    
    print("\n" + "="*60)
    print("DISTRIBUTION SIGNAL BOT RUNNING")
    print(">> Press Ctrl+C to STOP bot")
    print("="*60 + "\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n")
        logger.warning("Received Ctrl+C. Stopping bot...")
    
    bot.stop()
    print("\n[!] Bot stopped completely. Goodbye!")


if __name__ == "__main__":
    main()

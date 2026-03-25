"""
EMA RSI Reversal Signal Bot - Gui tin hieu SHORT dua tren chien luoc dao chieu EMA RSI
Ket hop tin hieu tu 2 khung thoi gian 1D va 1H.
"""
import os
import sys
import json
import time
import argparse
import threading
from datetime import datetime
from typing import Optional
from loguru import logger
from dotenv import load_dotenv

# Allow importing from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.crawler.bybit_crawler import BybitCrawler
from strategies.ema_rsi_reversal_strategy import EmaRsiReversalStrategy
from utils.telegram_bot import TelegramBot
from cli.run_distribution_signal_bot import get_top_coins, filter_bybit_symbols

load_dotenv()


class EmaRsiReversalSignalBot:
    """
    Bot gửi tín hiệu EMA RSI Reversal (SHORT) định kỳ tới Telegram.
    Sử dụng đa khung thời gian: 1D và 1H.
    """
    
    def __init__(
        self,
        interval_hours: float = 1.0,
        top_coins: int = 100,
        lookback_candles: int = 200,
        n_1d: int = 20,
        m_1h: int = 3,
    ):
        self.interval_hours = interval_hours
        self.interval_seconds = int(interval_hours * 3600)
        self.top_coins = top_coins
        self.lookback_candles = lookback_candles
        
        self.n_1d = n_1d
        self.m_1h = m_1h
        
        # Initialize components
        self.strategy_1d = EmaRsiReversalStrategy(max_distance_candles=n_1d)
        self.strategy_1h = EmaRsiReversalStrategy(max_distance_candles=m_1h)
        
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
            f"Top: {top_coins}, 1D dist: {n_1d}, 1H dist: {m_1h}"
        )
    
    def _get_symbols(self) -> list[str]:
        """Lấy danh sách symbols từ cache hoặc CMC API."""
        top_symbols = get_top_coins(limit=self.top_coins)
        return filter_bybit_symbols(self.crawler, top_symbols)
    
    def _scan_1d(self, df) -> Optional[dict]:
        """Quét tín hiệu trên khung 1D."""
        try:
            df = self.strategy_1d.compute_indicators(df)
            df = self.strategy_1d.generate_signals(df)
            
            if len(df) < self.strategy_1d.min_candles_required:
                return None
            
            last_row = df.iloc[-1]
            if last_row['signal'] == -1:
                return {
                    'symbol': df.iloc[-1].get('symbol', 'UNKNOWN'),
                    'price_1d': float(last_row['close']),
                    'bars_since_reversal_1d': int(last_row['bars_since_reversal']),
                    'ema_rsi_5_1d': float(last_row['ema_rsi_5']),
                    'ema_rsi_10_1d': float(last_row['ema_rsi_10']),
                    'ema_rsi_20_1d': float(last_row['ema_rsi_20']),
                    'atr_1d': float(last_row.get('atr', 0)),
                }
            return None
        except Exception as e:
            logger.debug(f"Error scanning 1D signal: {e}")
            return None

    def _scan_1h(self, df) -> Optional[dict]:
        """Quét tín hiệu trên khung 1H."""
        try:
            df = self.strategy_1h.compute_indicators(df)
            df = self.strategy_1h.generate_signals(df)
            
            if len(df) < self.strategy_1h.min_candles_required:
                return None
            
            last_row = df.iloc[-1]
            if last_row['signal'] == -1:
                return {
                    'price_1h': float(last_row['close']),
                    'bars_since_reversal_1h': int(last_row['bars_since_reversal']),
                    'ema_rsi_5_1h': float(last_row['ema_rsi_5']),
                    'ema_rsi_10_1h': float(last_row['ema_rsi_10']),
                    'ema_rsi_20_1h': float(last_row['ema_rsi_20']),
                    'atr_1h': float(last_row.get('atr', 0)),
                }
            return None
        except Exception as e:
            logger.debug(f"Error scanning 1H signal: {e}")
            return None

    def _fetch_and_scan(self, symbol: str) -> Optional[dict]:
        """Fetch data and process multi-timeframe signal."""
        try:
            # 1. Fetch 1D data
            df_1d = self.crawler.fetch_ohlcv(symbol, timeframe="1d", limit=self.lookback_candles)
            if df_1d.empty or len(df_1d) < self.strategy_1d.min_candles_required:
                return None
            
            df_1d['symbol'] = symbol
            signal_1d = self._scan_1d(df_1d)
            
            # If 1D doesn't trigger, skip 1H fetch to save API limits
            if not signal_1d:
                return None
            
            # 2. Fetch 1H data
            df_1h = self.crawler.fetch_ohlcv(symbol, timeframe="1h", limit=self.lookback_candles)
            if df_1h.empty or len(df_1h) < self.strategy_1h.min_candles_required:
                return None
            
            df_1h['symbol'] = symbol
            signal_1h = self._scan_1h(df_1h)
            
            if not signal_1h:
                return None
            
            # 3. Combine signals
            combined_signal = {**signal_1d, **signal_1h}
            return combined_signal
            
        except Exception as e:
            logger.debug(f"Error fetching/scanning {symbol}: {e}")
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
        # Signal is new if basically something changed (e.g., new 1H bar crossed)
        # Using bars_since_reversal_1h logic to filter out spam. 
        # Alternatively, tracking price variation.
        price_change = abs(signal_data['price_1h'] - last['price_1h']) / last['price_1h'] > 0.01
        bar_change = signal_data['bars_since_reversal_1h'] != last['bars_since_reversal_1h']
        
        return price_change or bar_change
    
    def run_cycle(self) -> list[dict]:
        """
        Thực hiện một chu kỳ quét tín hiệu.
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
                        f"[SignalBot] SHORT @ {symbol.replace('/USDT:USDT', '')} "
                        f"${signal['price_1h']:.4f} (1D={signal['bars_since_reversal_1d']}, 1H={signal['bars_since_reversal_1h']})"
                    )
                
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
        
        msg = (
            f"📉 <b>EMA RSI REVERSAL SIGNALS</b>\n"
            f"⏰ Cập nhật: {timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
        # Sort by 1H bars since reversal (closest to reversal first)
        sorted_signals = sorted(signals, key=lambda x: x['bars_since_reversal_1h'])
        
        for sig in sorted_signals:
            symbol = sig['symbol'].replace('/USDT:USDT', '')
            price = self._format_price(sig['price_1h'])
            
            b_1d = sig['bars_since_reversal_1d']
            b_1h = sig['bars_since_reversal_1h']
            ema_5_1d = sig['ema_rsi_5_1d']
            ema_10_1d = sig['ema_rsi_10_1d']
            ema_20_1d = sig['ema_rsi_20_1d']
            
            ema_5_1h = sig['ema_rsi_5_1h']
            ema_10_1h = sig['ema_rsi_10_1h']
            ema_20_1h = sig['ema_rsi_20_1h']
            
            atr = sig.get('atr_1h')
            if atr:
                sl = sig['price_1h'] + (atr * 2)
                sl_str = f"SL: ${self._format_price(sl)}"
            else:
                sl_str = f"SL: {sig['price_1h'] * 1.05:.4f} (+5%)"
            
            msg += (
                f"🔴 <b>{symbol} - SHORT</b>\n"
                f"   💰 Price: ${price}\n"
                f"   ⏳ Cách nến suy yếu (1D): {b_1d} nến | (1H): {b_1h} nến\n"
                f"   📈 1D EMA RSI (5-10-20): {ema_5_1d:.1f} - {ema_10_1d:.1f} - {ema_20_1d:.1f}\n"
                f"   📈 1H EMA RSI (5-10-20): {ema_5_1h:.1f} - {ema_10_1h:.1f} - {ema_20_1h:.1f}\n"
                f"   🛡️ {sl_str}\n\n"
            )
        
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Chiến lược: Đảo chiều suy yếu RSI\n"
            f"Tổng signals: {len(signals)}</i>"
        )
        
        return msg
    
    def _format_summary_message(self, total_scanned: int, new_signals: int) -> str:
        """Format summary message khi không có signal mới."""
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return (
            f"🔍 <b>EMA RSI REVERSAL SCAN COMPLETE</b>\n"
            f"⏰ {timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Đã quét: {total_scanned} coins\n"
            f"🆕 Signals mới: {new_signals}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Không có tín hiệu SHORT mới</i>"
        )
    
    def send_signals(self, new_signals: list[dict]):
        """Gửi signals tới Telegram."""
        if new_signals:
            message = self._format_signal_message(new_signals)
            if message:
                self.telegram.send_message(message)
                logger.info(f"[SignalBot] Sent {len(new_signals)} signals to Telegram")
        else:
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
            
            for _ in range(self.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)
    
    def start(self):
        """Bắt đầu bot."""
        logger.info("[SignalBot] Starting...")
        
        self.symbols = self._get_symbols()
        logger.info(f"[SignalBot] Loaded {len(self.symbols)} symbols")
        
        self.telegram.send_message(
            f"🚀 <b>EMA RSI Reversal Bot đã khởi động!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Chiến lược: Đảo chiều RSI Suy Yếu (SHORT)\n"
            f"⏰ Interval: {self.interval_hours} giờ\n"
            f"📈 Timeframe: 1D + 1H\n"
            f"🪙 Số coins: {len(self.symbols)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Đang quét tín hiệu...</i>"
        )
        
        logger.info("[SignalBot] Running initial scan...")
        new_signals = self.run_cycle()
        self.send_signals(new_signals)
        
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
            "🛑 <b>EMA RSI Reversal Bot đã dừng!</b>\n"
            f"⏰ Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        logger.info("[SignalBot] Stopped")


def main():
    parser = argparse.ArgumentParser(
        description="EMA RSI Reversal Signal Bot - Send SHORT signals to Telegram"
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
        "--lookback", 
        type=int, 
        default=250, 
        help="Number of candles to lookback (default: 250)"
    )
    parser.add_argument(
        "--n1d", 
        type=int, 
        default=20, 
        help="Max distance candles from 1D reversal (default: 20)"
    )
    parser.add_argument(
        "--m1h", 
        type=int, 
        default=3, 
        help="Max distance candles from 1H reversal (default: 3)"
    )
    parser.add_argument(
        "--oneshot", 
        action="store_true", 
        help="Run single scan and exit"
    )
    
    args = parser.parse_args()
    
    bot = EmaRsiReversalSignalBot(
        interval_hours=args.interval,
        top_coins=args.top,
        lookback_candles=args.lookback,
        n_1d=args.n1d,
        m_1h=args.m1h
    )
    
    if args.oneshot:
        logger.info("[SignalBot] Running one-shot mode...")
        bot.symbols = bot._get_symbols()
        logger.info(f"[SignalBot] Loaded {len(bot.symbols)} symbols")
        new_signals = bot.run_cycle()
        bot.send_signals(new_signals)
        return
    
    bot.start()
    
    print("\n" + "="*60)
    print("EMA RSI REVERSAL SIGNAL BOT RUNNING")
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

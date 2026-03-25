"""
Paper Trading Engine.

Executes trading strategies in real-time against fetched OHLCV data.
Checks open positions for SL/TP hits using the latest price.
Generates signals on new closed candles and opens paper trades.
"""
import time
from datetime import datetime
from typing import List

from loguru import logger
import pandas as pd

from data.storage.timescale_client import TimescaleClient
from paper_trading.portfolio import PortfolioManager
from strategies.base_strategy import BaseStrategy
from data.models.trade import TradeSide, TradeStatus


class PaperTradingEngine:
    """
    Core engine loop for paper trading.
    """

    def __init__(
        self,
        db_url: str,
        strategy: BaseStrategy,
        symbols: List[str],
        exchange: str = "binance",
        sleep_seconds: int = 60,
        cooldown_minutes: int = 15,
    ):
        self.db = TimescaleClient(db_url)
        self.portfolio = PortfolioManager(db_url)
        self.strategy = strategy
        self.symbols = symbols
        self.exchange = exchange
        self.sleep_seconds = sleep_seconds
        
        # In a generic setup, position size could be dynamic
        self.position_size_usd = 1000.0  
        self.last_close_times = {} # symbol -> datetime of last close
        self.cooldown_minutes = cooldown_minutes

        logger.info(f"Initialized Paper Trading Engine with {self.strategy.name} for {self.symbols} (Cooldown: {self.cooldown_minutes}m)")

    def run(self):
        """Start the endless paper trading loop."""
        logger.info("Starting Paper Trading Loop...")
        try:
            while True:
                self._run_cycle()
                time.sleep(self.sleep_seconds)
        except KeyboardInterrupt:
            logger.info("Paper Trading Engine stopped by user.")
        except Exception as e:
            logger.exception(f"Paper Trading Engine crashed: {e}")

    def _run_cycle(self):
        """Single execution cycle (check stops, generate signals)."""
        now = datetime.utcnow()
        logger.debug(f"--- Paper Trading Cycle @ {now.strftime('%Y-%m-%d %H:%M:%S UTC')} ---")

        for symbol in self.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")

    def _process_symbol(self, symbol: str):
        """Process a single symbol: verify open trades, fetch data, check signals."""
        # 1. Fetch latest data
        df = self.db.query_ohlcv(
            exchange=self.exchange,
            symbol=symbol,
            timeframe=self.strategy.timeframe,
            start=datetime.utcnow() - pd.Timedelta(days=30)
        )
        
        if df.empty or len(df) < 50:
            return

        latest_candle = df.iloc[-1]
        now = datetime.utcnow()
        
        # 0. Cooldown check
        if symbol in self.last_close_times:
            elapsed = (now - self.last_close_times[symbol]).total_seconds() / 60
            if elapsed < self.cooldown_minutes:
                return # Skip this symbol for now
        
        # 2. Check open trades for SL / TP hits and Timeouts
        open_trades = self.portfolio.get_open_trades(self.exchange, symbol)
        for trade in open_trades:
            # Update bar count in metadata
            try:
                import json
                meta = json.loads(trade.trade_metadata) if trade.trade_metadata else {"bars": 0}
                meta["bars"] = meta.get("bars", 0) + 1
                trade.trade_metadata = json.dumps(meta)
                # Note: We'll save this later or implicitly during check_sl_tp if it calls a save
            except:
                meta = {"bars": 1}
            
            self._check_sl_tp_timeout(trade, latest_candle, meta["bars"])

        # 3. Compute signals
        df_ind = self.strategy.compute_indicators(df)
        df_sig = self.strategy.generate_signals(df_ind, symbol=symbol, is_live=True)
        
        last_row = df_sig.iloc[-1]
        signal_val = int(last_row.get("signal", 0))

        if signal_val != 0:
            side = TradeSide.LONG if signal_val == 1 else TradeSide.SHORT
            if self.portfolio.has_open_trade(self.exchange, symbol, self.strategy.name):
                return

            entry_price = float(latest_candle["close"])
            # TP1, TP2 Logic
            tp1_dist = entry_price * self.strategy.tp_levels[0]
            tp2_dist = entry_price * self.strategy.tp_levels[1]
            sl_dist = entry_price * self.strategy.sl_pct
            
            if side == TradeSide.LONG:
                sl, tp1 = entry_price - sl_dist, entry_price + tp1_dist
            else:
                sl, tp1 = entry_price + sl_dist, entry_price - tp1_dist

            import json
            tp2_val = entry_price + tp2_dist if side == TradeSide.LONG else entry_price - tp2_dist
            self.portfolio.open_trade(
                exchange=self.exchange,
                symbol=symbol,
                strategy=self.strategy.name,
                timeframe=self.strategy.timeframe,
                side=side,
                entry_price=float(entry_price),
                position_size=float(self.position_size_usd),
                sl_price=float(sl),
                tp_price=float(tp1), # Start with TP1
                tp2_price=float(tp2_val),
                trade_metadata=json.dumps({"bars": 0})
            )

    def _check_sl_tp_timeout(self, trade, latest_candle: pd.Series, bars: int):
        """Check if SL, TP1, TP2 or Timeout was hit."""
        high, low, close = latest_candle["high"], latest_candle["low"], latest_candle["close"]
        tp2_price = trade.tp2_price

        # 1. Check Timeout (Only if in profit)
        if bars >= self.strategy.max_holding:
            is_profit = False
            if trade.side == TradeSide.LONG and close > trade.entry_price: is_profit = True
            if trade.side == TradeSide.SHORT and close < trade.entry_price: is_profit = True
            
            if is_profit:
                self.portfolio.close_trade(trade.id, close, "TIMEOUT_PROFIT")
                return

        # 2. Check SL / TP
        if trade.side == TradeSide.LONG:
            # Check SL
            if low <= trade.sl_price:
                reason = "sl_hit" if trade.sl_price < trade.entry_price else "SL_BREAKEVEN"
                logger.warning(f"🚨 [SL] {trade.symbol} hit SL at Price {low} (SL level: {trade.sl_price}) on Candle {latest_candle.name}")
                self.portfolio.close_trade(trade.id, trade.sl_price, reason)
                self.last_close_times[trade.symbol] = datetime.utcnow()
            # Check TP
            elif high >= trade.tp_price:
                if not trade.tp1_hit:
                    # TP1 Hit -> Move SL to entry, Update TP to TP2
                    logger.success(f"🎯 [TP1] {trade.symbol} hit TP1 at Price {high} (TP level: {trade.tp_price})")
                    self.portfolio.update_tp1_hit(trade.id, True)
                    self.portfolio.update_trade(trade.id, sl_price=trade.entry_price, tp_price=tp2_price)
                else:
                    # TP2 Hit -> Close
                    logger.success(f"🚀 [TP2] {trade.symbol} hit TP2 at Price {high} (TP level: {trade.tp_price})")
                    self.portfolio.close_trade(trade.id, trade.tp_price, "tp_hit")
                    self.last_close_times[trade.symbol] = datetime.utcnow()
        else: # SHORT
            if high >= trade.sl_price:
                reason = "sl_hit" if trade.sl_price > trade.entry_price else "SL_BREAKEVEN"
                logger.warning(f"🚨 [SL] {trade.symbol} hit SL at Price {high} (SL level: {trade.sl_price}) on Candle {latest_candle.name}")
                self.portfolio.close_trade(trade.id, trade.sl_price, reason)
                self.last_close_times[trade.symbol] = datetime.utcnow()
            elif low <= trade.tp_price:
                if not trade.tp1_hit:
                    logger.success(f"🎯 [TP1] {trade.symbol} hit TP1 at Price {low} (TP level: {trade.tp_price})")
                    self.portfolio.update_tp1_hit(trade.id, True)
                    self.portfolio.update_trade(trade.id, sl_price=trade.entry_price, tp_price=tp2_price)
                else:
                    logger.success(f"🚀 [TP2] {trade.symbol} hit TP2 at Price {low} (TP level: {trade.tp_price})")
                    self.portfolio.close_trade(trade.id, trade.tp_price, "tp_hit")
                    self.last_close_times[trade.symbol] = datetime.utcnow()

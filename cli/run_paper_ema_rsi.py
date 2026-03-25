"""
Master script: Paper Trading for EMA RSI Reversal (1D + 1H MTF).
Optimized config: SL 5%, TP1 10%, TP2 20%, No Move SL after TP1.
"""
import os
import sys
import time
import argparse
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
import pandas as pd

if os.name == 'nt':
    import msvcrt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.crawler.scheduler import DataScheduler
from data.crawler.bybit_crawler import BybitCrawler
from data.storage.timescale_client import TimescaleClient
from paper_trading.engine import PaperTradingEngine
from paper_trading.portfolio import PortfolioManager
from strategies.ema_rsi_reversal_strategy import EmaRsiReversalStrategy
from utils.telegram_bot import TelegramBot
from cli.run_distribution_signal_bot import get_top_coins, filter_bybit_symbols

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


class MTFEmaRsiStrategy:
    """
    Multi-Timeframe wrapper: 1D trend filter + 1H entry signal.
    Exposes the same interface as a standard BaseStrategy so the
    PaperTradingEngine can use it transparently.
    """

    def __init__(self, strategy_1d, strategy_1h, db: TimescaleClient):
        self._1d = strategy_1d
        self._1h = strategy_1h
        self._db = db

        # Expose attributes that PaperTradingEngine reads
        self.name = "EmaRsiReversal_MTF"
        self.timeframe = "1h"
        self.sl_pct = strategy_1h.sl_pct
        self.tp_levels = strategy_1h.tp_levels
        self.max_holding = strategy_1h.max_holding
        self.no_move_sl_after_tp1 = strategy_1h.no_move_sl_after_tp1

    # ------- PaperTradingEngine interface -------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._1h.compute_indicators(df)

    def generate_signals(self, df_1h_ind: pd.DataFrame, symbol: str = "UNKNOWN", is_live: bool = True) -> pd.DataFrame:
        df_sig = self._1h.generate_signals(df_1h_ind)

        # 1H signal not present → nothing to filter
        if df_sig.iloc[-1]["signal"] == 0:
            return df_sig

        # 1D MTF filter
        try:
            df_1d = self._db.query_latest_ohlcv(
                exchange="bybit", symbol=symbol, timeframe="1d", limit=110
            )
            if df_1d.empty or len(df_1d) < self._1d.min_candles_required:
                df_sig.iloc[-1, df_sig.columns.get_loc("signal")] = 0
                return df_sig

            df_1d_ind = self._1d.compute_indicators(df_1d)
            df_1d_sig = self._1d.generate_signals(df_1d_ind)

            last_1d = df_1d_sig.iloc[-1]["signal"]
            if last_1d != -1:
                logger.debug(f"[MTF] {symbol} filtered – 1D not in SHORT zone")
                df_sig.iloc[-1, df_sig.columns.get_loc("signal")] = 0
            else:
                logger.info(f"🔥 [MTF] CONFIRMED SHORT – {symbol} (1D+1H aligned)")

        except Exception as exc:
            logger.error(f"[MTF] signal generation error for {symbol}: {exc}")
            df_sig.iloc[-1, df_sig.columns.get_loc("signal")] = 0

        return df_sig

    def get_sl_tp(self, entry_price, signal, atr=None):
        return self._1h.get_sl_tp(entry_price, signal, atr)

    def validate_df(self, df):
        return self._1h.validate_df(df)


def send_report(portfolio: PortfolioManager, bot: TelegramBot):
    try:
        stats = portfolio.get_hourly_stats()
        a = stats["all"]
        wr = (a["wins"] / a["total"] * 100) if a["total"] > 0 else 0
        bot.send_message(
            f"📊 <b>EMA RSI PAPER REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 PnL: {a['pnl_usd']:+.2f}$ ({a['pnl_pct']:+.2f}%)\n"
            f"📈 Trades: {a['total']} | WR: {wr:.1f}%\n"
            f"🎯 TP1: {a['tp1_count']} | TP2: {a['tp2_count']} | SL: {a['sl_count']}\n"
            f"🔓 Open: {stats['open_count']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>SL 5% fixed | TP 10% / 20% | No Breakeven</i>"
        )
    except Exception as exc:
        logger.error(f"Report failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="EMA RSI Reversal Paper Trading")
    parser.add_argument("--top", type=int, default=300)
    parser.add_argument("--reset", action="store_true", help="Clear all trade history before starting")
    parser.add_argument("--oneshot", action="store_true", help="Run one scan cycle then exit")
    args = parser.parse_args()

    if not DATABASE_URL:
        logger.error("DATABASE_URL not set in .env")
        return

    # ── Components ──────────────────────────────────────────────────────
    strategy_1d = EmaRsiReversalStrategy(max_distance_candles=20, use_ema_filter=True, min_ema_rsi=40.0)
    strategy_1h = EmaRsiReversalStrategy(max_distance_candles=3, min_gap=3.0, min_ema_rsi=50.0)

    bot = TelegramBot()
    scheduler = DataScheduler(DATABASE_URL)
    crawler = BybitCrawler(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    scheduler.add_exchange(crawler)

    mtf = MTFEmaRsiStrategy(strategy_1d, strategy_1h, scheduler.db)

    # ── Symbols ─────────────────────────────────────────────────────────
    logger.info(f"Fetching Top {args.top} coins…")
    all_symbols = get_top_coins(limit=args.top)
    symbols = filter_bybit_symbols(crawler, all_symbols)
    logger.success(f"Loaded {len(symbols)} symbols")

    # ── Optional reset ───────────────────────────────────────────────────
    if args.reset:
        from sqlalchemy import create_engine, text
        eng = create_engine(DATABASE_URL)
        with eng.begin() as conn:
            conn.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
        logger.warning("Trade history cleared.")
        bot.send_message("🧹 <b>Trade history reset.</b>")

    # ── Engine ───────────────────────────────────────────────────────────
    engine = PaperTradingEngine(
        DATABASE_URL, mtf, symbols,
        exchange="bybit",
        sleep_seconds=0,
        cooldown_minutes=60,
    )

    # ── One-shot mode ────────────────────────────────────────────────────
    if args.oneshot:
        logger.info("One-shot scan…")
        engine._run_cycle()
        logger.success("One-shot complete.")
        return

    # ── Schedule data sync ───────────────────────────────────────────────
    for sym in symbols:
        try:
            scheduler.add_job("bybit", sym, "1h")
        except Exception:
            pass

    # ── Paper trading loop (every minute) ────────────────────────────────
    scheduler.add_custom_job(
        func=engine._run_cycle,
        cron_kwargs={"minute": "*"},
        job_id="ema_rsi_paper_engine",
        name="EMA RSI Paper Engine (1H)",
    )

    # ── Hourly report ────────────────────────────────────────────────────
    scheduler.add_custom_job(
        func=lambda: send_report(engine.portfolio, bot),
        cron_kwargs={"minute": "0"},
        job_id="ema_rsi_paper_report",
        name="EMA RSI Hourly Report",
    )

    # ── Start ────────────────────────────────────────────────────────────
    bot.send_message(
        f"🚀 <b>EMA RSI Paper Trading Started!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Coins: {len(symbols)}\n"
        f"🎯 Timeframe: 1H (filtered by 1D)\n"
        f"🛡️ SL: 5% (fixed – no breakeven move)\n"
        f"💰 TP1: 10% | TP2: 20%\n"
        f"📊 Based on backtest: <b>+710% PnL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    scheduler.start()

    print("\n" + "=" * 60)
    print(f"EMA RSI PAPER TRADING — {len(symbols)} COINS")
    print("Press 'q' to stop safely, or Ctrl+C")
    print("=" * 60 + "\n")

    try:
        while True:
            if os.name == 'nt' and msvcrt.kbhit():
                if msvcrt.getch().lower() == b'q':
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    scheduler.stop()
    bot.send_message(f"🛑 <b>EMA RSI Paper Bot stopped</b> @ {datetime.now().strftime('%d/%m %H:%M')}")
    print("\n✅ Bot stopped. Goodbye!")


if __name__ == "__main__":
    main()

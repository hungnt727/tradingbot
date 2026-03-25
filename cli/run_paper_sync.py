"""
CLI script to run the Paper Trading Engine.

Usage:
    python cli/run_paper_sync.py --strategy SonicRStrategy --symbols "BTC/USDT,ETH/USDT" --timeframe 1h
"""
import os
import importlib
import click
from dotenv import load_dotenv
from loguru import logger

from paper_trading.engine import PaperTradingEngine

load_dotenv()


def load_strategy(class_name: str):
    try:
        if class_name == "SonicRStrategy":
            mod = importlib.import_module("strategies.sonicr_strategy")
            return getattr(mod, class_name)()
            
        module = importlib.import_module("strategies")
        if hasattr(module, class_name):
            return getattr(module, class_name)()
            
        file_name = "".join(["_" + c.lower() if c.isupper() else c for c in class_name]).lstrip("_")
        mod = importlib.import_module(f"strategies.{file_name}")
        return getattr(mod, class_name)()
    except Exception as e:
        logger.error(f"Failed to load strategy '{class_name}': {e}")
        raise ValueError(f"Strategy {class_name} not found.")


@click.command()
@click.option("--strategy", required=True, help="Strategy class name (e.g. SonicRStrategy)")
@click.option("--symbols", required=True, help="Comma-separated trading pairs (e.g. BTC/USDT,ETH/USDT)")
@click.option("--exchange", default="binance", help="Exchange name (e.g. binance, bybit)")
@click.option("--timeframe", default="1h", help="Timeframe (e.g. 1h, 15m)")
@click.option("--sleep", default=60, help="Seconds to sleep between cycles")
def run_paper_sync(strategy: str, symbols: str, exchange: str, timeframe: str, sleep: int):
    """Start the endless paper trading loop."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not found in environment.")
        return

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        logger.error("No valid symbols provided.")
        return

    try:
        strat_obj = load_strategy(strategy)
        strat_obj.timeframe = timeframe  # Override if needed
    except ValueError as e:
        logger.error(e)
        return

    engine = PaperTradingEngine(
        db_url=db_url,
        strategy=strat_obj,
        symbols=sym_list,
        exchange=exchange,
        sleep_seconds=sleep,
    )
    
    engine.run()


if __name__ == "__main__":
    run_paper_sync()

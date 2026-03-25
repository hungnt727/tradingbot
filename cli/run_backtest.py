"""
CLI command to run backtests on historical data.

Usage:
    python cli/run_backtest.py \\
        --strategy SonicRStrategy \\
        --exchange binance \\
        --symbol BTC/USDT \\
        --timeframe 1h \\
        --start 2024-01-01 \\
        --capital 10000 \\
        --fee 0.001
"""
import importlib
import os
from datetime import datetime

import click
from dotenv import load_dotenv
from loguru import logger

from backtest.engine import BacktestEngine
from backtest.report import generate_html_report

load_dotenv()


def load_strategy(class_name: str):
    """Dynamically load strategy class from strategies package."""
    try:
        # Assuming all core strategies are in strategies module
        module = importlib.import_module("strategies")
        if hasattr(module, class_name):
            return getattr(module, class_name)()
            
        # Try finding it in a specific file by snake_casing the name
        file_name = "".join(["_" + c.lower() if c.isupper() else c for c in class_name]).lstrip("_")
        # e.g., SonicRStrategy -> sonic_r_strategy.py -> sonicr_strategy.py
        # Fallback hardcoded for now due to spelling quirks:
        if class_name == "SonicRStrategy":
            file_name = "sonicr_strategy"
            
        try:
            mod = importlib.import_module(f"strategies.{file_name}")
            return getattr(mod, class_name)()
        except (ImportError, AttributeError):
            raise ValueError(f"Strategy {class_name} not found in strategies/")
    except Exception as e:
        logger.error(f"Failed to load strategy '{class_name}': {e}")
        raise


@click.command()
@click.option("--strategy", required=True, help="Strategy class name (e.g. SonicRStrategy)")
@click.option("--exchange", required=True, help="Exchange name (e.g. binance, bybit)")
@click.option("--symbol", required=True, help="Trading pair (e.g. BTC/USDT)")
@click.option("--timeframe", required=True, help="Timeframe (e.g. 1h, 15m)")
@click.option("--start", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end", default=None, help="End date (YYYY-MM-DD). Defaults to now.")
@click.option("--capital", default=10000.0, help="Initial capital in USD")
@click.option("--fee", default=0.001, help="Fee rate (0.001 = 0.1%)")
@click.option("--slippage", default=0.0005, help="Slippage rate (0.0005 = 0.05%)")
@click.option("--htf", default=None, help="Higher timeframe needed by strategy (e.g. 4h)")
@click.option("--report/--no-report", default=True, help="Generate HTML report")
def run_backtest(
    strategy: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    capital: float,
    fee: float,
    slippage: float,
    htf: str,
    report: bool,
):
    """Run a backtest on historical data and optionally generate a report."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not found in environment.")
        return

    try:
        strat_obj = load_strategy(strategy)
    except ValueError as e:
        logger.error(e)
        return

    start_date = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d") if end else datetime.utcnow()

    engine = BacktestEngine(db_url, fee_rate=fee, slippage=slippage)
    
    result = engine.run(
        strategy=strat_obj,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        htf_timeframe=htf,
    )

    if result.trades and report:
        logger.info("Generating HTML teardown report...")
        report_path = generate_html_report(result)
        if report_path:
            click.echo(f"Report generated: file://{os.path.abspath(report_path)}")
    elif not result.trades:
        logger.warning(f"No trades executed for {symbol} on {timeframe}.")


if __name__ == "__main__":
    run_backtest()

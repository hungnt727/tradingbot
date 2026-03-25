"""
HTML Report generator using quantstats.
Creates detailed tear sheets (performance reports) for backtest results.
"""
import os
from pathlib import Path

import pandas as pd
try:
    import quantstats as qs
except ImportError:
    qs = None

from loguru import logger

from backtest.engine import BacktestResult


def generate_html_report(result: BacktestResult, output_dir: str = "output/reports") -> str:
    """
    Generate an HTML tear sheet from BacktestResult using quantstats.

    Args:
        result:     BacktestResult object from engine.py
        output_dir: Directory to save the HTML report.

    Returns:
        Absolute path to the generated HTML file.
    """
    if qs is None:
        logger.error("[Report] quantstats not installed. Cannot generate HTML report.")
        return ""

    if not result.trades:
        logger.warning("[Report] No trades found. Skipping HTML report.")
        return ""

    os.makedirs(output_dir, exist_ok=True)
    
    # Needs to be a Pandas Series of percentage returns with DatetimeIndex
    # We must construct a daily returns series for quantstats to work well
    
    # 1. Create a Series of Pnl % at the exit timestamp
    pnl_series = pd.Series(
        [t.pnl_pct for t in result.trades],
        index=pd.to_datetime([t.exit_time for t in result.trades])
    )
    
    # 2. Resample to daily returns (sum of pnl_pct per day)
    # This is an approximation for quantstats since it expects daily returns
    daily_returns = pnl_series.resample("D").sum().fillna(0)
    
    # Clean timezone if present (quantstats sometimes struggles with tz)
    daily_returns.index = daily_returns.index.tz_localize(None)

    file_name = f"{result.strategy_name}_{result.symbol.replace('/','')}_{result.timeframe}.html"
    file_path = str(Path(output_dir) / file_name)

    title = f"{result.strategy_name} - {result.exchange.capitalize()} {result.symbol} ({result.timeframe})"

    try:
        qs.reports.html(
            returns=daily_returns,
            title=title,
            output=file_path,
            download_filename=file_path,
        )
        logger.success(f"[Report] HTML tear sheet saved to: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"[Report] Failed to generate HTML report: {e}")
        return ""

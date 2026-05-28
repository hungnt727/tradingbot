"""EmaRsiReversal handler — dual-timeframe SHORT-only signal.

Mirrors the original CLI bot's contract: a SHORT fires only when BOTH the last
1D candle and the last 1H candle trigger. The 1D filter is fetched first so a
symbol that doesn't satisfy the daily check short-circuits before we touch the
hourly API.

NOTE: the original CLI hard-coded different per-timeframe constants (1D:
``use_ema_filter=True``, ``min_ema_rsi=40.0``; 1H: ``min_gap=3.0``,
``min_ema_rsi=50.0``). Here those are driven by the user's params instead, and
both timeframes share a single ``min_ema_rsi`` field. To reproduce the proven
+710% config, set ``use_ema_filter=true`` and ``min_gap=3.0``.
"""
from strategies.base_strategy import BaseStrategy
from strategies.ema_rsi_reversal_strategy import EmaRsiReversalStrategy
from worker.data_loader import ensure_data_ready
from worker.strategy_handlers._util import coerce_float as _f

MIN_CANDLES = 200  # EmaRsiReversal needs ~200 for EMA-200
WEEKLY_MIN_CANDLES = 50  # ~1 year of weekly bars — enough for stable EMA-20 of RSI


def build(params: dict) -> tuple[BaseStrategy, BaseStrategy]:
    rsi = int(params.get("rsi_period", 14))
    min_ema = float(params.get("min_ema_rsi", 50.0))
    strat_1d = EmaRsiReversalStrategy(
        rsi_period=rsi,
        max_distance_candles=int(params.get("n1d", 20)),
        use_ema_filter=bool(params.get("use_ema_filter", False)),
        min_ema_rsi=min_ema,
    )
    strat_1h = EmaRsiReversalStrategy(
        rsi_period=rsi,
        max_distance_candles=int(params.get("m1h", 3)),
        min_gap=float(params.get("min_gap", 0.0)),
        min_ema_rsi=min_ema,
    )
    return strat_1d, strat_1h


def _weekly_filter_passes(strat, exchange: str, symbol: str) -> bool | None:
    """Check that the latest 1W candle has ema_rsi_5 < ema_rsi_10 < ema_rsi_20.

    Returns ``True`` if the weekly EMA-RSI is ordered descending (filter passes),
    ``False`` if not (filter blocks), or ``None`` if 1W data is unavailable /
    insufficient (treat as blocked — better to miss a signal than fire blind).
    """
    df_1w = ensure_data_ready(exchange, symbol, "1w", min_required=WEEKLY_MIN_CANDLES)
    if df_1w is None or len(df_1w) < WEEKLY_MIN_CANDLES:
        return None
    w = strat.compute_indicators(df_1w)
    last = w.iloc[-1]
    # NaN comparisons evaluate to False — safe (we'd block if EMAs aren't computed).
    return bool(last["ema_rsi_5"] < last["ema_rsi_10"] < last["ema_rsi_20"])


def scan(strat_high, strat_low, exchange: str, symbol: str, params: dict) -> dict | None:
    """Return a SHORT signal dict if 1W filter (optional) + 1D + 1H all fire; else None."""
    lookback = int(params.get("lookback", 250))

    # 1W filter — short-circuits before touching 1D/1H APIs to save calls.
    if bool(params.get("use_weekly_filter", True)):
        passed = _weekly_filter_passes(strat_high, exchange, symbol)
        if not passed:
            return None

    df_1d = ensure_data_ready(exchange, symbol, "1d", min_required=lookback)
    if df_1d is None or len(df_1d) < MIN_CANDLES:
        return None
    d1 = strat_high.generate_signals(strat_high.compute_indicators(df_1d))
    if int(d1.iloc[-1]["signal"]) != -1:
        return None

    df_1h = ensure_data_ready(exchange, symbol, "1h", min_required=lookback)
    if df_1h is None or len(df_1h) < MIN_CANDLES:
        return None
    h1 = strat_low.generate_signals(strat_low.compute_indicators(df_1h))
    last_h = h1.iloc[-1]
    if int(last_h["signal"]) != -1:
        return None

    last_d = d1.iloc[-1]
    return {
        "symbol": symbol,
        "signal_type": "SHORT",
        "timestamp_candle": h1.index[-1].to_pydatetime(),
        "close": _f(last_h["close"]),
        "indicators": {
            "close": _f(last_h["close"]),
            "rsi": _f(last_h["rsi"]),
            "ema_rsi_5": _f(last_h["ema_rsi_5"]),
            "ema_rsi_10": _f(last_h["ema_rsi_10"]),
            "ema_rsi_20": _f(last_h["ema_rsi_20"]),
            "atr": _f(last_h.get("atr")),
            "bars_since_reversal_1h": _f(last_h["bars_since_reversal"]),
            "bars_since_reversal_1d": _f(last_d["bars_since_reversal"]),
            "ema_rsi_5_1d": _f(last_d["ema_rsi_5"]),
            "ema_rsi_10_1d": _f(last_d["ema_rsi_10"]),
            "ema_rsi_20_1d": _f(last_d["ema_rsi_20"]),
            "weekly_filter": bool(params.get("use_weekly_filter", True)),
        },
    }


def format_alert(sig: dict, cfg, username: str) -> str:
    p = cfg.params
    close = sig["close"] or 0.0
    sl_pct, tp1_pct, tp2_pct = p.get("sl_pct", 0.05), p.get("tp1_pct", 0.10), p.get("tp2_pct", 0.20)
    # SHORT: stop above entry, targets below.
    sl, tp1, tp2 = close * (1 + sl_pct), close * (1 - tp1_pct), close * (1 - tp2_pct)
    ind = sig["indicators"]
    return (
        f"🚨 {sig['signal_type']} signal — {sig['symbol']} ({cfg.exchange})\n"
        f"TF: 1H | Time: {sig['timestamp_candle']:%Y-%m-%d %H:%M} UTC\n\n"
        f"RSI: {ind.get('rsi') or 0:.1f} | EMA RSI 20: {ind.get('ema_rsi_20') or 0:.1f}\n"
        f"Entry: ${close:.6g}\n"
        f"SL:    ${sl:.6g}  ({sl_pct*100:.0f}%)\n"
        f"TP1:   ${tp1:.6g}  ({tp1_pct*100:.0f}%)\n"
        f"TP2:   ${tp2:.6g}  ({tp2_pct*100:.0f}%)\n\n"
        f"Reason: 1D bars={ind.get('bars_since_reversal_1d')}, "
        f"1H bars={ind.get('bars_since_reversal_1h')}"
        f"{' (1W filter ✓)' if ind.get('weekly_filter') else ''}\n"
        f'Process: "{cfg.name}" by {username}'
    )

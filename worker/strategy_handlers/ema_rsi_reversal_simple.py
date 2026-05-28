"""EmaRsiReversalSimple handler — triple-timeframe SHORT signal.

Fires SHORT when **all** of these hold:

  - 1W [-1]: descending order (``ema_rsi_5 < ema_rsi_10 < ema_rsi_20``) **AND**
             ``bars_since_not_desc < max_distance``
  - 1D [-1]: same pattern + freshness check
  - 1H [-1]: same pattern + freshness check **AND** ``ema_rsi_5 > min_ema_rsi_5``
             (level guard — only at the signal candle)

Fetch order is 1W → 1D → 1H so we short-circuit before paying for lower-TF API
calls when a higher TF already rules out the symbol.
"""
from strategies.base_strategy import BaseStrategy
from strategies.ema_rsi_reversal_simple_strategy import EmaRsiReversalSimpleStrategy
from worker.data_loader import ensure_data_ready
from worker.strategy_handlers._util import coerce_float as _f

MIN_CANDLES = 30          # enough for EMA-20 of RSI + bars_since_not_desc lookback
WEEKLY_MIN_CANDLES = 30   # ~7 months of weekly data — practical floor for newer coins


def build(params: dict) -> tuple[BaseStrategy, BaseStrategy]:
    """One strategy instance is enough — the same indicator/signal logic runs
    on all 3 timeframes. We return it twice to satisfy the handler protocol."""
    s = EmaRsiReversalSimpleStrategy(
        rsi_period=int(params.get("rsi_period", 14)),
        max_distance=int(params.get("max_distance", 10)),
        min_ema_rsi_5=float(params.get("min_ema_rsi_5", 40.0)),
    )
    return s, s


def _pattern_fires(strat, df) -> tuple[bool, dict | None]:
    """Run compute_indicators + signal check on the latest candle of ``df``.

    Returns ``(fires, last_row_dict)``. ``last_row_dict`` is the indicators
    snapshot dict the caller can stash into the signal payload.
    """
    if df is None or len(df) < MIN_CANDLES:
        return False, None
    scored = strat.generate_signals(strat.compute_indicators(df))
    last = scored.iloc[-1]
    fires = int(last["signal"]) == -1
    snap = {
        "ema_rsi_5": _f(last["ema_rsi_5"]),
        "ema_rsi_10": _f(last["ema_rsi_10"]),
        "ema_rsi_20": _f(last["ema_rsi_20"]),
        "bars_since_not_desc": _f(last["bars_since_not_desc"]),
    }
    return fires, snap


def scan(strat_high, strat_low, exchange: str, symbol: str, params: dict) -> dict | None:
    strat = strat_high  # build() returns the same instance for both slots
    lookback = int(params.get("lookback", 250))
    min_ema_rsi_5 = float(params.get("min_ema_rsi_5", 40.0))

    # 1W — top-of-stack filter
    df_1w = ensure_data_ready(exchange, symbol, "1w", min_required=WEEKLY_MIN_CANDLES)
    fires_w, snap_w = _pattern_fires(strat, df_1w)
    if not fires_w:
        return None

    # 1D — pattern must also fire on daily
    df_1d = ensure_data_ready(exchange, symbol, "1d", min_required=lookback)
    fires_d, snap_d = _pattern_fires(strat, df_1d)
    if not fires_d:
        return None

    # 1H — pattern + level guard on signal candle
    df_1h = ensure_data_ready(exchange, symbol, "1h", min_required=lookback)
    if df_1h is None or len(df_1h) < MIN_CANDLES:
        return None
    h1 = strat.generate_signals(strat.compute_indicators(df_1h))
    last_h = h1.iloc[-1]
    if int(last_h["signal"]) != -1:
        return None
    # Level guard — only here at the entry TF.
    if not (last_h["ema_rsi_5"] > min_ema_rsi_5):
        return None

    return {
        "symbol": symbol,
        "signal_type": "SHORT",
        "timestamp_candle": h1.index[-1].to_pydatetime(),
        "close": _f(last_h["close"]),
        "indicators": {
            "close": _f(last_h["close"]),
            "rsi_1h": _f(last_h["rsi"]),
            "ema_rsi_5_1h": _f(last_h["ema_rsi_5"]),
            "ema_rsi_10_1h": _f(last_h["ema_rsi_10"]),
            "ema_rsi_20_1h": _f(last_h["ema_rsi_20"]),
            "bars_since_not_desc_1h": _f(last_h["bars_since_not_desc"]),
            "ema_rsi_5_1d": (snap_d or {}).get("ema_rsi_5"),
            "ema_rsi_10_1d": (snap_d or {}).get("ema_rsi_10"),
            "ema_rsi_20_1d": (snap_d or {}).get("ema_rsi_20"),
            "bars_since_not_desc_1d": (snap_d or {}).get("bars_since_not_desc"),
            "ema_rsi_5_1w": (snap_w or {}).get("ema_rsi_5"),
            "ema_rsi_10_1w": (snap_w or {}).get("ema_rsi_10"),
            "ema_rsi_20_1w": (snap_w or {}).get("ema_rsi_20"),
            "bars_since_not_desc_1w": (snap_w or {}).get("bars_since_not_desc"),
        },
    }


def format_alert(sig: dict, cfg, username: str) -> str:
    p = cfg.params
    close = sig["close"] or 0.0
    sl_pct, tp1_pct, tp2_pct = p.get("sl_pct", 0.05), p.get("tp1_pct", 0.10), p.get("tp2_pct", 0.20)
    sl, tp1, tp2 = close * (1 + sl_pct), close * (1 - tp1_pct), close * (1 - tp2_pct)
    ind = sig["indicators"]
    return (
        f"🚨 {sig['signal_type']} signal — {sig['symbol']} ({cfg.exchange})\n"
        f"TF: 1H | Time: {sig['timestamp_candle']:%Y-%m-%d %H:%M} UTC\n\n"
        f"EMA-RSI 5/10/20 (1H): "
        f"{ind.get('ema_rsi_5_1h') or 0:.1f} / "
        f"{ind.get('ema_rsi_10_1h') or 0:.1f} / "
        f"{ind.get('ema_rsi_20_1h') or 0:.1f}\n"
        f"Entry: ${close:.6g}\n"
        f"SL:    ${sl:.6g}  ({sl_pct*100:.0f}%)\n"
        f"TP1:   ${tp1:.6g}  ({tp1_pct*100:.0f}%)\n"
        f"TP2:   ${tp2:.6g}  ({tp2_pct*100:.0f}%)\n\n"
        f"Reason: 3 EMA-RSI vừa xếp giảm trên cả 1W ({ind.get('bars_since_not_desc_1w')}), "
        f"1D ({ind.get('bars_since_not_desc_1d')}), 1H ({ind.get('bars_since_not_desc_1h')}) nến\n"
        f'Process: "{cfg.name}" by {username}'
    )

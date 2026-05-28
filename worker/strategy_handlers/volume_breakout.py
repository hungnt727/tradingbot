"""VolumeBreakout handler — dual-timeframe reversal signal.

Reversal semantics: a forced volume + price spike is read as exhaustion, so
the emitted signal goes AGAINST the spike direction.

  1D candle index is ``[-2]`` (last fully-closed daily candle) — per user spec
  "Cây nến dùng để lấy tín hiệu: Cây nến ngay trước cây nến hiện tại".
  1H candle index is ``[-1]`` (current candle).
  Both timeframes must fire in the SAME direction.
"""
from strategies.base_strategy import BaseStrategy
from strategies.volume_breakout_strategy import VolumeBreakoutStrategy
from worker.data_loader import ensure_data_ready
from worker.strategy_handlers._util import coerce_float as _f

MIN_CANDLES = 30  # SMA-10 + index [-2] + buffer


def build(params: dict) -> tuple[BaseStrategy, BaseStrategy]:
    # SMA window is shared across TFs and across vol/price; the per-TF
    # thresholds (vol_mult, price_pct) differ so 1D and 1H can be tuned
    # independently (e.g. require a stricter spike on 1D than on 1H).
    sma_lookback = int(params.get("sma_lookback", 10))
    strat_1d = VolumeBreakoutStrategy(
        vol_mult=float(params.get("vol_mult_1d", 3.0)),
        vol_lookback=sma_lookback,
        price_pct=float(params.get("price_pct_1d", 0.30)),
        price_lookback=sma_lookback,
    )
    strat_1h = VolumeBreakoutStrategy(
        vol_mult=float(params.get("vol_mult_1h", 3.0)),
        vol_lookback=sma_lookback,
        price_pct=float(params.get("price_pct_1h", 0.30)),
        price_lookback=sma_lookback,
    )
    return strat_1d, strat_1h


def scan(strat_high, strat_low, exchange: str, symbol: str, params: dict) -> dict | None:
    lookback = int(params.get("lookback", 50))

    df_1d = ensure_data_ready(exchange, symbol, "1d", min_required=lookback)
    if df_1d is None or len(df_1d) < MIN_CANDLES:
        return None
    d1 = strat_high.generate_signals(strat_high.compute_indicators(df_1d))
    sig_d = int(d1.iloc[-2]["signal"])  # 1D = previous-closed candle
    if sig_d == 0:
        return None

    df_1h = ensure_data_ready(exchange, symbol, "1h", min_required=lookback)
    if df_1h is None or len(df_1h) < MIN_CANDLES:
        return None
    h1 = strat_low.generate_signals(strat_low.compute_indicators(df_1h))
    sig_h = int(h1.iloc[-1]["signal"])  # 1H = current candle
    if sig_h == 0 or sig_h != sig_d:    # both TFs must agree on direction
        return None

    last_h, last_d = h1.iloc[-1], d1.iloc[-2]
    return {
        "symbol": symbol,
        "signal_type": "LONG" if sig_h == 1 else "SHORT",
        "timestamp_candle": h1.index[-1].to_pydatetime(),
        "close": _f(last_h["close"]),
        "indicators": {
            "close": _f(last_h["close"]),
            "vol_ratio_1h": _f(last_h["vol_ratio"]),
            "price_ratio_1h": _f(last_h["price_ratio"]),
            "vol_ratio_1d": _f(last_d["vol_ratio"]),
            "price_ratio_1d": _f(last_d["price_ratio"]),
        },
    }


def format_alert(sig: dict, cfg, username: str) -> str:
    p = cfg.params
    close = sig["close"] or 0.0
    sl_pct = p.get("sl_pct", 0.05)
    tp1_pct = p.get("tp1_pct", 0.10)
    tp2_pct = p.get("tp2_pct", 0.20)
    is_long = sig["signal_type"] == "LONG"
    sl = close * ((1 - sl_pct) if is_long else (1 + sl_pct))
    tp1 = close * ((1 + tp1_pct) if is_long else (1 - tp1_pct))
    tp2 = close * ((1 + tp2_pct) if is_long else (1 - tp2_pct))
    ind = sig["indicators"]
    icon = "🟢" if is_long else "🔴"
    return (
        f"{icon} {sig['signal_type']} signal — {sig['symbol']} ({cfg.exchange})\n"
        f"TF: 1H | Time: {sig['timestamp_candle']:%Y-%m-%d %H:%M} UTC\n\n"
        f"Vol×: 1H {ind.get('vol_ratio_1h') or 0:.2f}, 1D {ind.get('vol_ratio_1d') or 0:.2f}\n"
        f"Price×: 1H {ind.get('price_ratio_1h') or 0:.3f}, 1D {ind.get('price_ratio_1d') or 0:.3f}\n"
        f"Entry: ${close:.6g}\n"
        f"SL:    ${sl:.6g}  ({sl_pct*100:.0f}%)\n"
        f"TP1:   ${tp1:.6g}  ({tp1_pct*100:.0f}%)\n"
        f"TP2:   ${tp2:.6g}  ({tp2_pct*100:.0f}%)\n\n"
        f"Reason: bùng vol → kỳ vọng đảo chiều (1D & 1H xác nhận)\n"
        f'Process: "{cfg.name}" by {username}'
    )

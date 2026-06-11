"""Strategy parameter schemas + multi-strategy registry.

Each strategy is described by a :class:`StrategyDescriptor`: its Pydantic params
model, basic/advanced field groups (drive the two-tier form), the two
timeframes it confirms across, a display label, and the dotted path to its
worker handler module (which exposes ``build`` / ``scan`` / ``format_alert``).

Adding a strategy = (1) a new Pydantic params model below, (2) an entry in
:data:`STRATEGY_REGISTRY`, (3) a strategy class under ``strategies/``, and (4) a
handler module under ``worker/strategy_handlers/``. The worker dispatches by
``strategy_name``; the form re-renders fields from the descriptor.
"""
from dataclasses import dataclass

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Per-strategy Pydantic params                                               #
# --------------------------------------------------------------------------- #

class EmaRsiReversalParams(BaseModel):
    # --- Basic ---
    rsi_period: int = Field(14, ge=2, le=100, description="RSI period")
    max_distance_candles: int = Field(
        20, ge=1, le=200, description="Max bars since 1H reversal candle"
    )
    min_gap: float = Field(0.0, ge=0.0, le=100.0, description="Min EMA-RSI gap threshold (1H)")
    use_ema_filter: bool = Field(False, description="Enable EMA-200 trend filter (1D)")
    use_weekly_filter: bool = Field(
        True,
        description="Bộ lọc 1W: chỉ fire khi nến tuần mới nhất có ema_rsi_5 < ema_rsi_10 và ema_rsi_5 < ema_rsi_20",
    )
    min_ema_rsi: float = Field(50.0, ge=0.0, le=100.0, description="ema_rsi_20 threshold")
    telegram_on_no_signal: bool = Field(
        True,
        description="Gửi Telegram cả khi không có tín hiệu (ON: luôn gửi, OFF: chỉ gửi khi có tín hiệu)",
    )

    # --- Advanced ---
    sl_pct: float = Field(0.05, ge=0.001, le=1.0, description="Stop loss % (display only in Telegram)")
    tp1_pct: float = Field(0.10, ge=0.001, le=2.0, description="Take profit 1 %")
    tp2_pct: float = Field(0.20, ge=0.001, le=2.0, description="Take profit 2 %")
    lookback: int = Field(250, ge=200, le=2000, description="Candles to load for indicators")
    n1d: int = Field(20, ge=1, le=100, description="Max bars since 1D reversal")
    m1h: int = Field(3, ge=1, le=20, description="Max bars since 1H reversal")


class EmaRsiReversalSimpleParams(BaseModel):
    # --- Basic ---
    rsi_period: int = Field(14, ge=2, le=100, description="RSI period")
    max_distance: int = Field(
        10, ge=1, le=200,
        description="Số nến tối đa kể từ lần gần nhất pattern bị phá vỡ (3 EMA-RSI mới sắp xếp)",
    )
    min_ema_rsi_5: float = Field(
        40.0, ge=0.0, le=100.0,
        description="Ngưỡng tối thiểu ema_rsi_5 trên nến 1H (tránh fire khi RSI đã quá thấp)",
    )
    telegram_on_no_signal: bool = Field(
        True,
        description="Gửi Telegram cả khi không có tín hiệu (ON: luôn gửi, OFF: chỉ gửi khi có tín hiệu)",
    )

    # --- Advanced ---
    sl_pct: float = Field(0.05, ge=0.001, le=1.0, description="Stop loss % (display Telegram)")
    tp1_pct: float = Field(0.10, ge=0.001, le=2.0, description="Take profit 1 %")
    tp2_pct: float = Field(0.20, ge=0.001, le=2.0, description="Take profit 2 %")
    lookback: int = Field(250, ge=100, le=2000, description="Số nến fetch cho 1H/1D (1W dùng 60)")


class VolumeBreakoutParams(BaseModel):
    # --- Basic ---
    sma_lookback: int = Field(
        10, ge=2, le=200,
        description="Số nến tính SMA (dùng chung cho vol & price, cả 1D & 1H)",
    )
    vol_mult_1d: float = Field(
        3.0, ge=1.0, le=100.0, description="Ngưỡng vol 1D (× SMA)",
    )
    vol_mult_1h: float = Field(
        3.0, ge=1.0, le=100.0, description="Ngưỡng vol 1H (× SMA)",
    )
    price_pct_1d: float = Field(
        0.30, ge=0.01, le=5.0,
        description="Ngưỡng giá 1D so SMA close (0.30 = 30%)",
    )
    price_pct_1h: float = Field(
        0.30, ge=0.01, le=5.0,
        description="Ngưỡng giá 1H so SMA close (0.30 = 30%)",
    )
    telegram_on_no_signal: bool = Field(
        True,
        description="Gửi Telegram cả khi không có tín hiệu (ON: luôn gửi, OFF: chỉ gửi khi có tín hiệu)",
    )

    # --- Advanced ---
    sl_pct: float = Field(0.05, ge=0.001, le=1.0, description="Stop loss % (display Telegram)")
    tp1_pct: float = Field(0.10, ge=0.001, le=2.0, description="Take profit 1 %")
    tp2_pct: float = Field(0.20, ge=0.001, le=2.0, description="Take profit 2 %")
    lookback: int = Field(50, ge=30, le=2000, description="Số nến fetch cho mỗi TF")


# --------------------------------------------------------------------------- #
#  Strategy descriptor + registry                                             #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StrategyDescriptor:
    params_model: type[BaseModel]
    basic_fields: tuple[str, ...]
    advanced_fields: tuple[str, ...]
    tf_high: str           # higher-timeframe filter, e.g. "1d"
    tf_low: str            # lower-timeframe signal, e.g. "1h"
    label: str             # human-readable name for the form dropdown
    handler_module: str    # dotted path to worker.strategy_handlers.<name>


STRATEGY_REGISTRY: dict[str, StrategyDescriptor] = {
    "EmaRsiReversal": StrategyDescriptor(
        params_model=EmaRsiReversalParams,
        basic_fields=(
            "rsi_period", "max_distance_candles", "min_gap",
            "use_ema_filter", "use_weekly_filter", "min_ema_rsi",
            "telegram_on_no_signal",
        ),
        advanced_fields=("sl_pct", "tp1_pct", "tp2_pct", "lookback", "n1d", "m1h"),
        tf_high="1d",
        tf_low="1h",
        label="EMA-RSI Reversal (1D+1H)",
        handler_module="worker.strategy_handlers.ema_rsi_reversal",
    ),
    "EmaRsiReversalSimple": StrategyDescriptor(
        params_model=EmaRsiReversalSimpleParams,
        basic_fields=("rsi_period", "max_distance", "min_ema_rsi_5", "telegram_on_no_signal"),
        advanced_fields=("sl_pct", "tp1_pct", "tp2_pct", "lookback"),
        tf_high="1w",
        tf_low="1h",
        label="EMA-RSI Reversal Simple (1W+1D+1H)",
        handler_module="worker.strategy_handlers.ema_rsi_reversal_simple",
    ),
    "VolumeBreakout": StrategyDescriptor(
        params_model=VolumeBreakoutParams,
        basic_fields=(
            "sma_lookback",
            "vol_mult_1d", "vol_mult_1h",
            "price_pct_1d", "price_pct_1h",
            "telegram_on_no_signal",
        ),
        advanced_fields=("sl_pct", "tp1_pct", "tp2_pct", "lookback"),
        tf_high="1d",
        tf_low="1h",
        label="Volume Breakout — đảo chiều (1D+1H)",
        handler_module="worker.strategy_handlers.volume_breakout",
    ),
}


def field_specs(schema: type[BaseModel]) -> dict[str, dict]:
    """Return ``{field_name: {default, description, ge, le, is_bool, is_int}}`` for templates."""
    out: dict[str, dict] = {}
    for name, field in schema.model_fields.items():
        ge = le = None
        for meta in field.metadata:
            ge = getattr(meta, "ge", ge)
            le = getattr(meta, "le", le)
        out[name] = {
            "default": field.default,
            "description": field.description or "",
            "ge": ge,
            "le": le,
            "is_bool": field.annotation is bool,
            "is_int": field.annotation is int,
        }
    return out

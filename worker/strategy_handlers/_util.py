"""Shared helpers for strategy handlers."""
import pandas as pd


def coerce_float(value) -> float | None:
    """Coerce to float; map NaN/None to None so JSON snapshots stay safe."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f

"""Per-strategy handlers (build / scan / format_alert).

Each module here implements the worker contract for one strategy registered in
:data:`web.schemas.strategy_params.STRATEGY_REGISTRY`. The runner dispatches
purely by ``strategy_name`` — adding a strategy never touches the runner.
"""

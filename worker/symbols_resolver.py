"""Symbol resolution for the worker (Phase 6 slice 0007).

Dispatches ``symbols_mode`` to a concrete symbol list:
  - ``list``  → the stored list, as-is.
  - ``top_n`` → CoinMarketCap top-N (Redis-cached via ``cmc_service``).
"""
from web.services import cmc_service


def resolve_symbols(exchange: str, mode: str, value: dict, *, redis_conn=None) -> list[str]:
    if mode == "list":
        return list(value.get("list", []))
    if mode == "top_n":
        return cmc_service.fetch_top_n(exchange, int(value["top_n"]), redis_conn=redis_conn)
    raise ValueError(f"Unknown symbols mode '{mode}'")

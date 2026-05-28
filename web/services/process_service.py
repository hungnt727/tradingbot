"""Process CRUD service (Phase 6 slice 0005).

Authorization lives here, not in the routes: every read/write is gated by
``owner_user_id == user.id`` (or ``user.is_admin``). Unauthorized access raises
``ProcessNotFound`` (404, not 403) so we never leak that a process exists.

Strategy params are validated against the registered Pydantic schema; symbols
are validated per mode (slice 0005 supports ``list`` only — ``top_n`` is wired
in slice 0007).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from pydantic import ValidationError as PydanticValidationError

from app_db.models.process import Process
from app_db.models.user import User
from web.schemas.strategy_params import STRATEGY_REGISTRY

MIN_INTERVAL_MINUTES = 5
VALID_EXCHANGES = ("binance", "bybit")


class ProcessNotFound(Exception):
    """Raised when a process is missing or the user may not access it."""


class ProcessValidationError(Exception):
    """Raised for invalid process input (bad params, interval, symbols, chat_id)."""


def _authorize(process: Process | None, user) -> Process:
    if process is None or (process.owner_user_id != user.id and not user.is_admin):
        raise ProcessNotFound("Process not found.")
    return process


def validate_params(strategy_name: str, raw: dict) -> dict:
    """Validate raw strategy params against the registered schema; return clean dict."""
    descriptor = STRATEGY_REGISTRY.get(strategy_name)
    if descriptor is None:
        raise ProcessValidationError(f"Unknown strategy '{strategy_name}'.")
    try:
        model = descriptor.params_model(**raw)
    except PydanticValidationError as exc:
        raise ProcessValidationError(_format_pydantic(exc)) from exc
    return model.model_dump()


MAX_TOP_N = 500


def validate_symbols(mode: str, raw_list: list[str] | None, top_n: int | None) -> dict:
    """Build + validate ``symbols_value`` for the given mode (``list`` or ``top_n``)."""
    if mode == "list":
        cleaned = [s.strip().upper() for s in (raw_list or []) if s.strip()]
        if not cleaned:
            raise ProcessValidationError("Provide at least one symbol (e.g. BTC/USDT).")
        return {"list": cleaned}
    if mode == "top_n":
        if not top_n or top_n < 1 or top_n > MAX_TOP_N:
            raise ProcessValidationError(f"Top N must be between 1 and {MAX_TOP_N}.")
        return {"top_n": int(top_n)}
    raise ProcessValidationError(f"Invalid symbols mode '{mode}'.")


def _validate_common(exchange: str, interval_minutes: int) -> None:
    if exchange not in VALID_EXCHANGES:
        raise ProcessValidationError(f"Exchange must be one of {VALID_EXCHANGES}.")
    if interval_minutes < MIN_INTERVAL_MINUTES:
        raise ProcessValidationError(f"Interval must be ≥ {MIN_INTERVAL_MINUTES} minutes.")


def create_process(session_factory, owner_user_id: int, data: dict) -> Process:
    _validate_common(data["exchange"], data["interval_minutes"])
    with session_factory() as db:
        process = Process(
            owner_user_id=owner_user_id,
            name=data["name"].strip(),
            strategy_name=data["strategy_name"],
            strategy_params=data["strategy_params"],
            exchange=data["exchange"],
            symbols_mode=data["symbols_mode"],
            symbols_value=data["symbols_value"],
            interval_minutes=data["interval_minutes"],
            telegram_chat_id=(data.get("telegram_chat_id") or "").strip() or None,
            is_active=False,
            last_run_status="idle",
        )
        db.add(process)
        db.commit()
        db.refresh(process)
        db.expunge(process)
        return process


def list_processes(session_factory, user) -> list[Process]:
    """Own processes, or all of them when the user is an admin."""
    with session_factory() as db:
        stmt = select(Process).options(joinedload(Process.owner)).order_by(Process.id)
        if not user.is_admin:
            stmt = stmt.where(Process.owner_user_id == user.id)
        rows = list(db.scalars(stmt))
        for r in rows:
            db.expunge(r)
        return rows


def list_all_processes(session_factory) -> list[Process]:
    """Every process, owner eager-loaded — for the admin read-only view."""
    with session_factory() as db:
        rows = list(
            db.scalars(select(Process).options(joinedload(Process.owner)).order_by(Process.id))
        )
        for r in rows:
            db.expunge(r)
        return rows


def get_process(session_factory, process_id: int, user) -> Process:
    with session_factory() as db:
        process = db.get(Process, process_id)
        _authorize(process, user)
        db.expunge(process)
        return process


def update_process(session_factory, process_id: int, data: dict, user) -> Process:
    _validate_common(data["exchange"], data["interval_minutes"])
    with session_factory() as db:
        process = _authorize(db.get(Process, process_id), user)
        # Strategy is fixed at creation — reject any attempt to change it via
        # form/api so existing signals/params stay coherent.
        if data["strategy_name"] != process.strategy_name:
            raise ProcessValidationError("Cannot change strategy of an existing process.")
        process.name = data["name"].strip()
        process.strategy_params = data["strategy_params"]
        process.exchange = data["exchange"]
        process.symbols_mode = data["symbols_mode"]
        process.symbols_value = data["symbols_value"]
        process.interval_minutes = data["interval_minutes"]
        process.telegram_chat_id = (data.get("telegram_chat_id") or "").strip() or None
        db.commit()
        db.refresh(process)
        db.expunge(process)
        return process


def delete_process(session_factory, process_id: int, user) -> None:
    with session_factory() as db:
        process = _authorize(db.get(Process, process_id), user)
        db.delete(process)
        db.commit()


def toggle_active(session_factory, process_id: int, user) -> Process:
    """Flip ``is_active``. Enabling requires a resolvable Telegram chat ID."""
    with session_factory() as db:
        process = _authorize(db.get(Process, process_id), user)
        if not process.is_active:
            owner = db.get(User, process.owner_user_id)
            chat = process.telegram_chat_id or (owner.default_telegram_chat_id if owner else None)
            if not chat:
                raise ProcessValidationError(
                    "Set a Telegram chat ID (process or profile default) before starting."
                )
            process.is_active = True
            process.last_run_status = process.last_run_status or "idle"
        else:
            process.is_active = False
        db.commit()
        db.refresh(process)
        db.expunge(process)
        return process


def request_force_run(session_factory, process_id: int, user) -> Process:
    """Flag a one-shot "scan now". The worker picks it up next cycle and clears it.

    Allowed on inactive processes too (the feature is for test scans).
    """
    with session_factory() as db:
        process = _authorize(db.get(Process, process_id), user)
        process.force_run_requested_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(process)
        db.expunge(process)
        return process


def _format_pydantic(exc: PydanticValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)

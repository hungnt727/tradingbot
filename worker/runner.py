"""Worker orchestrator: run one process' scan cycle (Phase 6 slice 0006).

``run_one_process`` is the deepest module in the worker. It:
  1. marks the process ``running`` (clears the force-run flag),
  2. snapshots its config + looks up the strategy descriptor + handler,
  3. resolves symbols, asks the handler to scan each one,
  4. dedupe-inserts each signal (UNIQUE constraint → no double alert),
  5. re-checks the process is still active, then sends the Telegram alert,
  6. records final status (``OK`` / ``OK (telegram error: ...)`` / ``error: ...``).

Strategy-specific behaviour lives in ``worker.strategy_handlers.<name>``: each
handler exports ``build(params)``, ``scan(strat_high, strat_low, exchange,
symbol, params)`` and ``format_alert(sig, cfg, username)``. The runner itself
is strategy-agnostic — adding a strategy never touches this file.
"""
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.exc import IntegrityError

from app_db.models.process import Process
from app_db.models.signal import Signal
from app_db.models.user import User
from web.schemas.strategy_params import STRATEGY_REGISTRY
from web.services.telegram_service import send_message
from worker.symbols_resolver import resolve_symbols


@dataclass
class RunResult:
    process_id: int
    status: str
    signals_found: int = 0
    signals_inserted: int = 0
    telegram_sent: int = 0
    telegram_failed: int = 0
    error: str | None = None


@dataclass
class _Cfg:
    exchange: str
    symbols_mode: str
    symbols_value: dict
    params: dict
    telegram_chat_id: str | None
    name: str
    owner_default_chat: str | None
    owner_username: str
    strategy_name: str
    interval_minutes: int = 60
    is_force_run: bool = False  # True when this cycle was triggered by "Quét ngay"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _insert_signal_dedup(db, process_id: int, exchange: str, timeframe: str, sig: dict) -> Signal | None:
    """Insert a signal; return it, or None if it duplicates an existing candle.

    Uses a SAVEPOINT so a unique-constraint hit doesn't poison the outer txn.
    """
    signal = Signal(
        process_id=process_id,
        exchange=exchange,
        symbol=sig["symbol"],
        timeframe=timeframe,
        timestamp_candle=sig["timestamp_candle"],
        signal_type=sig["signal_type"],
        indicators_snapshot=sig["indicators"],
    )
    try:
        with db.begin_nested():
            db.add(signal)
            db.flush()
    except IntegrityError:
        return None
    return signal


def _finish(session_factory, process_id: int, status: str) -> None:
    with session_factory() as db:
        p = db.get(Process, process_id)
        if p is not None:
            p.last_run_at = _utcnow()
            p.last_run_status = status
            p.last_run_started_at = None
            db.commit()


def _format_force_run_completion(cfg: _Cfg, result: "RunResult") -> str:
    if result.error:
        return f"❌ Quét thất bại — {cfg.name}\nLỗi: {result.error[:300]}"
    if result.signals_inserted:
        return (
            f"✅ Quét xong — {cfg.name}\n"
            f"Tín hiệu mới: {result.signals_inserted}"
            f" (gửi Telegram: {result.telegram_sent}, lỗi: {result.telegram_failed})"
        )
    return f"✅ Quét xong — {cfg.name}\nTín hiệu mới: 0"


def _send_run_completion(cfg: _Cfg, result: "RunResult") -> None:
    """Best-effort completion ping for ALL runs (force-run + scheduled).

    Skipped silently when no chat is configured; failure logged but never
    poisons the run status. Always logs ok/skip/fail so operators can audit.
    """
    send_on_no_signal = cfg.params.get("telegram_on_no_signal", True)
    if not send_on_no_signal and not result.error and result.signals_inserted == 0:
        logger.info(
            f"[runner] completion telegram SKIPPED for '{cfg.name}': "
            f"no signals found/inserted and telegram_on_no_signal is False"
        )
        return

    chat = cfg.telegram_chat_id or cfg.owner_default_chat
    if not chat:
        logger.warning(f"[runner] completion telegram SKIPPED for '{cfg.name}': no chat configured")
        return
    try:
        ok, err = send_message(chat, _format_force_run_completion(cfg, result))
        if ok:
            logger.info(f"[runner] completion telegram sent for '{cfg.name}' -> {chat}")
        else:
            logger.warning(f"[runner] completion telegram FAILED for '{cfg.name}' -> {chat}: {err}")
    except Exception:  # noqa: BLE001
        logger.exception(f"[runner] completion telegram CRASHED for '{cfg.name}' -> {chat}")


def run_one_process(session_factory, process_id: int) -> RunResult:
    # --- Phase 1: mark running + snapshot config (so later edits don't race) ---
    with session_factory() as db:
        p = db.get(Process, process_id)
        if p is None:
            return RunResult(process_id, "missing")
        p.last_run_status = "running"
        p.last_run_started_at = _utcnow()
        is_force_run = p.force_run_requested_at is not None  # capture before clear
        p.force_run_requested_at = None
        owner = db.get(User, p.owner_user_id)
        cfg = _Cfg(
            exchange=p.exchange,
            symbols_mode=p.symbols_mode,
            symbols_value=dict(p.symbols_value),
            params=dict(p.strategy_params),
            telegram_chat_id=p.telegram_chat_id,
            name=p.name,
            owner_default_chat=owner.default_telegram_chat_id if owner else None,
            owner_username=owner.username if owner else "?",
            strategy_name=p.strategy_name,
            interval_minutes=p.interval_minutes,
            is_force_run=is_force_run,
        )
        db.commit()

    result = RunResult(process_id, "OK")
    try:
        descriptor = STRATEGY_REGISTRY.get(cfg.strategy_name)
        if descriptor is None:
            raise ValueError(f"Unknown strategy '{cfg.strategy_name}'.")
        handler = importlib.import_module(descriptor.handler_module)

        symbols = resolve_symbols(cfg.exchange, cfg.symbols_mode, cfg.symbols_value)
        strat_high, strat_low = handler.build(cfg.params)
        found = [s for s in (handler.scan(strat_high, strat_low, cfg.exchange, sym, cfg.params)
                             for sym in symbols) if s]
        result.signals_found = len(found)

        telegram_errors: list[str] = []
        with session_factory() as db:
            proc = db.get(Process, process_id)
            if proc is None:  # deleted mid-run → nothing to insert, no alert
                return RunResult(process_id, "missing", signals_found=len(found))
            for sig in found:
                inserted = _insert_signal_dedup(
                    db, process_id, cfg.exchange, descriptor.tf_low, sig
                )
                if inserted is None:
                    continue
                result.signals_inserted += 1
                db.refresh(proc)
                # Skip per-signal alert when the process isn't active AND this
                # wasn't a "Quét ngay" run — i.e. Stop quiets the scheduler
                # noise, but explicit force-run requests always get their
                # alerts. ``is_force_run`` was captured in Phase 1 before the
                # flag was cleared.
                if not proc.is_active and not cfg.is_force_run:
                    continue
                chat_id = cfg.telegram_chat_id or cfg.owner_default_chat
                ok, err = send_message(chat_id, handler.format_alert(sig, cfg, cfg.owner_username))
                inserted.telegram_sent = ok
                inserted.telegram_sent_at = _utcnow() if ok else None
                inserted.telegram_error = None if ok else err
                if ok:
                    result.telegram_sent += 1
                else:
                    result.telegram_failed += 1
                    telegram_errors.append(err or "unknown")
            db.commit()

        status = "OK" if not telegram_errors else f"OK (telegram error: {telegram_errors[0][:200]})"
        _finish(session_factory, process_id, status)
        result.status = status
        _send_run_completion(cfg, result)
        return result

    except Exception as exc:  # noqa: BLE001 — any failure becomes process status, never crashes loop
        logger.exception(f"[runner] process {process_id} failed")
        status = f"error: {str(exc)[:480]}"
        _finish(session_factory, process_id, status)
        result.status = status
        result.error = str(exc)
        _send_run_completion(cfg, result)
        return result

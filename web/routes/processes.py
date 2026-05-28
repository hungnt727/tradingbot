"""Process CRUD routes (Phase 6 slice 0005).

Thin handlers: parse the form, delegate to ``process_service`` (which owns
authz + validation), redirect on success or re-render the form with the error
and the submitted values preserved.

Multi-strategy: the form's strategy dropdown is active on the create page
(GET /processes/new?strategy=<name> re-renders fresh fields). On the edit page
the strategy is locked — the route ignores any ``strategy_name`` posted by the
client and forces it from the DB before delegating to the service.
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.deps import get_session_factory, require_user
from web.services import process_service
from web.services.telegram_service import send_message
from web.schemas.strategy_params import STRATEGY_REGISTRY, field_specs
from web.templating import templates

router = APIRouter(prefix="/processes", tags=["processes"])

DEFAULT_STRATEGY = "EmaRsiReversal"
DEFAULT_INTERVAL = 60


def _resolve_strategy(strategy_name: str | None) -> str:
    """Fall back to default when the requested strategy isn't registered."""
    if strategy_name and strategy_name in STRATEGY_REGISTRY:
        return strategy_name
    return DEFAULT_STRATEGY


def _specs(strategy_name: str):
    return field_specs(STRATEGY_REGISTRY[strategy_name].params_model)


def _strategy_choices() -> list[tuple[str, str]]:
    return [(key, desc.label) for key, desc in STRATEGY_REGISTRY.items()]


def _default_values(strategy_name: str) -> dict:
    values = {name: spec["default"] for name, spec in _specs(strategy_name).items()}
    values.update(
        name="", exchange="binance", symbols_mode="list", symbols_list="",
        top_n=100, interval_minutes=DEFAULT_INTERVAL, telegram_chat_id="",
        strategy_name=strategy_name,
    )
    return values


def _values_from_process(p) -> dict:
    values = dict(p.strategy_params)
    symbols_list = "\n".join(p.symbols_value.get("list", [])) if p.symbols_mode == "list" else ""
    values.update(
        name=p.name, exchange=p.exchange, symbols_mode=p.symbols_mode,
        symbols_list=symbols_list, top_n=p.symbols_value.get("top_n", 100),
        interval_minutes=p.interval_minutes, telegram_chat_id=p.telegram_chat_id or "",
        strategy_name=p.strategy_name,
    )
    return values


def _values_from_form(form, strategy_name: str) -> dict:
    values = dict(form)
    # checkboxes only appear in the form when ticked
    for name, spec in _specs(strategy_name).items():
        if spec["is_bool"]:
            values[name] = name in form
    values["strategy_name"] = strategy_name
    return values


def _parse(form, strategy_name: str) -> dict:
    """Build a validated process-data dict from raw form fields. Raises ProcessValidationError.

    ``strategy_name`` is determined by the caller (route) — on edit the route
    forces it from the DB; on create the route reads it from the form.
    """
    specs = field_specs(STRATEGY_REGISTRY[strategy_name].params_model)
    raw_params: dict = {}
    for fname, spec in specs.items():
        if spec["is_bool"]:
            raw_params[fname] = fname in form
        elif (form.get(fname) or "") != "":
            raw_params[fname] = form.get(fname)
    params = process_service.validate_params(strategy_name, raw_params)

    name = (form.get("name") or "").strip()
    if not name:
        raise process_service.ProcessValidationError("Name is required.")

    mode = form.get("symbols_mode") or "list"
    raw_list = (form.get("symbols_list") or "").splitlines() if mode == "list" else None
    top_n = None
    if mode == "top_n":
        try:
            top_n = int(form.get("top_n") or 0)
        except ValueError:
            raise process_service.ProcessValidationError("Top-N must be a number.")
    symbols_value = process_service.validate_symbols(mode, raw_list, top_n)

    try:
        interval = int(form.get("interval_minutes") or 0)
    except ValueError:
        raise process_service.ProcessValidationError("Interval must be a number.")

    return {
        "name": name,
        "strategy_name": strategy_name,
        "strategy_params": params,
        "exchange": form.get("exchange") or "",
        "symbols_mode": mode,
        "symbols_value": symbols_value,
        "interval_minutes": interval,
        "telegram_chat_id": form.get("telegram_chat_id") or "",
    }


def _render_form(request, *, values, strategy_name, error=None, process=None, status_code=200):
    descriptor = STRATEGY_REGISTRY[strategy_name]
    return templates.TemplateResponse(
        request,
        "processes/form.html",
        {
            "values": values,
            "error": error,
            "process": process,
            "specs": _specs(strategy_name),
            "basic_fields": list(descriptor.basic_fields),
            "advanced_fields": list(descriptor.advanced_fields),
            "exchanges": process_service.VALID_EXCHANGES,
            "strategy_name": strategy_name,
            "strategy_label": descriptor.label,
            "strategy_choices": _strategy_choices(),
            "lock_strategy": process is not None,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def list_view(request: Request, user=Depends(require_user), sf=Depends(get_session_factory)):
    processes = process_service.list_processes(sf, user)
    return templates.TemplateResponse(
        request, "processes/list.html", {"processes": processes, "is_admin_view": False}
    )


@router.get("/rows", response_class=HTMLResponse)
def list_rows(request: Request, user=Depends(require_user), sf=Depends(get_session_factory)):
    """HTMX polling fragment: just the table rows, for live status badges."""
    processes = process_service.list_processes(sf, user)
    return templates.TemplateResponse(
        request, "processes/_rows.html", {"processes": processes, "is_admin_view": False}
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    strategy: str | None = Query(default=None),
    user=Depends(require_user),
):
    strategy_name = _resolve_strategy(strategy)
    return _render_form(
        request, values=_default_values(strategy_name), strategy_name=strategy_name
    )


@router.post("")
async def create(request: Request, user=Depends(require_user), sf=Depends(get_session_factory)):
    form = await request.form()
    strategy_name = _resolve_strategy(form.get("strategy_name"))
    try:
        data = _parse(form, strategy_name)
        process_service.create_process(sf, user.id, data)
    except process_service.ProcessValidationError as exc:
        return _render_form(
            request,
            values=_values_from_form(form, strategy_name),
            strategy_name=strategy_name,
            error=str(exc),
            status_code=400,
        )
    return RedirectResponse("/processes", status_code=303)


@router.get("/{process_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, process_id: int, user=Depends(require_user), sf=Depends(get_session_factory)):
    try:
        process = process_service.get_process(sf, process_id, user)
    except process_service.ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)
    return _render_form(
        request,
        values=_values_from_process(process),
        strategy_name=process.strategy_name,
        process=process,
    )


@router.post("/{process_id}")
async def update(request: Request, process_id: int, user=Depends(require_user), sf=Depends(get_session_factory)):
    form = await request.form()
    try:
        process = process_service.get_process(sf, process_id, user)
    except process_service.ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)
    # Strategy is locked on edit — force from DB regardless of what the form claims.
    strategy_name = process.strategy_name
    try:
        data = _parse(form, strategy_name)
        process_service.update_process(sf, process_id, data, user)
    except process_service.ProcessValidationError as exc:
        return _render_form(
            request,
            values=_values_from_form(form, strategy_name),
            strategy_name=strategy_name,
            error=str(exc),
            process=process,
            status_code=400,
        )
    return RedirectResponse("/processes", status_code=303)


@router.post("/{process_id}/delete")
def delete(request: Request, process_id: int, user=Depends(require_user), sf=Depends(get_session_factory)):
    try:
        process_service.delete_process(sf, process_id, user)
    except process_service.ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)
    return RedirectResponse("/processes", status_code=303)


@router.post("/{process_id}/force-run", response_class=HTMLResponse)
def force_run(request: Request, process_id: int, user=Depends(require_user), sf=Depends(get_session_factory)):
    """Flag a one-shot scan; the worker runs it next cycle. Returns the rows fragment.

    Also pings Telegram with a "scan requested" message so the user gets immediate
    feedback that their click landed; the worker sends a completion summary when
    the scan finishes (see ``worker.runner._send_force_run_completion``). Skipped
    silently when no chat is configured anywhere — scan still queues.
    """
    try:
        process = process_service.request_force_run(sf, process_id, user)
    except process_service.ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)
    chat = process.telegram_chat_id or user.default_telegram_chat_id
    if chat:
        send_message(
            chat,
            f"🔍 Đã yêu cầu quét — {process.name}\n"
            f"Sàn: {process.exchange}\n"
            f"Worker sẽ chạy trong vài giây...",
        )
    processes = process_service.list_processes(sf, user)
    return templates.TemplateResponse(
        request, "processes/_rows.html", {"processes": processes, "is_admin_view": False}
    )


@router.post("/{process_id}/toggle")
def toggle(request: Request, process_id: int, user=Depends(require_user), sf=Depends(get_session_factory)):
    try:
        process = process_service.toggle_active(sf, process_id, user)
    except process_service.ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)
    except process_service.ProcessValidationError as exc:
        processes = process_service.list_processes(sf, user)
        return templates.TemplateResponse(
            request,
            "processes/list.html",
            {"processes": processes, "is_admin_view": False, "error": str(exc)},
            status_code=400,
        )
    chat = process.telegram_chat_id or user.default_telegram_chat_id
    if chat:
        if process.is_active:
            text = (
                f"▶️ Đã bật — {process.name}\n"
                f"Sàn: {process.exchange}\n"
                f"Worker sẽ quét tự động mỗi {process.interval_minutes} phút."
            )
        else:
            text = f"⏸️ Đã tắt — {process.name}\nWorker đã ngừng quét tự động."
        send_message(chat, text)
    return RedirectResponse("/processes", status_code=303)

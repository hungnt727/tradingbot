"""Signal history routes (Phase 6 slice 0008).

``GET /processes/{id}/signals`` renders the full page, or — when called by HTMX
(filter submit) — just the table fragment. ``.../signals/{sig_id}`` returns the
indicator-snapshot modal fragment.
"""
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from web.deps import get_session_factory, require_user
from web.services import signal_service
from web.services.process_service import ProcessNotFound
from web.templating import templates

router = APIRouter(prefix="/processes", tags=["signals"])


@router.get("/{process_id}/signals", response_class=HTMLResponse)
def signals_page(
    request: Request,
    process_id: int,
    exchange: str = "",
    symbol: str = "",
    signal_type: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    size: int = signal_service.DEFAULT_PAGE_SIZE,
    user=Depends(require_user),
    sf=Depends(get_session_factory),
):
    filters = signal_service.SignalFilters(
        exchange=exchange or None,
        symbol=symbol or None,
        signal_type=signal_type or None,
        date_from=signal_service.parse_date(date_from),
        date_to=signal_service.parse_date(date_to, end_of_day=True),
    )
    try:
        rows, total, page_count = signal_service.list_signals(
            sf, process_id, user, filters=filters, page=page, size=size
        )
    except ProcessNotFound:
        return HTMLResponse("Not found", status_code=404)

    ctx = {
        "process_id": process_id,
        "rows": rows,
        "total": total,
        "page": page,
        "page_count": page_count,
        "size": size,
        "filters": {"exchange": exchange, "symbol": symbol, "signal_type": signal_type,
                    "date_from": date_from, "date_to": date_to},
    }
    # HTMX filter submit → swap only the table; full navigation → whole page.
    template = "signals/_table.html" if request.headers.get("HX-Request") else "signals/list.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/{process_id}/signals/{signal_id}", response_class=HTMLResponse)
def signal_detail(
    request: Request,
    process_id: int,
    signal_id: int,
    user=Depends(require_user),
    sf=Depends(get_session_factory),
):
    try:
        sig = signal_service.get_signal(sf, process_id, signal_id, user)
    except (ProcessNotFound, signal_service.SignalNotFound):
        return HTMLResponse("Not found", status_code=404)
    snapshot = json.dumps(sig.indicators_snapshot, indent=2, sort_keys=True)
    return templates.TemplateResponse(
        request, "signals/detail_modal.html", {"signal": sig, "snapshot": snapshot}
    )

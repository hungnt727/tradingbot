"""User profile / settings routes (Phase 6 slice 0004).

Self-service: every route operates on the *current* user only. The
"Test Telegram" button POSTs via HTMX and swaps in a small toast fragment.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.deps import get_session_factory, require_user
from web.services import telegram_service, user_service
from web.templating import templates

router = APIRouter(prefix="/settings", tags=["settings"])


def _render(request, user, sf, *, message=None, error=None, status_code=200):
    # Re-read the user so the form reflects the latest persisted chat_id.
    fresh = next((u for u in user_service.list_users(sf) if u.id == user.id), user)
    return templates.TemplateResponse(
        request,
        "settings/profile.html",
        {"profile": fresh, "message": message, "error": error},
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, user=Depends(require_user), sf=Depends(get_session_factory)):
    return _render(request, user, sf)


@router.post("/profile")
def update_profile(
    request: Request,
    default_telegram_chat_id: str = Form(""),
    user=Depends(require_user),
    sf=Depends(get_session_factory),
):
    user_service.set_default_chat_id(sf, user.id, default_telegram_chat_id)
    return RedirectResponse("/settings", status_code=303)


@router.post("/test-telegram", response_class=HTMLResponse)
def test_telegram(
    request: Request,
    default_telegram_chat_id: str = Form(""),
    user=Depends(require_user),
):
    target = default_telegram_chat_id.strip() or user.default_telegram_chat_id
    ok, error = telegram_service.send_message(target, "✅ Test message from TradingBot web")
    return templates.TemplateResponse(
        request,
        "settings/_telegram_toast.html",
        {"ok": ok, "error": error},
    )


@router.post("/password", response_class=HTMLResponse)
def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    user=Depends(require_user),
    sf=Depends(get_session_factory),
):
    if user_service.change_password(sf, user.id, old_password, new_password):
        return _render(request, user, sf, message="Password updated.")
    return _render(request, user, sf, error="Current password is incorrect.", status_code=400)

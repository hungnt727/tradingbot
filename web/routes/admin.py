"""Admin user management routes (Phase 6 slice 0003).

All routes are gated by ``require_admin``. Mutations follow the
POST-redirect-GET pattern (303 back to the list) so a refresh never re-submits.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.deps import get_session_factory, require_admin
from web.services import process_service, user_service
from web.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_class=HTMLResponse)
def users_list(request: Request, _admin=Depends(require_admin), sf=Depends(get_session_factory)):
    users = user_service.list_users(sf)
    return templates.TemplateResponse(
        request, "admin/users_list.html", {"users": users, "error": None}
    )


@router.post("/users")
def users_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
    default_telegram_chat_id: str = Form(""),
    admin=Depends(require_admin),
    sf=Depends(get_session_factory),
):
    try:
        user_service.create_user(
            sf, username.strip(), password, is_admin, default_telegram_chat_id.strip() or None
        )
    except user_service.UserExistsError as exc:
        users = user_service.list_users(sf)
        return templates.TemplateResponse(
            request,
            "admin/users_list.html",
            {"users": users, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/reset-password")
def users_reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    admin=Depends(require_admin),
    sf=Depends(get_session_factory),
):
    user_service.reset_password(sf, user_id, new_password)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
def users_delete(
    request: Request,
    user_id: int,
    admin=Depends(require_admin),
    sf=Depends(get_session_factory),
):
    try:
        user_service.delete_user(sf, user_id, acting_user_id=admin.id)
    except user_service.SelfDeleteError as exc:
        users = user_service.list_users(sf)
        return templates.TemplateResponse(
            request,
            "admin/users_list.html",
            {"users": users, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/processes", response_class=HTMLResponse)
def admin_processes(request: Request, _admin=Depends(require_admin), sf=Depends(get_session_factory)):
    """Read-only view of every user's processes (edit/delete disabled in the template)."""
    processes = process_service.list_all_processes(sf)
    return templates.TemplateResponse(
        request, "processes/list.html", {"processes": processes, "is_admin_view": True}
    )

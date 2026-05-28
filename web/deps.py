"""Shared FastAPI dependencies for the Web Control Panel (Phase 6).

``request.state.user`` is populated by the session middleware in ``web.app``.
The session factory is published on ``app.state`` so tests can swap in a
SQLite-backed factory the same way they swap ``app.state.auth_service``.
"""
from fastapi import HTTPException, Request

from app_db.models.user import User


def get_session_factory(request: Request):
    """Return the app DB session factory bound on ``app.state``."""
    return request.app.state.session_factory


class RedirectToLogin(HTTPException):
    """Raised by ``require_user`` for anonymous requests; renders a 307 redirect.

    Starlette's HTTPException handler echoes ``headers``, so the ``Location``
    header turns this into a browser redirect to the login page.
    """

    def __init__(self) -> None:
        super().__init__(status_code=307, detail="Login required", headers={"Location": "/login"})


def require_user(request: Request) -> User:
    """Dependency: the current authenticated user, or redirect to /login."""
    user = request.state.user
    if user is None:
        raise RedirectToLogin()
    return user


def require_admin(request: Request) -> User:
    """Dependency: the current user, requiring ``is_admin``; 403 otherwise."""
    user = require_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

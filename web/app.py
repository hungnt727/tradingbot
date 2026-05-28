import os

import redis
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app_db.session import SessionLocal
from web.routes import admin, processes, settings, signals
from web.services.auth_service import AuthService
from web.templating import templates

COOKIE_NAME = "session_id"


def _make_auth_service() -> AuthService:
    conn = redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    return AuthService(conn, SessionLocal)


app = FastAPI(title="TradingBot Web Control Panel")
app.state.auth_service = _make_auth_service()
app.state.session_factory = SessionLocal

app.include_router(admin.router)
app.include_router(settings.router)
app.include_router(processes.router)
app.include_router(signals.router)


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    sid = request.cookies.get(COOKIE_NAME)
    request.state.user = request.app.state.auth_service.resolve_session(sid) if sid else None
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.state.user is None:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "home.html", {})


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    svc = request.app.state.auth_service
    user = svc.authenticate(username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username or password"},
            status_code=200,
        )
    session_id = svc.create_session(user.id)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, session_id, httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout(request: Request):
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        request.app.state.auth_service.destroy_session(sid)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp

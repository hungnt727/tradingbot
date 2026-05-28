"""Shared fixtures for Phase 6 (Web Control Panel) tests.

Uses in-memory SQLite (StaticPool so all sessions share one connection) and
fakeredis, per slice 0002 test-isolation decision.
"""
import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import datetime, timezone

from app_db.base import Base
from app_db import models  # noqa: F401  (registers models on Base.metadata)
from app_db.models.process import Process
from app_db.models.signal import Signal
from app_db.models.user import User
from web.schemas.strategy_params import EmaRsiReversalParams
from web.services.auth_service import AuthService


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def fake_redis():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def auth_service(fake_redis, session_factory):
    return AuthService(redis_conn=fake_redis, session_factory=session_factory)


@pytest.fixture
def make_user(session_factory):
    def _make(username: str = "alice", password: str = "pw", is_admin: bool = False) -> User:
        with session_factory() as db:
            user = User(
                username=username,
                password_hash=AuthService.hash_password(password),
                is_admin=is_admin,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user

    return _make


@pytest.fixture
def client(auth_service):
    """FastAPI TestClient wired to the fake-backed auth service + sqlite factory.

    Overrides both ``app.state`` slots so routes resolve sessions and run service
    queries against the same in-memory DB the fixtures seed.
    """
    from fastapi.testclient import TestClient

    from web.app import app

    app.state.auth_service = auth_service
    app.state.session_factory = auth_service.session_factory
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def login(client):
    """Log the given user in on the shared client; returns the client."""
    def _login(username: str, password: str = "pw"):
        resp = client.post("/login", data={"username": username, "password": password})
        assert resp.status_code == 302, resp.text
        return client

    return _login


@pytest.fixture
def make_process(session_factory):
    def _make(
        owner_user_id: int,
        name: str = "p1",
        exchange: str = "binance",
        symbols: list[str] | None = None,
        interval_minutes: int = 60,
        telegram_chat_id: str | None = None,
        is_active: bool = False,
        params: dict | None = None,
    ) -> Process:
        with session_factory() as db:
            proc = Process(
                owner_user_id=owner_user_id,
                name=name,
                strategy_name="EmaRsiReversal",
                strategy_params=params or EmaRsiReversalParams().model_dump(),
                exchange=exchange,
                symbols_mode="list",
                symbols_value={"list": symbols or ["BTC/USDT"]},
                interval_minutes=interval_minutes,
                telegram_chat_id=telegram_chat_id,
                is_active=is_active,
                last_run_status="idle",
            )
            db.add(proc)
            db.commit()
            db.refresh(proc)
            db.expunge(proc)
            return proc

    return _make


@pytest.fixture
def make_signal(session_factory):
    def _make(
        process_id: int,
        symbol: str = "BTC/USDT",
        exchange: str = "binance",
        signal_type: str = "SHORT",
        timestamp_candle: datetime | None = None,
        telegram_sent: bool = False,
        telegram_error: str | None = None,
        indicators: dict | None = None,
    ) -> Signal:
        with session_factory() as db:
            sig = Signal(
                process_id=process_id,
                exchange=exchange,
                symbol=symbol,
                timeframe="1h",
                timestamp_candle=timestamp_candle or datetime(2024, 6, 1, 14, 0, tzinfo=timezone.utc),
                signal_type=signal_type,
                indicators_snapshot=indicators or {"rsi": 70.0, "ema_rsi_20": 55.0},
                telegram_sent=telegram_sent,
                telegram_error=telegram_error,
            )
            db.add(sig)
            db.commit()
            db.refresh(sig)
            db.expunge(sig)
            return sig

    return _make

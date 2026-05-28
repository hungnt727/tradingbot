"""Tests for web.services.process_service (Phase 6 slice 0005)."""
import pytest
from types import SimpleNamespace

from app_db.models.process import Process
from web.schemas.strategy_params import EmaRsiReversalParams
from web.services import process_service, user_service


def _u(uid, is_admin=False):
    return SimpleNamespace(id=uid, is_admin=is_admin)


def _data(name="p1", interval=60, symbols=("BTC/USDT",), chat=None):
    return {
        "name": name,
        "strategy_name": "EmaRsiReversal",
        "strategy_params": EmaRsiReversalParams().model_dump(),
        "exchange": "binance",
        "symbols_mode": "list",
        "symbols_value": {"list": list(symbols)},
        "interval_minutes": interval,
        "telegram_chat_id": chat,
    }


class TestValidation:
    def test_params_out_of_bounds_rejected(self):
        with pytest.raises(process_service.ProcessValidationError):
            process_service.validate_params("EmaRsiReversal", {"rsi_period": 1})

    def test_unknown_strategy_rejected(self):
        with pytest.raises(process_service.ProcessValidationError):
            process_service.validate_params("Nope", {})

    def test_symbols_list_cleaned(self):
        assert process_service.validate_symbols("list", ["btc/usdt", " ", "eth/usdt"], None) == {
            "list": ["BTC/USDT", "ETH/USDT"]
        }

    def test_empty_symbols_rejected(self):
        with pytest.raises(process_service.ProcessValidationError):
            process_service.validate_symbols("list", [" "], None)

    def test_top_n_supported(self):
        assert process_service.validate_symbols("top_n", None, 50) == {"top_n": 50}

    def test_top_n_out_of_range_rejected(self):
        with pytest.raises(process_service.ProcessValidationError):
            process_service.validate_symbols("top_n", None, 0)
        with pytest.raises(process_service.ProcessValidationError):
            process_service.validate_symbols("top_n", None, 9999)

    def test_interval_below_minimum_rejected(self, session_factory, make_user):
        owner = make_user(username="o")
        with pytest.raises(process_service.ProcessValidationError):
            process_service.create_process(session_factory, owner.id, _data(interval=3))


class TestOwnership:
    def test_user_cannot_read_others_process(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        other = make_user(username="other")
        proc = make_process(owner.id)
        with pytest.raises(process_service.ProcessNotFound):
            process_service.get_process(session_factory, proc.id, _u(other.id))

    def test_admin_can_read_any_process(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        got = process_service.get_process(session_factory, proc.id, _u(999, is_admin=True))
        assert got.id == proc.id

    def test_list_filters_to_own_for_regular_user(self, session_factory, make_user, make_process):
        a = make_user(username="a")
        b = make_user(username="b")
        make_process(a.id, name="a1")
        make_process(b.id, name="b1")
        names = [p.name for p in process_service.list_processes(session_factory, _u(a.id))]
        assert names == ["a1"]

    def test_admin_list_sees_all(self, session_factory, make_user, make_process):
        a = make_user(username="a")
        b = make_user(username="b")
        make_process(a.id, name="a1")
        make_process(b.id, name="b1")
        names = {p.name for p in process_service.list_processes(session_factory, _u(99, is_admin=True))}
        assert names == {"a1", "b1"}

    def test_update_others_process_rejected(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        other = make_user(username="other")
        proc = make_process(owner.id)
        with pytest.raises(process_service.ProcessNotFound):
            process_service.update_process(session_factory, proc.id, _data(name="x"), _u(other.id))


class TestCrud:
    def test_create_then_list(self, session_factory, make_user):
        owner = make_user(username="owner")
        process_service.create_process(session_factory, owner.id, _data(name="hello"))
        rows = process_service.list_processes(session_factory, _u(owner.id))
        assert len(rows) == 1 and rows[0].name == "hello"
        assert rows[0].is_active is False
        assert rows[0].last_run_status == "idle"

    def test_update_changes_fields(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        proc = make_process(owner.id, name="old")
        process_service.update_process(
            session_factory, proc.id, _data(name="new", symbols=("ETH/USDT",)), _u(owner.id)
        )
        got = process_service.get_process(session_factory, proc.id, _u(owner.id))
        assert got.name == "new"
        assert got.symbols_value == {"list": ["ETH/USDT"]}

    def test_delete_removes(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        process_service.delete_process(session_factory, proc.id, _u(owner.id))
        with session_factory() as db:
            assert db.get(Process, proc.id) is None


class TestToggle:
    def test_cannot_start_without_chat_id(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")  # no default chat id
        proc = make_process(owner.id, telegram_chat_id=None)
        with pytest.raises(process_service.ProcessValidationError):
            process_service.toggle_active(session_factory, proc.id, _u(owner.id))

    def test_start_with_process_chat_id(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        proc = make_process(owner.id, telegram_chat_id="123")
        got = process_service.toggle_active(session_factory, proc.id, _u(owner.id))
        assert got.is_active is True

    def test_start_with_owner_default_chat_id(self, session_factory, make_user, make_process):
        owner = user_service.create_user(
            session_factory, "owner", "pw", default_telegram_chat_id="999"
        )
        proc = make_process(owner.id, telegram_chat_id=None)
        got = process_service.toggle_active(session_factory, proc.id, _u(owner.id))
        assert got.is_active is True

    def test_toggle_off_when_active(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        proc = make_process(owner.id, telegram_chat_id="123", is_active=True)
        got = process_service.toggle_active(session_factory, proc.id, _u(owner.id))
        assert got.is_active is False

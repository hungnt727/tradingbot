"""Tests for web.services.signal_service.list_signals (Phase 6 slice 0008)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from web.services import signal_service
from web.services.process_service import ProcessNotFound


def _u(uid, is_admin=False):
    return SimpleNamespace(id=uid, is_admin=is_admin)


class TestAuthorization:
    def test_non_owner_non_admin_rejected(self, session_factory, make_user, make_process):
        owner = make_user(username="owner")
        other = make_user(username="other")
        proc = make_process(owner.id)
        with pytest.raises(ProcessNotFound):
            signal_service.list_signals(session_factory, proc.id, _u(other.id))

    def test_admin_can_view(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        make_signal(proc.id)
        rows, total, _ = signal_service.list_signals(session_factory, proc.id, _u(99, is_admin=True))
        assert total == 1


class TestFilters:
    def test_filter_by_symbol_and_exchange(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        make_signal(proc.id, symbol="BTC/USDT", exchange="binance")
        make_signal(proc.id, symbol="ETH/USDT", exchange="binance",
                    timestamp_candle=datetime(2024, 6, 1, 15, 0, tzinfo=timezone.utc))
        f = signal_service.SignalFilters(symbol="BTC/USDT", exchange="binance")
        rows, total, _ = signal_service.list_signals(session_factory, proc.id, _u(owner.id), filters=f)
        assert total == 1 and rows[0].symbol == "BTC/USDT"

    def test_filter_by_date_range(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        # detected_at defaults to now(); insert one then filter to an old window → excluded
        make_signal(proc.id)
        f = signal_service.SignalFilters(
            date_from=datetime(2000, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2000, 1, 2, tzinfo=timezone.utc),
        )
        _, total, _ = signal_service.list_signals(session_factory, proc.id, _u(owner.id), filters=f)
        assert total == 0


class TestPagination:
    def test_pages_split_total(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        for i in range(5):
            make_signal(proc.id, symbol=f"C{i}/USDT",
                        timestamp_candle=datetime(2024, 6, 1, i, 0, tzinfo=timezone.utc))
        rows, total, page_count = signal_service.list_signals(
            session_factory, proc.id, _u(owner.id), page=1, size=2
        )
        assert total == 5 and page_count == 3 and len(rows) == 2

    def test_size_capped_and_page_floored(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        make_signal(proc.id)
        rows, total, _ = signal_service.list_signals(
            session_factory, proc.id, _u(owner.id), page=0, size=9999
        )
        assert total == 1  # did not error on out-of-range page/size


class TestGetSignal:
    def test_get_returns_snapshot(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        proc = make_process(owner.id)
        sig = make_signal(proc.id, indicators={"rsi": 71.5})
        got = signal_service.get_signal(session_factory, proc.id, sig.id, _u(owner.id))
        assert got.indicators_snapshot == {"rsi": 71.5}

    def test_get_other_process_signal_rejected(self, session_factory, make_user, make_process, make_signal):
        owner = make_user(username="owner")
        other = make_user(username="other")
        proc = make_process(owner.id)
        sig = make_signal(proc.id)
        with pytest.raises(ProcessNotFound):
            signal_service.get_signal(session_factory, proc.id, sig.id, _u(other.id))


def test_parse_date():
    assert signal_service.parse_date("") is None
    assert signal_service.parse_date("not-a-date") is None
    d = signal_service.parse_date("2026-01-15")
    assert d.year == 2026 and d.hour == 0
    end = signal_service.parse_date("2026-01-15", end_of_day=True)
    assert end.hour == 23

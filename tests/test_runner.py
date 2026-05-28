"""Tests for worker.runner.run_one_process (Phase 6 slice 0006).

The strategy handler's ``scan`` and the runner's ``send_message`` are patched
at the module boundary so we test orchestration (dedupe insert, telegram,
status) without real OHLCV/network. Tests target the EmaRsiReversal handler
because that's the default strategy created by the ``make_process`` fixture.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app_db.models.process import Process
from app_db.models.signal import Signal
from worker import runner
from worker.strategy_handlers import ema_rsi_reversal


CANDLE_TS = datetime(2024, 6, 1, 14, 0, tzinfo=timezone.utc)


def _sig(symbol="BTC/USDT", ts=CANDLE_TS):
    return {
        "symbol": symbol,
        "signal_type": "SHORT",
        "timestamp_candle": ts,
        "close": 100.0,
        "indicators": {"close": 100.0, "rsi": 70.0, "ema_rsi_20": 55.0,
                       "bars_since_reversal_1h": 2, "bars_since_reversal_1d": 5},
    }


def _patch_scan(monkeypatch, fake):
    """Replace the EmaRsi handler's scan(). Lambda signature: (sh, sl, ex, sym, p)."""
    monkeypatch.setattr(ema_rsi_reversal, "scan", fake)


@pytest.fixture
def active_process(make_user, make_process):
    owner = make_user(username="alice")
    proc = make_process(owner.id, symbols=["BTC/USDT", "ETH/USDT"],
                        telegram_chat_id="123", is_active=True)
    return proc


def _count_signals(session_factory, process_id):
    with session_factory() as db:
        return len(db.scalars(select(Signal).where(Signal.process_id == process_id)).all())


def test_happy_path_inserts_signal_and_sends(active_process, session_factory, monkeypatch):
    sends = []
    _patch_scan(monkeypatch, lambda sh, sl, ex, sym, p: _sig(sym) if sym == "BTC/USDT" else None)
    monkeypatch.setattr(runner, "send_message", lambda chat, text: (sends.append((chat, text)) or (True, None)))

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.signals_inserted == 1
    assert result.telegram_sent == 1
    # 1 per-signal alert + 1 completion summary, both to the process's chat.
    assert len(sends) == 2
    assert all(chat == "123" for chat, _ in sends)
    assert any("SHORT signal" in t for _, t in sends)
    assert any("Quét xong" in t for _, t in sends)
    assert _count_signals(session_factory, active_process.id) == 1
    with session_factory() as db:
        p = db.get(Process, active_process.id)
        assert p.last_run_status == "OK"
        assert p.last_run_started_at is None
        assert p.last_run_at is not None


def test_duplicate_candle_not_resent(active_process, session_factory, monkeypatch):
    sends = []
    _patch_scan(monkeypatch, lambda sh, sl, ex, sym, p: _sig("BTC/USDT") if sym == "BTC/USDT" else None)
    monkeypatch.setattr(runner, "send_message", lambda chat, text: (sends.append(text) or (True, None)))

    runner.run_one_process(session_factory, active_process.id)
    runner.run_one_process(session_factory, active_process.id)  # same candle

    assert _count_signals(session_factory, active_process.id) == 1
    # Run 1: 1 per-signal alert + 1 completion = 2.
    # Run 2: signal dedup'd (no per-signal alert) + 1 completion = 1. Total 3.
    alerts = [t for t in sends if "SHORT signal" in t]
    completions = [t for t in sends if "Quét xong" in t]
    assert len(alerts) == 1  # the dedupe contract: alert NOT re-sent
    assert len(completions) == 2  # every run sends one


def test_telegram_failure_keeps_signal_and_warns(active_process, session_factory, monkeypatch):
    _patch_scan(monkeypatch, lambda sh, sl, ex, sym, p: _sig("BTC/USDT") if sym == "BTC/USDT" else None)
    monkeypatch.setattr(runner, "send_message", lambda chat, text: (False, "Forbidden: bot was blocked"))

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.signals_inserted == 1
    assert result.telegram_failed == 1
    with session_factory() as db:
        sig = db.scalar(select(Signal).where(Signal.process_id == active_process.id))
        assert sig.telegram_sent is False
        assert "blocked" in sig.telegram_error.lower()
        p = db.get(Process, active_process.id)
        assert p.last_run_status.startswith("OK (telegram error")


def test_process_deleted_mid_run_no_telegram(active_process, session_factory, monkeypatch):
    sends = []

    def deleting_scan(sh, sl, ex, sym, p):
        # Simulate the user deleting the process mid-cycle.
        with session_factory() as db:
            proc = db.get(Process, active_process.id)
            if proc is not None:
                db.delete(proc)
                db.commit()
        return _sig(sym)

    _patch_scan(monkeypatch, deleting_scan)
    monkeypatch.setattr(runner, "send_message", lambda chat, text: (sends.append(1) or (True, None)))

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.status == "missing"
    assert len(sends) == 0
    assert _count_signals(session_factory, active_process.id) == 0


def test_stopped_mid_run_inserts_but_no_telegram(active_process, session_factory, monkeypatch):
    sends = []

    def stopping_scan(sh, sl, ex, sym, p):
        with session_factory() as db:
            proc = db.get(Process, active_process.id)
            proc.is_active = False
            db.commit()
        return _sig("BTC/USDT") if sym == "BTC/USDT" else None

    _patch_scan(monkeypatch, stopping_scan)
    monkeypatch.setattr(runner, "send_message", lambda chat, text: (sends.append(text) or (True, None)))

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.signals_inserted == 1
    # Per-signal alert is skipped because the process flipped inactive; the
    # completion summary still fires (it summarises the run, regardless of state).
    assert not any("SHORT signal" in t for t in sends)
    assert any("Quét xong" in t for t in sends)
    assert _count_signals(session_factory, active_process.id) == 1


def test_exception_sets_error_status(active_process, session_factory, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("indicator blew up")

    _patch_scan(monkeypatch, boom)
    monkeypatch.setattr(runner, "send_message", lambda *a, **k: (True, None))

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.status.startswith("error:")
    with session_factory() as db:
        p = db.get(Process, active_process.id)
        assert p.last_run_status.startswith("error:")
        assert p.last_run_started_at is None


def test_unknown_strategy_name_sets_error_status(active_process, session_factory, monkeypatch):
    """If a process points at a strategy not in the registry, the runner records
    the error against that process — it must not crash the worker loop."""
    monkeypatch.setattr(runner, "send_message", lambda *a, **k: (True, None))
    with session_factory() as db:
        db.get(Process, active_process.id).strategy_name = "NotARealStrategy"
        db.commit()

    result = runner.run_one_process(session_factory, active_process.id)

    assert result.status.startswith("error:")
    assert "NotARealStrategy" in result.error


def test_scan_runs_real_strategy_without_error(monkeypatch):
    """Feed a synthetic 1D/1H DataFrame through the real EmaRsi handler scan().

    Engineering a guaranteed SHORT is brittle; we just assert the indicator
    pipeline runs end-to-end and returns either None or a well-formed dict.
    """
    import numpy as np
    import pandas as pd

    def _df(n):
        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        return pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1, "close": close,
             "volume": np.full(n, 10.0)}, index=idx)

    monkeypatch.setattr(ema_rsi_reversal, "ensure_data_ready",
                        lambda ex, sym, tf, min_required=250: _df(260))
    strat_1d, strat_1h = ema_rsi_reversal.build(
        {"rsi_period": 14, "n1d": 20, "m1h": 3, "min_ema_rsi": 50.0,
         "min_gap": 0.0, "use_ema_filter": False, "lookback": 250})
    result = ema_rsi_reversal.scan(strat_1d, strat_1h, "binance", "BTC/USDT", {"lookback": 250})
    assert result is None or (result["signal_type"] == "SHORT" and "indicators" in result)


def test_force_run_flag_cleared_on_start(active_process, session_factory, monkeypatch):
    with session_factory() as db:
        p = db.get(Process, active_process.id)
        p.force_run_requested_at = datetime.now(timezone.utc)
        db.commit()
    _patch_scan(monkeypatch, lambda *a, **k: None)
    monkeypatch.setattr(runner, "send_message", lambda *a, **k: (True, None))

    runner.run_one_process(session_factory, active_process.id)

    with session_factory() as db:
        assert db.get(Process, active_process.id).force_run_requested_at is None


def _set_force_run(session_factory, process_id):
    with session_factory() as db:
        db.get(Process, process_id).force_run_requested_at = datetime.now(timezone.utc)
        db.commit()


class TestForceRunCompletionTelegram:
    def test_force_run_no_signals_sends_completion_summary(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(monkeypatch, lambda *a, **k: None)
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append((chat, text)) or (True, None)),
        )
        _set_force_run(session_factory, active_process.id)

        runner.run_one_process(session_factory, active_process.id)

        # exactly one completion message (no per-signal alerts since scan returned None)
        assert len(sends) == 1
        chat, text = sends[0]
        assert chat == "123"  # process's telegram_chat_id from active_process fixture
        assert "Quét xong" in text
        assert "0" in text  # 0 signals

    def test_scheduled_run_also_sends_completion(
        self, active_process, session_factory, monkeypatch
    ):
        """Scheduled runs (no force-run flag) now also send a completion summary."""
        sends = []
        _patch_scan(monkeypatch, lambda *a, **k: None)
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        # NO force_run_requested_at set → scheduled run

        runner.run_one_process(session_factory, active_process.id)

        # Now: zero signals + scheduled run still emits one "Quét xong" summary.
        assert len(sends) == 1
        assert "Quét xong" in sends[0]

    def test_force_run_with_signals_sends_per_signal_plus_completion(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(
            monkeypatch,
            lambda sh, sl, ex, sym, p: _sig(sym) if sym == "BTC/USDT" else None,
        )
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        _set_force_run(session_factory, active_process.id)

        runner.run_one_process(session_factory, active_process.id)

        # one signal alert + one completion summary
        assert len(sends) == 2
        assert any("SHORT signal" in t for t in sends)
        assert any("Quét xong" in t for t in sends)

    def test_force_run_on_inactive_process_still_sends_per_signal_alert(
        self, make_user, make_process, session_factory, monkeypatch
    ):
        """Quét ngay on a Stop'd process: per-signal alert MUST still fire.

        Stop suppresses scheduled scans' alert noise — but an explicit force-run
        is the user asking 'show me what this strategy would catch right now',
        so we honour it even when ``is_active=False``.
        """
        owner = make_user(username="alice")
        proc = make_process(
            owner.id, symbols=["BTC/USDT"], telegram_chat_id="123", is_active=False,
        )
        sends = []
        _patch_scan(monkeypatch, lambda sh, sl, ex, sym, p: _sig(sym))
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        _set_force_run(session_factory, proc.id)

        runner.run_one_process(session_factory, proc.id)

        assert any("SHORT signal" in t for t in sends), \
            "force-run on inactive process should still send per-signal alert"
        assert any("Quét xong" in t for t in sends)

    def test_scheduled_run_on_inactive_skips_per_signal_alert(
        self, active_process, session_factory, monkeypatch
    ):
        """Sanity-check the other half of the gate: a scheduled scan (not
        force-run) on a process that flips inactive mid-run keeps the signal
        but skips the per-signal alert."""
        sends = []

        def stopping_scan(sh, sl, ex, sym, p):
            with session_factory() as db:
                db.get(Process, active_process.id).is_active = False
                db.commit()
            return _sig(sym)

        _patch_scan(monkeypatch, stopping_scan)
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        # NOTE: no _set_force_run — this is a scheduled run.

        runner.run_one_process(session_factory, active_process.id)

        assert not any("SHORT signal" in t for t in sends), \
            "scheduled scan on inactive process should NOT send per-signal alert"

    def test_force_run_exception_sends_failure_telegram(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        _set_force_run(session_factory, active_process.id)

        result = runner.run_one_process(session_factory, active_process.id)

        assert result.status.startswith("error:")
        # one failure-completion message
        assert len(sends) == 1
        assert "Quét thất bại" in sends[0]
        assert "boom" in sends[0]

    def test_no_signals_and_telegram_on_no_signal_is_false_skips_completion(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(monkeypatch, lambda *a, **k: None)
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )

        # Set telegram_on_no_signal = False
        with session_factory() as db:
            p = db.get(Process, active_process.id)
            params = dict(p.strategy_params)
            params["telegram_on_no_signal"] = False
            p.strategy_params = params
            db.commit()

        runner.run_one_process(session_factory, active_process.id)

        # No completion summary should be sent because there are no signals and telegram_on_no_signal is False
        assert len(sends) == 0

    def test_signals_found_and_telegram_on_no_signal_is_false_sends_completion(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(
            monkeypatch,
            lambda sh, sl, ex, sym, p: _sig(sym) if sym == "BTC/USDT" else None,
        )
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )

        # Set telegram_on_no_signal = False
        with session_factory() as db:
            p = db.get(Process, active_process.id)
            params = dict(p.strategy_params)
            params["telegram_on_no_signal"] = False
            p.strategy_params = params
            db.commit()

        runner.run_one_process(session_factory, active_process.id)

        # Should send both: one signal alert + one completion summary
        assert len(sends) == 2
        assert any("SHORT signal" in t for t in sends)
        assert any("Quét xong" in t for t in sends)

    def test_exception_sends_telegram_even_if_telegram_on_no_signal_is_false(
        self, active_process, session_factory, monkeypatch
    ):
        sends = []
        _patch_scan(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(
            runner, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )

        # Set telegram_on_no_signal = False
        with session_factory() as db:
            p = db.get(Process, active_process.id)
            params = dict(p.strategy_params)
            params["telegram_on_no_signal"] = False
            p.strategy_params = params
            db.commit()

        runner.run_one_process(session_factory, active_process.id)

        # Completion summary should be sent due to error
        assert len(sends) == 1
        assert "Quét thất bại" in sends[0]
        assert "boom" in sends[0]


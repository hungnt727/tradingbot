"""Integration tests for /processes routes (Phase 6 slice 0005)."""
from sqlalchemy import select

from app_db.models.process import Process
from web.routes import processes as processes_route


def _form(**overrides):
    data = {
        "strategy_name": "EmaRsiReversal",
        "name": "MyProc",
        "exchange": "binance",
        "symbols_mode": "list",
        "symbols_list": "BTC/USDT\nETH/USDT",
        "interval_minutes": "60",
        "telegram_chat_id": "",
        "rsi_period": "14",
        "max_distance_candles": "20",
        "min_gap": "0.0",
        "min_ema_rsi": "50.0",
        "sl_pct": "0.05",
        "tp1_pct": "0.10",
        "tp2_pct": "0.20",
        "lookback": "250",
        "n1d": "20",
        "m1h": "3",
    }
    data.update(overrides)
    return data


class TestProcessCrudRoutes:
    def test_create_appears_in_own_list_only(self, make_user, login, client, session_factory):
        make_user(username="alice", password="pw")
        make_user(username="bob", password="pw")
        c = login("alice")
        resp = c.post("/processes", data=_form(name="AliceBot"))
        assert resp.status_code == 303
        # alice sees it
        assert "AliceBot" in c.get("/processes").text
        # bob does not
        client.post("/login", data={"username": "bob", "password": "pw"})
        assert "AliceBot" not in client.get("/processes").text

    def test_interval_below_min_rejected(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/processes", data=_form(interval_minutes="3"))
        assert resp.status_code == 400
        assert "≥ 5" in resp.text or "interval" in resp.text.lower()

    def test_rsi_out_of_bounds_rejected(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/processes", data=_form(rsi_period="1"))
        assert resp.status_code == 400
        assert "rsi_period" in resp.text.lower()

    def test_edit_others_process_404(self, make_user, login, make_process, client):
        owner = make_user(username="owner", password="pw")
        make_user(username="intruder", password="pw")
        proc = make_process(owner.id, name="secret")
        client.post("/login", data={"username": "intruder", "password": "pw"})
        resp = client.get(f"/processes/{proc.id}/edit")
        assert resp.status_code == 404

    def test_edit_updates_process(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, name="old")
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}", data=_form(name="renamed"))
        assert resp.status_code == 303
        with session_factory() as db:
            assert db.get(Process, proc.id).name == "renamed"

    def test_edit_active_process_not_blocked(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, name="live", telegram_chat_id="123", is_active=True)
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}", data=_form(name="still-live"))
        assert resp.status_code == 303
        with session_factory() as db:
            row = db.get(Process, proc.id)
            assert row.name == "still-live" and row.is_active is True

    def test_delete_removes(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id)
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}/delete")
        assert resp.status_code == 303
        with session_factory() as db:
            assert db.get(Process, proc.id) is None


class TestToggleRoutes:
    def test_start_requires_chat_id(self, make_user, login, make_process):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id=None)
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}/toggle")
        assert resp.status_code == 400
        assert "telegram" in resp.text.lower()

    def test_start_succeeds_with_chat_id(self, make_user, login, make_process, session_factory):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id="123")
        c = login("alice")
        resp = c.post(f"/processes/{proc.id}/toggle")
        assert resp.status_code == 303
        with session_factory() as db:
            assert db.get(Process, proc.id).is_active is True


class TestToggleNotifications:
    def test_start_sends_bat_telegram(self, make_user, login, make_process, monkeypatch):
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append((chat, text)) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id="123", is_active=False)
        c = login("alice")

        c.post(f"/processes/{proc.id}/toggle")

        assert len(sends) == 1
        chat, text = sends[0]
        assert chat == "123"
        assert "Đã bật" in text
        assert proc.name in text

    def test_stop_sends_tat_telegram(self, make_user, login, make_process, monkeypatch):
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append((chat, text)) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id="123", is_active=True)
        c = login("alice")

        c.post(f"/processes/{proc.id}/toggle")

        assert len(sends) == 1
        chat, text = sends[0]
        assert chat == "123"
        assert "Đã tắt" in text
        assert proc.name in text

    def test_stop_without_chat_no_telegram_but_toggles(
        self, make_user, login, make_process, session_factory, monkeypatch
    ):
        """Stopping is allowed even without a chat ID; just no notification."""
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")  # no default_telegram_chat_id
        # Force is_active=True directly because route validation would reject Start without chat
        proc = make_process(owner.id, telegram_chat_id=None, is_active=True)
        c = login("alice")

        c.post(f"/processes/{proc.id}/toggle")

        assert sends == []  # nothing to send to
        with session_factory() as db:
            assert db.get(Process, proc.id).is_active is False

    def test_validation_error_on_start_does_not_send_telegram(
        self, make_user, login, make_process, monkeypatch
    ):
        sends = []
        monkeypatch.setattr(
            processes_route, "send_message",
            lambda chat, text: (sends.append(text) or (True, None)),
        )
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, telegram_chat_id=None, is_active=False)
        c = login("alice")

        resp = c.post(f"/processes/{proc.id}/toggle")

        assert resp.status_code == 400  # validation failed (no chat for Start)
        assert sends == []  # never sent


class TestMultiStrategySupport:
    def test_new_form_default_renders_emarsi_fields(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.get("/processes/new")
        assert resp.status_code == 200
        assert "rsi_period" in resp.text
        assert "EMA-RSI Reversal" in resp.text

    def test_new_form_with_strategy_query_param_renders_other_strategy(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.get("/processes/new?strategy=VolumeBreakout")
        assert resp.status_code == 200
        # VolumeBreakout-specific basic fields appear; EmaRsi-specific ones don't.
        assert "vol_mult" in resp.text
        assert "price_pct" in resp.text
        assert "rsi_period" not in resp.text

    def test_new_form_unknown_strategy_falls_back_to_default(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.get("/processes/new?strategy=DoesNotExist")
        assert resp.status_code == 200
        # Falls back to EmaRsiReversal fields.
        assert "rsi_period" in resp.text

    def test_create_volume_breakout_process(self, make_user, login, session_factory):
        from app_db.models.process import Process
        make_user(username="alice", password="pw")
        c = login("alice")
        resp = c.post("/processes", data={
            "strategy_name": "VolumeBreakout",
            "name": "VBProc",
            "exchange": "binance",
            "symbols_mode": "list",
            "symbols_list": "BTC/USDT",
            "interval_minutes": "60",
            "telegram_chat_id": "",
            "sma_lookback": "10",
            "vol_mult_1d": "3.0", "vol_mult_1h": "2.5",
            "price_pct_1d": "0.30", "price_pct_1h": "0.20",
            "sl_pct": "0.05", "tp1_pct": "0.10", "tp2_pct": "0.20",
            "lookback": "50",
        })
        assert resp.status_code == 303
        with session_factory() as db:
            row = db.scalar(select(Process).where(Process.name == "VBProc"))
            assert row is not None
            assert row.strategy_name == "VolumeBreakout"
            # Verify per-TF params persisted distinctly.
            assert row.strategy_params["vol_mult_1d"] == 3.0
            assert row.strategy_params["vol_mult_1h"] == 2.5
            assert row.strategy_params["sma_lookback"] == 10

    def test_edit_form_locks_strategy_dropdown(self, make_user, login, make_process):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, name="locked")
        c = login("alice")
        resp = c.get(f"/processes/{proc.id}/edit")
        assert resp.status_code == 200
        # The "Edit" view ships a disabled <select> showing the locked strategy.
        assert "disabled" in resp.text
        assert "không thể đổi" in resp.text

    def test_edit_ignores_strategy_change_in_form(
        self, make_user, login, make_process, session_factory
    ):
        """A crafted POST with a different strategy_name must NOT mutate the DB
        record's strategy. Route forces strategy_name from DB before service call."""
        from app_db.models.process import Process
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id, name="immutable")
        c = login("alice")
        # Send a VolumeBreakout strategy_name + EmaRsi params on an EmaRsi process.
        # Params still validate (route forces strategy_name from DB), so the update succeeds
        # with the original strategy intact.
        resp = c.post(f"/processes/{proc.id}", data=_form(
            strategy_name="VolumeBreakout", name="still-emarsi"
        ))
        assert resp.status_code == 303
        with session_factory() as db:
            row = db.get(Process, proc.id)
            assert row.strategy_name == "EmaRsiReversal"  # unchanged
            assert row.name == "still-emarsi"


class TestAdminProcessesView:
    def test_admin_sees_all_readonly(self, make_user, login, make_process):
        owner = make_user(username="owner", password="pw")
        make_user(username="boss", password="pw", is_admin=True)
        make_process(owner.id, name="ownerproc")
        c = login("boss")
        resp = c.get("/admin/processes")
        assert resp.status_code == 200
        assert "ownerproc" in resp.text
        assert "owner" in resp.text  # owner username column

    def test_regular_user_cannot_see_admin_processes(self, make_user, login):
        make_user(username="alice", password="pw")
        c = login("alice")
        assert c.get("/admin/processes").status_code == 403

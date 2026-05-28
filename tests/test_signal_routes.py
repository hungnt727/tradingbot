"""Integration tests for signal history routes (Phase 6 slice 0008)."""


class TestSignalRoutes:
    def test_owner_sees_signals(self, make_user, login, make_process, make_signal):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id)
        make_signal(proc.id, symbol="BTC/USDT")
        c = login("alice")
        resp = c.get(f"/processes/{proc.id}/signals")
        assert resp.status_code == 200
        assert "BTC/USDT" in resp.text

    def test_non_owner_404(self, make_user, login, make_process, make_signal, client):
        owner = make_user(username="owner", password="pw")
        make_user(username="intruder", password="pw")
        proc = make_process(owner.id)
        make_signal(proc.id)
        client.post("/login", data={"username": "intruder", "password": "pw"})
        assert client.get(f"/processes/{proc.id}/signals").status_code == 404

    def test_admin_sees_any(self, make_user, login, make_process, make_signal):
        owner = make_user(username="owner", password="pw")
        make_user(username="boss", password="pw", is_admin=True)
        proc = make_process(owner.id)
        make_signal(proc.id, symbol="ETH/USDT")
        c = login("boss")
        resp = c.get(f"/processes/{proc.id}/signals")
        assert resp.status_code == 200 and "ETH/USDT" in resp.text

    def test_htmx_filter_returns_table_fragment_only(self, make_user, login, make_process, make_signal):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id)
        make_signal(proc.id, symbol="BTC/USDT")
        c = login("alice")
        resp = c.get(f"/processes/{proc.id}/signals", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "signals-table" in resp.text
        assert "<html" not in resp.text.lower()  # fragment, not full page

    def test_detail_modal_shows_snapshot(self, make_user, login, make_process, make_signal):
        owner = make_user(username="alice", password="pw")
        proc = make_process(owner.id)
        sig = make_signal(proc.id, indicators={"rsi": 71.5, "ema_rsi_20": 55.0})
        c = login("alice")
        resp = c.get(f"/processes/{proc.id}/signals/{sig.id}")
        assert resp.status_code == 200
        assert "71.5" in resp.text

    def test_detail_other_process_404(self, make_user, login, make_process, make_signal, client):
        owner = make_user(username="owner", password="pw")
        make_user(username="intruder", password="pw")
        proc = make_process(owner.id)
        sig = make_signal(proc.id)
        client.post("/login", data={"username": "intruder", "password": "pw"})
        assert client.get(f"/processes/{proc.id}/signals/{sig.id}").status_code == 404

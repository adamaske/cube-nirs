"""WebSocket + REST integration tests (FastAPI TestClient).

A test session factory injects the engine-test fakes (NullBeeper, dwell 0,
no LSL) but keeps the real clock with tiny durations, so the full
thread -> asyncio -> WebSocket path is exercised.
"""
import pytest
from fastapi.testclient import TestClient

from app.server import engine
from app.server.engine import NullBeeper, Session
from app.server.lsl_out import NullOutlet
from app.server.main import create_app
from app.server.store import Store
from scripts import scramble as scramble_gen

START = {
    "cmd": "start",
    "config": {"subject": 1, "session": 1, "trials": 1, "rest_pre": 0.05,
               "rest_post": 0.05, "seed": 7, "no_lsl": True, "no_beep": True},
    "advance_mode": "both",
}


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path))

    def factory(config, emit):
        return Session(config, marker_sink=NullOutlet(), beeper=NullBeeper(),
                       store=store, scramble_fn=scramble_gen.generate,
                       emit=emit, dwell_s=0.0)

    app = create_app(store=store, session_factory=factory)
    with TestClient(app) as c:
        c.app_store = store
        yield c


def recv_until(ws, pred, limit=500):
    for _ in range(limit):
        msg = ws.receive_json()
        if pred(msg):
            return msg
    raise AssertionError("expected message never arrived")


def wait_state(ws, state):
    return recv_until(ws, lambda m: m.get("type") == "state" and m.get("state") == state)


def test_snapshot_on_connect_idle(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["state"] == "idle"


def test_full_session_over_websocket(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # idle snapshot
        ws.send_json(START)
        recv_until(ws, lambda m: m["type"] == "ack" and m["cmd"] == "start")
        snap = wait_state(ws, "configured")
        assert snap["scramble"]
        assert snap["trials_planned"] == 1
        ws.send_json({"cmd": "advance", "from_state": "configured"})
        wait_state(ws, "plan")
        ws.send_json({"cmd": "advance", "from_state": "plan"})
        wait_state(ws, "solve")
        ws.send_json({"cmd": "dnf"})
        recv_until(ws, lambda m: m["type"] == "dnf_flagged")
        ws.send_json({"cmd": "advance", "from_state": "solve"})
        done = wait_state(ws, "done")
        assert done["completed"] is True
        assert done["results"][0]["dnf"] is True
    assert len(client.app_store.list_sessions()) == 1


def test_start_while_running_rejected(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(START)
        recv_until(ws, lambda m: m["type"] == "ack")
        ws.send_json(START)
        msg = recv_until(ws, lambda m: m["type"] == "rejected")
        assert "already running" in msg["reason"]
        ws.send_json({"cmd": "abort"})
        wait_state(ws, "aborted")


def test_invalid_and_malformed_commands(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"cmd": "bogus"})
        assert recv_until(ws, lambda m: m["type"] == "error")
        ws.send_json({"cmd": "advance"})  # missing from_state
        assert recv_until(ws, lambda m: m["type"] == "error")
        ws.send_json({"cmd": "advance", "from_state": "plan"})  # no session
        msg = recv_until(ws, lambda m: m["type"] == "rejected")
        assert msg["reason"] == "no session"


def test_stale_advance_rejected_over_ws(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(START)
        recv_until(ws, lambda m: m["type"] == "ack")
        wait_state(ws, "configured")
        ws.send_json({"cmd": "advance", "from_state": "solve"})
        msg = recv_until(ws, lambda m: m["type"] == "rejected")
        assert "stale" in msg["reason"]
        ws.send_json({"cmd": "abort"})
        wait_state(ws, "aborted")


def test_advance_mode_filters_source(client):
    start = dict(START, advance_mode="experimenter")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(start)
        recv_until(ws, lambda m: m["type"] == "ack")
        wait_state(ws, "configured")
        ws.send_json({"cmd": "advance", "from_state": "configured", "source": "subject"})
        msg = recv_until(ws, lambda m: m["type"] == "rejected")
        assert "disabled" in msg["reason"]
        ws.send_json({"cmd": "abort"})
        wait_state(ws, "aborted")


def test_reconnect_mid_session_gets_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(START)
        recv_until(ws, lambda m: m["type"] == "ack")
        wait_state(ws, "configured")
    # first client is gone; session lives on server-side
    with client.websocket_connect("/ws") as ws2:
        snap = ws2.receive_json()
        assert snap["type"] == "state"
        assert snap["state"] == "configured"
        assert snap["scramble"]
        ws2.send_json({"cmd": "abort"})
        wait_state(ws2, "aborted")


def test_rest_endpoints(client, tmp_path):
    r = client.get("/api/config")
    assert r.status_code == 200 and r.json()["config"]["trials"] == 5
    r = client.get("/api/next-session", params={"subject": 1})
    assert r.json() == {"subject": 1, "session": 1}
    r = client.get("/api/sessions")
    assert r.json() == {"sessions": [], "solves": []}
    r = client.get("/api/sessions/nope")
    assert r.status_code == 404
    r = client.get("/api/lsl-status")
    assert "available" in r.json()


def test_dashboard_reads_after_session(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(START)
        recv_until(ws, lambda m: m["type"] == "ack")
        wait_state(ws, "configured")
        ws.send_json({"cmd": "advance", "from_state": "configured"})
        wait_state(ws, "plan")
        ws.send_json({"cmd": "advance", "from_state": "plan"})
        wait_state(ws, "solve")
        ws.send_json({"cmd": "advance", "from_state": "solve"})
        wait_state(ws, "done")
    data = client.get("/api/sessions").json()
    assert len(data["sessions"]) == 1
    assert len(data["solves"]) == 1
    base = data["sessions"][0]["log"]
    log = client.get(f"/api/sessions/{base}").json()
    assert log["completed"] is True
    assert [m["name"] for m in log["markers"]][0] == "SESSION_START"

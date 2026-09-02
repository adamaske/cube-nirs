"""FastAPI app: REST + WebSocket + static files for the session GUI.

The asyncio side never executes timing logic. Engine events cross the
thread boundary once, via `loop.call_soon_threadsafe(queue.put_nowait, ev)`;
a consumer task broadcasts them to every connected WebSocket. Commands go
the other way as plain thread-safe method calls on the Session.
"""
import asyncio
import dataclasses
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from app.server import engine  # noqa: E402
from app.server.beeper import Beeper  # noqa: E402
from app.server.engine import Session, SessionConfig  # noqa: E402
from app.server.store import Store  # noqa: E402
from scripts import scramble as scramble_gen  # noqa: E402

DIST = os.path.join(ROOT, "app", "web", "dist")

AdvanceMode = Literal["experimenter", "subject", "both"]


# --------------------------------------------------------------------------- #
# Inbound message models
# --------------------------------------------------------------------------- #
class StartConfig(BaseModel):
    subject: int = 1
    session: int = 1
    trials: int = 5
    rest_pre: float = 20.0
    rest_post: float = 45.0
    scramble_len: int = 20
    seed: Optional[int] = None
    stream_name: str = "Trigger"
    stream_type: str = "Markers"
    source_id: str = "cube-nirs"
    no_lsl: bool = False
    no_beep: bool = False
    comment: str = ""


class StartCmd(BaseModel):
    cmd: Literal["start"]
    config: StartConfig
    advance_mode: AdvanceMode = "both"


class AdvanceCmd(BaseModel):
    cmd: Literal["advance"]
    from_state: str
    source: Literal["experimenter", "subject"] = "experimenter"


class DnfCmd(BaseModel):
    cmd: Literal["dnf"]


class AbortCmd(BaseModel):
    cmd: Literal["abort"]


COMMANDS = {"start": StartCmd, "advance": AdvanceCmd, "dnf": DnfCmd, "abort": AbortCmd}


def default_session_factory(config: SessionConfig, emit) -> Session:
    """Builds a Session with real dependencies. Raises if the LSL outlet
    cannot be created (running unmarked silently is the worst failure mode)."""
    from app.server.lsl_out import MarkerOutlet, NullOutlet
    outlet = NullOutlet() if config.no_lsl else MarkerOutlet(
        config.stream_name, config.stream_type, config.source_id)
    return Session(
        config,
        marker_sink=outlet,
        beeper=engine.NullBeeper() if config.no_beep else Beeper(),
        store=Store(ROOT),
        scramble_fn=scramble_gen.generate,
        emit=emit,
    )


# --------------------------------------------------------------------------- #
# Hub: connected WebSockets with per-client outbound queues
# --------------------------------------------------------------------------- #
class Hub:
    QUEUE_SIZE = 200

    def __init__(self):
        self.clients: dict[WebSocket, asyncio.Queue] = {}

    def add(self, ws: WebSocket) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=self.QUEUE_SIZE)
        self.clients[ws] = q
        return q

    def remove(self, ws: WebSocket):
        self.clients.pop(ws, None)

    def broadcast(self, msg: dict):
        for q in self.clients.values():
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                if msg.get("type") == "tick":
                    continue  # a slow client just loses stale ticks
                # never drop a state change: evict a stale tick if there is
                # one, otherwise the oldest queued message
                items = []
                while True:
                    try:
                        items.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                for i, it in enumerate(items):
                    if it.get("type") == "tick":
                        del items[i]
                        break
                else:
                    items = items[1:]
                items.append(msg)
                for it in items:
                    q.put_nowait(it)


# --------------------------------------------------------------------------- #
# Supervisor: at most one live Session
# --------------------------------------------------------------------------- #
class SessionSupervisor:
    def __init__(self, store: Store, hub: Hub, session_factory=default_session_factory):
        self.store = store
        self.hub = hub
        self.session_factory = session_factory
        self.session: Optional[Session] = None
        self.advance_mode: AdvanceMode = "both"
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: asyncio.Queue = asyncio.Queue()

    # -- engine event plumbing (emit runs on the session thread) ------------ #
    def _emit(self, ev):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)

    async def consume_events(self):
        while True:
            ev = await self.queue.get()
            name = engine.event_name(ev)
            msg = {"type": name, **dataclasses.asdict(ev)}
            if name == "tick":
                self.hub.broadcast(msg)
            else:
                self.hub.broadcast(msg)
                if name in ("state_changed", "trial_completed", "dnf_flagged",
                            "session_ended"):
                    self.hub.broadcast(self.state_message())

    # -- state ------------------------------------------------------------- #
    def state_message(self) -> dict:
        if self.session is None:
            return {"type": "state", "state": engine.IDLE, "advance_mode": self.advance_mode}
        return {"type": "state", **self.session.snapshot(),
                "advance_mode": self.advance_mode}

    # -- commands ----------------------------------------------------------- #
    def start(self, cmd: StartCmd) -> tuple[bool, str]:
        if self.session is not None and not self.session.is_over:
            return False, "a session is already running"
        try:
            config = SessionConfig(**cmd.config.model_dump())
        except ValueError as e:
            return False, f"invalid config: {e}"
        try:
            session = self.session_factory(config, self._emit)
        except Exception as e:
            logging.exception("failed to arm session")
            return False, f"could not create LSL outlet: {e}"
        self.advance_mode = cmd.advance_mode
        self.session = session
        session.start()
        return True, ""

    def handle(self, cmd) -> tuple[bool, str]:
        if isinstance(cmd, StartCmd):
            return self.start(cmd)
        if self.session is None:
            return False, "no session"
        if isinstance(cmd, AdvanceCmd):
            if self.advance_mode != "both" and cmd.source != self.advance_mode:
                return False, f"advance from {cmd.source!r} disabled (mode={self.advance_mode})"
            return self.session.advance(cmd.from_state)
        if isinstance(cmd, DnfCmd):
            return self.session.flag_dnf()
        if isinstance(cmd, AbortCmd):
            return self.session.abort()
        return False, "unknown command"


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(store: Store | None = None,
               session_factory=default_session_factory) -> FastAPI:
    store = store or Store(ROOT)
    hub = Hub()
    supervisor = SessionSupervisor(store, hub, session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        supervisor.loop = asyncio.get_running_loop()
        task = asyncio.create_task(supervisor.consume_events())
        yield
        task.cancel()

    app = FastAPI(title="cube-nirs session GUI", lifespan=lifespan)
    app.state.supervisor = supervisor

    # ---- REST ------------------------------------------------------------- #
    # in-memory saved setup-form values, served back as the form's prefill
    saved_config = {"config": StartConfig().model_dump(), "advance_mode": "both"}

    @app.get("/api/config")
    def get_config():
        return saved_config

    @app.post("/api/config")
    def post_config(cfg: StartConfig, advance_mode: AdvanceMode = "both"):
        saved_config["config"] = cfg.model_dump()
        saved_config["advance_mode"] = advance_mode
        return saved_config

    @app.get("/api/next-session")
    def next_session(subject: int):
        return {"subject": subject, "session": store.next_session_number(subject)}

    @app.get("/api/lsl-status")
    def lsl_status():
        try:
            import pylsl  # noqa: F401
            return {"available": True, "error": None}
        except Exception as e:
            return {"available": False, "error": str(e)}

    @app.get("/api/sessions")
    def sessions():
        return {"sessions": store.list_sessions(), "solves": store.list_solves()}

    @app.get("/api/sessions/{log}")
    def session_log(log: str):
        try:
            return store.read_log(log)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"no log {log!r}")

    # ---- WebSocket --------------------------------------------------------- #
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        q = hub.add(ws)
        await ws.send_json(supervisor.state_message())

        async def sender():
            while True:
                await ws.send_json(await q.get())

        send_task = asyncio.create_task(sender())
        try:
            while True:
                raw = await ws.receive_json()
                cmd_name = raw.get("cmd") if isinstance(raw, dict) else None
                model = COMMANDS.get(cmd_name)
                if model is None:
                    await ws.send_json({"type": "error", "reason": f"unknown command {cmd_name!r}"})
                    continue
                try:
                    cmd = model.model_validate(raw)
                except ValidationError as e:
                    await ws.send_json({"type": "error", "reason": str(e)})
                    continue
                ok, reason = supervisor.handle(cmd)
                await ws.send_json({"type": "ack" if ok else "rejected",
                                    "cmd": cmd_name, "reason": reason})
                if ok and cmd_name == "start":
                    hub.broadcast(supervisor.state_message())
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            hub.remove(ws)

    # ---- static frontend --------------------------------------------------- #
    if os.path.isdir(DIST):
        @app.get("/subject")
        def subject_page():
            return FileResponse(os.path.join(DIST, "subject.html"))

        @app.get("/dashboard")
        def dashboard_page():
            return FileResponse(os.path.join(DIST, "dashboard.html"))

        app.mount("/", StaticFiles(directory=DIST, html=True), name="static")

    return app

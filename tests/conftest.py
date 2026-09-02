import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.server import engine  # noqa: E402
from app.server.engine import Session, SessionConfig, NullBeeper  # noqa: E402
from app.server.store import Store  # noqa: E402
from scripts import scramble as scramble_gen  # noqa: E402


class FakeClock:
    """Deterministic clock: time advances only when the engine waits.
    Waits are near-instant in real time, so sessions finish in milliseconds."""
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def wait(self, event, timeout):
        event.wait(0.001)
        self.t += timeout


class FakeSink:
    """MarkerSink stub; t_wall from the fake clock so durations are exact."""
    def __init__(self, clock):
        self.clock = clock
        self.pushed = []

    def push(self, name):
        from scripts.triggers import code
        m = {"code": code(name), "name": name, "t_wall": self.clock.now(), "t_lsl": None}
        self.pushed.append(m)
        return m


class FakeBeeper:
    def __init__(self):
        self.cues = []

    def cue(self, times=1):
        self.cues.append(times)


class Recorder:
    def __init__(self):
        self.events = []
        self.ended = threading.Event()

    def __call__(self, ev):
        self.events.append(ev)
        if isinstance(ev, engine.SessionEnded):
            self.ended.set()

    def of(self, cls):
        return [e for e in self.events if isinstance(e, cls)]

    def states(self):
        return [e.state for e in self.of(engine.StateChanged)]

    def markers(self):
        return [e.name for e in self.of(engine.MarkerPushed)]


@pytest.fixture
def harness(tmp_path):
    def make(config=None, dwell_s=0.0):
        cfg = config or SessionConfig(subject=1, session=1, trials=2,
                                      rest_pre=0.2, rest_post=0.2, seed=42,
                                      no_lsl=True, no_beep=True, comment="fixture")
        clock = FakeClock()
        sink = FakeSink(clock)
        beeper = FakeBeeper()
        store = Store(str(tmp_path))
        rec = Recorder()
        s = Session(cfg, marker_sink=sink, beeper=beeper, store=store,
                    scramble_fn=scramble_gen.generate, clock=clock, emit=rec,
                    dwell_s=dwell_s)
        return s, rec, sink, beeper, store, clock
    return make


def wait_for_state(session, state, timeout=5.0):
    """Poll (real time) until the session reaches `state`."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if session.state == state:
            return True
        time.sleep(0.001)
    raise AssertionError(f"timed out waiting for state {state!r}, at {session.state!r}")


def advance_when(session, state, timeout=5.0, dnf=False):
    """Wait for `state`, then advance out of it (retrying past the dwell guard)."""
    import time
    wait_for_state(session, state, timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if dnf:
            session.flag_dnf()
        ok, reason = session.advance(state)
        if ok:
            return
        if "stale" in reason or "no active block" in reason:
            raise AssertionError(f"advance from {state} rejected: {reason}")
        time.sleep(0.001)
    raise AssertionError(f"advance from {state} never accepted")


def run_happy_path(session, rec, dnf_on=()):
    """Drive a full session to completion; flag DNF on trials in `dnf_on`."""
    session.start()
    advance_when(session, engine.CONFIGURED)
    for i in range(1, session.config.trials + 1):
        advance_when(session, engine.PLAN)
        advance_when(session, engine.SOLVE, dnf=(i in dnf_on))
        if i < session.config.trials:
            advance_when(session, engine.BREAK)
    assert rec.ended.wait(5.0)

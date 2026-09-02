"""Session state machine, extracted from scripts/run_session.py.

A `Session` runs the block design in its own background thread; all
time-critical work (deadline waits, marker pushes, beeps, saves) happens
there. Commands (`advance`, `flag_dnf`, `abort`) are thread-safe, validated
under one lock, and answered with accepted/rejected + reason. Every state
change, marker push and ~5 Hz timer tick is emitted through the `emit`
callback (called from the session thread — callers must make it thread-safe).

This module imports nothing from FastAPI, pylsl, or repo paths. The marker
sink, beeper, store, clock and scramble generator are injected:

    Clock       now() -> float; wait(event, timeout) -> None
    MarkerSink  push(name) -> {"code", "name", "t_wall", "t_lsl"}
    Beeper      cue(times=1)
    Store       save_json(base, dict), append_solve(row), append_session(row)

Block flow, marker codes, beep points, and the JSON/CSV output schemas are
identical to the pre-refactor scripts/run_session.py; tests compare against
fixtures generated from that code.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from scripts.triggers import TRIGGERS

# States
IDLE = "idle"
CONFIGURED = "configured"
REST_PRE = "rest_pre"
PLAN = "plan"
SOLVE = "solve"
REST_POST = "rest_post"
BREAK = "break"
DONE = "done"
ABORTED = "aborted"

SELF_PACED = {CONFIGURED, PLAN, SOLVE, BREAK}

TICK_INTERVAL = 0.2  # ~5 Hz
MIN_DWELL_S = 0.5    # double-advance guard


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
@dataclass
class StateChanged:
    state: str
    trial: int          # 1-based; 0 outside trials
    scramble: str

@dataclass
class MarkerPushed:
    code: int
    name: str
    t_wall: float
    t_lsl: Optional[float]

@dataclass
class Tick:
    state: str
    trial: int
    remaining: Optional[float]  # timed blocks
    elapsed: Optional[float]    # self-paced blocks

@dataclass
class TrialCompleted:
    trial: dict

@dataclass
class DnfFlagged:
    trial: int

@dataclass
class CommandRejected:
    command: str
    reason: str

@dataclass
class SessionEnded:
    completed: bool
    error: Optional[str]


def event_name(ev) -> str:
    return {
        StateChanged: "state_changed", MarkerPushed: "marker",
        Tick: "tick", TrialCompleted: "trial_completed",
        DnfFlagged: "dnf_flagged", CommandRejected: "command_rejected",
        SessionEnded: "session_ended",
    }[type(ev)]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SessionConfig:
    """Mirrors the CLI arguments; `params_dict()` reproduces the JSON log's
    `params` object byte-for-byte (including seed=None when auto-derived)."""
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

    def __post_init__(self):
        if self.subject < 1:
            raise ValueError("subject must be >= 1")
        if self.session < 1:
            raise ValueError("session must be >= 1")
        if self.trials < 1:
            raise ValueError("trials must be >= 1")
        if self.rest_pre < 0 or self.rest_post < 0:
            raise ValueError("rest durations must be >= 0")
        if self.scramble_len < 1:
            raise ValueError("scramble_len must be >= 1")

    def params_dict(self) -> dict:
        return dataclasses.asdict(self)


class RealClock:
    def now(self) -> float:
        import time
        return time.time()

    def wait(self, event: threading.Event, timeout: float):
        event.wait(timeout)


class NullBeeper:
    def cue(self, times: int = 1):
        pass


class _Aborted(Exception):
    pass


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self, config: SessionConfig, *, marker_sink, beeper, store,
                 scramble_fn: Callable[[int, int], str],
                 clock=None, emit: Callable = None,
                 started: dt.datetime | None = None,
                 dwell_s: float = MIN_DWELL_S):
        self.config = config
        self.marker_sink = marker_sink
        self.beeper = beeper
        self.store = store
        self.scramble_fn = scramble_fn
        self.clock = clock or RealClock()
        self._emit_cb = emit or (lambda ev: None)
        self.dwell_s = dwell_s

        self.started = started or dt.datetime.now()
        self.stamp = self.started.strftime("%Y%m%d_%H%M%S")
        self.base = f"sub-{config.subject:02d}_ses-{config.session:02d}_{self.stamp}"
        self.seed = config.seed if config.seed is not None else int(self.started.timestamp())

        self.session_dict = {
            "subject": config.subject, "session": config.session,
            "started": self.started.isoformat(),
            "params": config.params_dict(), "seed": self.seed,
            "stream": {"name": config.stream_name, "type": config.stream_type,
                       "source_id": config.source_id},
            "triggers": {c: n for c, (n, _) in TRIGGERS.items()},
            "markers": [], "trials": [], "completed": False,
        }
        self.first_scramble = scramble_fn(config.scramble_len, self.seed)

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._advance_pending = False
        self._dnf_pending = False
        self._abort_pending = False
        self.state = IDLE
        self._state_entered = self.clock.now()
        self.trial_i = 0
        self.scramble = self.first_scramble
        self.error: Optional[str] = None
        self._session_started = False  # SESSION_START pushed
        self._thread: Optional[threading.Thread] = None

    # ---- public API ------------------------------------------------------- #
    def start(self):
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("session already started")
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name=f"session-{self.base}")
        self._thread.start()

    def advance(self, from_state: str) -> tuple[bool, str]:
        with self._lock:
            if self.state in (DONE, ABORTED, IDLE):
                return self._reject("advance", f"no active block (state={self.state})")
            if from_state != self.state:
                return self._reject("advance", f"stale state: got {from_state!r}, current is {self.state!r}")
            if self.state not in SELF_PACED:
                return self._reject("advance", f"{self.state!r} is a timed block")
            if self._advance_pending:
                return self._reject("advance", "advance already pending")
            if self.clock.now() - self._state_entered < self.dwell_s:
                return self._reject("advance", f"ignored: {self.state!r} entered <{self.dwell_s:.1f}s ago")
            self._advance_pending = True
            self._wake.set()
            return True, ""

    def flag_dnf(self) -> tuple[bool, str]:
        with self._lock:
            if self.state != SOLVE:
                return self._reject("dnf", f"DNF only valid during solve (state={self.state})")
            if self._dnf_pending:
                return True, ""
            self._dnf_pending = True
        self._emit(DnfFlagged(trial=self.trial_i))
        return True, ""

    def abort(self) -> tuple[bool, str]:
        with self._lock:
            if self.state in (DONE, ABORTED):
                return self._reject("abort", f"session already over (state={self.state})")
            self._abort_pending = True
            self._wake.set()
            return True, ""

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "trial": self.trial_i,
                "trials_planned": self.config.trials,
                "scramble": self.scramble,
                "dnf_pending": self._dnf_pending,
                "config": self.config.params_dict(),
                "results": [dict(t) for t in self.session_dict["trials"]],
                "base": self.base,
                "started": self.started.isoformat(),
                "completed": self.session_dict["completed"],
                "error": self.error,
            }

    def join(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    @property
    def is_over(self) -> bool:
        with self._lock:
            return self.state in (DONE, ABORTED)

    # ---- internals (session thread) --------------------------------------- #
    def _reject(self, command: str, reason: str) -> tuple[bool, str]:
        logging.info(f"rejected {command}: {reason}")
        self._emit(CommandRejected(command=command, reason=reason))
        return False, reason

    def _emit(self, ev):
        try:
            self._emit_cb(ev)
        except Exception:
            logging.exception("event callback failed")

    def _set_state(self, state: str):
        with self._lock:
            self.state = state
            self._state_entered = self.clock.now()
            self._advance_pending = False
            self._wake.clear()
        self._emit(StateChanged(state=state, trial=self.trial_i, scramble=self.scramble))

    def _check_abort(self):
        with self._lock:
            if self._abort_pending:
                raise _Aborted()

    def _mark(self, name: str) -> dict:
        # LSL push happens before the JSON save so disk latency lands in
        # rest periods, never in marker timing (same ordering as the CLI).
        m = self.marker_sink.push(name)
        self.session_dict["markers"].append(m)
        self._save()
        self._emit(MarkerPushed(**m))
        return m

    def _save(self):
        self.store.save_json(self.base, self.session_dict)

    def _timed_block(self, seconds: float):
        deadline = self.clock.now() + seconds
        while True:
            self._check_abort()
            remaining = deadline - self.clock.now()
            if remaining <= 0:
                return
            self._emit(Tick(state=self.state, trial=self.trial_i,
                            remaining=round(remaining, 1), elapsed=None))
            self.clock.wait(self._wake, min(TICK_INTERVAL, remaining))

    def _self_paced_block(self) -> float:
        """Wait for an accepted advance; returns elapsed seconds."""
        t0 = self._state_entered
        while True:
            self._check_abort()
            with self._lock:
                if self._advance_pending:
                    self._advance_pending = False
                    self._wake.clear()
                    return self.clock.now() - t0
            self._emit(Tick(state=self.state, trial=self.trial_i,
                            remaining=None,
                            elapsed=round(self.clock.now() - t0, 1)))
            self.clock.wait(self._wake, TICK_INTERVAL)

    def _run(self):
        cfg = self.config
        try:
            self._set_state(CONFIGURED)
            self._self_paced_block()  # scramble done, Aurora recording confirmed

            self._session_started = True
            self._mark("SESSION_START")
            for i in range(1, cfg.trials + 1):
                self.trial_i = i
                trial = {"trial": i, "scramble": self.scramble, "dnf": False}

                self._set_state(REST_PRE)
                m = self._mark("REST_PRE")
                trial["t_rest_pre"] = m["t_lsl"] or m["t_wall"]
                self._timed_block(cfg.rest_pre)

                self.beeper.cue()
                self._set_state(PLAN)
                m = self._mark("PLAN")
                trial["t_plan"] = m["t_lsl"] or m["t_wall"]
                self._self_paced_block()

                self._set_state(SOLVE)
                m = self._mark("SOLVE")
                trial["t_solve"] = m["t_lsl"] or m["t_wall"]
                with self._lock:
                    self._dnf_pending = False
                self._self_paced_block()
                with self._lock:
                    dnf = self._dnf_pending
                    self._dnf_pending = False

                self._set_state(REST_POST)
                m = self._mark("REST_POST")
                trial["t_rest_post"] = m["t_lsl"] or m["t_wall"]
                if dnf:
                    trial["dnf"] = True
                    self._mark("DNF")
                trial["plan_s"] = round(trial["t_solve"] - trial["t_plan"], 3)
                trial["solve_s"] = round(trial["t_rest_post"] - trial["t_solve"], 3)
                self._emit(TrialCompleted(trial=dict(trial)))
                self._timed_block(cfg.rest_post)
                self.beeper.cue(times=1 if i < cfg.trials else 2)

                self.session_dict["trials"].append(trial)
                self._save()

                if i < cfg.trials:
                    self.scramble = self.scramble_fn(cfg.scramble_len, self.seed + i)
                    self._set_state(BREAK)
                    self._mark("BREAK")
                    trial["break_s"] = round(self._self_paced_block(), 1)
                    self._save()

                self.store.append_solve({
                    "subject": cfg.subject, "session": cfg.session, "trial": i,
                    "date": self.started.strftime("%Y-%m-%d"), "plan_s": trial["plan_s"],
                    "solve_s": trial["solve_s"], "dnf": int(trial["dnf"]),
                    "break_s": trial.get("break_s", ""), "scramble": trial["scramble"],
                })

            self._mark("SESSION_END")
            self.session_dict["completed"] = True
            self._set_state(DONE)
        except _Aborted:
            self._finish_aborted(None)
        except Exception as e:
            logging.exception("session thread crashed; applying abort semantics")
            self._finish_aborted(str(e))
        finally:
            if self._session_started:
                self.session_dict["ended"] = dt.datetime.now().isoformat()
                self._save()
                solved = [t for t in self.session_dict["trials"] if not t["dnf"]]
                self.store.append_session({
                    "subject": cfg.subject, "session": cfg.session,
                    "date": self.started.strftime("%Y-%m-%d %H:%M"),
                    "trials_completed": len(self.session_dict["trials"]),
                    "trials_planned": cfg.trials,
                    "mean_solve_s": round(sum(t["solve_s"] for t in solved) / len(solved), 2) if solved else "",
                    "best_solve_s": round(min(t["solve_s"] for t in solved), 2) if solved else "",
                    "completed": int(self.session_dict["completed"]),
                    "log": self.base, "comment": cfg.comment,
                })
            self._emit(SessionEnded(completed=self.session_dict["completed"],
                                    error=self.error))

    def _finish_aborted(self, error: Optional[str]):
        self.error = error
        if self._session_started:
            try:
                self._mark("ABORT")
            except Exception:
                logging.exception("failed to push ABORT marker")
        self._set_state(ABORTED)

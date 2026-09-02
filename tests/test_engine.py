import threading

import pytest

from app.server import engine
from app.server.engine import SessionConfig
from conftest import advance_when, run_happy_path, wait_for_state


def test_happy_path_states_and_markers(harness):
    s, rec, sink, beeper, store, clock = harness()
    run_happy_path(s, rec)
    assert s.state == engine.DONE
    assert rec.markers() == [
        "SESSION_START",
        "REST_PRE", "PLAN", "SOLVE", "REST_POST", "BREAK",
        "REST_PRE", "PLAN", "SOLVE", "REST_POST",
        "SESSION_END",
    ]
    assert rec.states() == [
        "configured",
        "rest_pre", "plan", "solve", "rest_post", "break",
        "rest_pre", "plan", "solve", "rest_post",
        "done",
    ]
    assert s.session_dict["completed"] is True
    assert len(s.session_dict["trials"]) == 2
    # beeps: one at end of each REST_PRE, one at end of REST_POST (double on last)
    assert beeper.cues == [1, 1, 1, 2]


def test_dnf_flag(harness):
    s, rec, sink, beeper, store, clock = harness()
    run_happy_path(s, rec, dnf_on={2})
    trials = s.session_dict["trials"]
    assert trials[0]["dnf"] is False
    assert trials[1]["dnf"] is True
    assert "DNF" in rec.markers()
    # DNF marker comes right after the trial's REST_POST marker
    names = rec.markers()
    assert names[names.index("DNF") - 1] == "REST_POST"


def test_dnf_rejected_outside_solve(harness):
    s, rec, *_ = harness()
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    ok, reason = s.flag_dnf()
    assert not ok and "solve" in reason
    s.abort()
    rec.ended.wait(5)


def test_abort_mid_block(harness):
    s, rec, sink, beeper, store, clock = harness()
    s.start()
    advance_when(s, engine.CONFIGURED)
    wait_for_state(s, engine.PLAN)
    ok, _ = s.abort()
    assert ok
    assert rec.ended.wait(5)
    assert s.state == engine.ABORTED
    assert rec.markers()[-1] == "ABORT"
    assert s.session_dict["completed"] is False
    # sessions.csv row still written with 0 completed trials
    rows = store.list_sessions()
    assert len(rows) == 1 and rows[0]["trials_completed"] == "0" and rows[0]["completed"] == "0"


def test_abort_before_start_writes_nothing(harness, tmp_path):
    s, rec, sink, beeper, store, clock = harness()
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    s.abort()
    assert rec.ended.wait(5)
    assert s.state == engine.ABORTED
    assert sink.pushed == []
    assert store.list_sessions() == []
    assert not list((tmp_path / "logs").iterdir())


def test_stale_from_state_rejected(harness):
    s, rec, *_ = harness()
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    ok, reason = s.advance("plan")
    assert not ok and "stale" in reason
    assert any(e.command == "advance" for e in rec.of(engine.CommandRejected))
    s.abort()
    rec.ended.wait(5)


def test_advance_rejected_during_timed_block(harness):
    s, rec, *_ = harness(config=SessionConfig(trials=1, rest_pre=5.0, rest_post=0.2,
                                              seed=1, no_lsl=True, no_beep=True))
    s.start()
    advance_when(s, engine.CONFIGURED)
    wait_for_state(s, engine.REST_PRE)
    ok, reason = s.advance(engine.REST_PRE)
    assert not ok and "timed" in reason
    s.abort()
    rec.ended.wait(5)


def test_dwell_time_guard(harness):
    s, rec, *_ = harness(dwell_s=0.5)
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    # immediately after entering the state, the fake clock has not moved
    ok, reason = s.advance(engine.CONFIGURED)
    assert not ok and "ignored" in reason
    # after the clock passes the dwell threshold it is accepted
    advance_when(s, engine.CONFIGURED)
    s.abort()
    rec.ended.wait(5)


def test_double_advance_second_rejected(harness):
    s, rec, *_ = harness()
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    # hold the engine lock so the first advance cannot be consumed
    # between the two calls (RLock: same-thread advance() still works)
    with s._lock:
        ok1, _ = s.advance(engine.CONFIGURED)
        ok2, reason2 = s.advance(engine.CONFIGURED)
    assert ok1
    assert not ok2 and "pending" in reason2
    s.abort()
    rec.ended.wait(5)


def test_dnf_after_solve_advance_rejected(harness):
    s, rec, *_ = harness()
    s.start()
    advance_when(s, engine.CONFIGURED)
    advance_when(s, engine.PLAN)
    wait_for_state(s, engine.SOLVE)
    with s._lock:
        ok, _ = s.advance(engine.SOLVE)
        assert ok
        # solve is ending: a late DNF must be rejected, never silently lost
        ok2, reason = s.flag_dnf()
    assert not ok2 and "ending" in reason
    advance_when(s, engine.BREAK)
    advance_when(s, engine.PLAN)
    advance_when(s, engine.SOLVE)
    assert rec.ended.wait(5)
    assert all(t["dnf"] is False for t in s.session_dict["trials"])


def test_ticks_emitted(harness):
    s, rec, *_ = harness()
    run_happy_path(s, rec)
    timed = [t for t in rec.of(engine.Tick) if t.remaining is not None]
    paced = [t for t in rec.of(engine.Tick) if t.elapsed is not None]
    assert timed and paced
    assert all(t.remaining > 0 for t in timed)


def test_trial_timing_fields(harness):
    s, rec, *_ = harness()
    run_happy_path(s, rec)
    t = s.session_dict["trials"][0]
    assert t["plan_s"] == round(t["t_solve"] - t["t_plan"], 3)
    assert t["solve_s"] == round(t["t_rest_post"] - t["t_solve"], 3)
    assert "break_s" in t
    assert "break_s" not in s.session_dict["trials"][-1]


def test_snapshot_reflects_state(harness):
    s, rec, *_ = harness()
    snap = s.snapshot()
    assert snap["state"] == engine.IDLE
    s.start()
    wait_for_state(s, engine.CONFIGURED)
    snap = s.snapshot()
    assert snap["state"] == engine.CONFIGURED
    assert snap["scramble"] == s.first_scramble
    assert snap["trials_planned"] == 2
    assert snap["config"]["subject"] == 1
    s.abort()
    assert rec.ended.wait(5)
    assert s.snapshot()["state"] == engine.ABORTED


def test_config_validation():
    with pytest.raises(ValueError):
        SessionConfig(trials=0)
    with pytest.raises(ValueError):
        SessionConfig(rest_pre=-1)
    with pytest.raises(ValueError):
        SessionConfig(subject=0)


def test_scrambles_deterministic_from_seed(harness):
    s1, rec1, *_ = harness()
    s2, rec2, *_ = harness()
    run_happy_path(s1, rec1)
    run_happy_path(s2, rec2)
    assert [t["scramble"] for t in s1.session_dict["trials"]] == \
           [t["scramble"] for t in s2.session_dict["trials"]]


def test_crash_in_marker_sink_applies_abort_semantics(harness):
    s, rec, sink, *_ = harness()
    calls = {"n": 0}
    orig = sink.push

    def failing_push(name):
        calls["n"] += 1
        if calls["n"] == 3:  # fail on the PLAN marker
            raise RuntimeError("sink exploded")
        return orig(name)

    sink.push = failing_push
    s.start()
    advance_when(s, engine.CONFIGURED)
    assert rec.ended.wait(5)
    assert s.state == engine.ABORTED
    ended = rec.of(engine.SessionEnded)[0]
    assert ended.error and "sink exploded" in ended.error

"""Smoke test: the refactored scripts/run_session.py, driven over a pipe like
the old one, produces the same JSON/CSV outputs as the pre-refactor fixture.

The script tree is copied into a temp dir so outputs never land in the repo.
"""
import json
import os
import shutil
import subprocess
import sys

from test_compat import FIXTURES, normalize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cli_end_to_end(tmp_path):
    for d in ("scripts", "app"):
        shutil.copytree(os.path.join(ROOT, d), tmp_path / d,
                        ignore=shutil.ignore_patterns("__pycache__", "web"))
    # start ENTER, t1: plan, solve, break, t2: plan, solve (+spares)
    stdin = "\n" * 8
    proc = subprocess.run(
        [sys.executable, "scripts/run_session.py", "--no-lsl", "--no-beep",
         "--subject", "1", "--session", "1", "--trials", "2",
         "--rest-pre", "0.2", "--rest-post", "0.2", "--seed", "42",
         "--comment", "fixture"],
        cwd=tmp_path, input=stdin, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Session complete" in proc.stdout
    assert ">> marker 1 SESSION_START" in proc.stdout
    assert ">> marker 2 SESSION_END" in proc.stdout

    logs = list((tmp_path / "logs").glob("*.json"))
    assert len(logs) == 1
    got = json.loads(logs[0].read_text())
    expected = json.loads(open(os.path.join(FIXTURES, "pre_refactor_log.json")).read())
    assert normalize(got) == normalize(expected)

    solves = (tmp_path / "data" / "solves.csv").read_text().splitlines()
    exp_solves = open(os.path.join(FIXTURES, "pre_refactor_solves.csv")).read().splitlines()
    assert solves[0] == exp_solves[0]
    assert len(solves) == len(exp_solves)
    sessions = (tmp_path / "data" / "sessions.csv").read_text().splitlines()
    exp_sessions = open(os.path.join(FIXTURES, "pre_refactor_sessions.csv")).read().splitlines()
    assert sessions[0] == exp_sessions[0]


def test_cli_auto_session_increment(tmp_path):
    for d in ("scripts", "app"):
        shutil.copytree(os.path.join(ROOT, d), tmp_path / d,
                        ignore=shutil.ignore_patterns("__pycache__", "web"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sessions.csv").write_text(
        "subject,session,date,trials_completed,trials_planned,mean_solve_s,"
        "best_solve_s,completed,log,comment\n"
        "1,3,2026-09-01 10:00,2,2,10.0,8.0,1,sub-01_ses-03_x,\n"
    )
    proc = subprocess.run(
        [sys.executable, "scripts/run_session.py", "--no-lsl", "--no-beep",
         "--subject", "1", "--trials", "1", "--rest-pre", "0.1",
         "--rest-post", "0.1", "--seed", "1"],
        cwd=tmp_path, input="\n" * 5, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "session 4" in proc.stdout
    logs = list((tmp_path / "logs").glob("*.json"))
    assert len(logs) == 1 and logs[0].name.startswith("sub-01_ses-04_")

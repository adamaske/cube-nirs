import json

import pytest

from app.server.store import Store


def test_next_session_number_empty(tmp_path):
    assert Store(str(tmp_path)).next_session_number(1) == 1


def test_next_session_number_increments_per_subject(tmp_path):
    store = Store(str(tmp_path))
    store.append_session({"subject": 1, "session": 3, "date": "x",
                          "trials_completed": 1, "trials_planned": 1,
                          "mean_solve_s": 1, "best_solve_s": 1,
                          "completed": 1, "log": "a", "comment": ""})
    store.append_session({"subject": 2, "session": 7, "date": "x",
                          "trials_completed": 1, "trials_planned": 1,
                          "mean_solve_s": 1, "best_solve_s": 1,
                          "completed": 1, "log": "b", "comment": ""})
    assert store.next_session_number(1) == 4
    assert store.next_session_number(2) == 8
    assert store.next_session_number(3) == 1


def test_save_and_read_log_roundtrip(tmp_path):
    store = Store(str(tmp_path))
    store.save_json("sub-01_ses-01_x", {"a": 1})
    assert store.read_log("sub-01_ses-01_x") == {"a": 1}
    assert json.load(open(tmp_path / "logs" / "sub-01_ses-01_x.json")) == {"a": 1}


def test_read_log_rejects_path_traversal(tmp_path):
    store = Store(str(tmp_path))
    for bad in ("../secrets", "..", ".hidden", "a/b"):
        with pytest.raises(FileNotFoundError):
            store.read_log(bad)


def test_csv_headers_written_once(tmp_path):
    store = Store(str(tmp_path))
    row = {"subject": 1, "session": 1, "trial": 1, "date": "d", "plan_s": 1,
           "solve_s": 2, "dnf": 0, "break_s": "", "scramble": "R U"}
    store.append_solve(row)
    store.append_solve(row)
    lines = open(store.solves_csv).read().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("subject,session,trial,")

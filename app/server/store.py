"""File I/O for session outputs. The only module that knows the repo layout.

Writes logs/<base>.json (after every marker, as the CLI always did) and
appends data/solves.csv / data/sessions.csv. Also the read side for the
dashboard: list_sessions(), read_log(), next_session_number().
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Store:
    def __init__(self, root: str = ROOT):
        self.log_dir = os.path.join(root, "logs")
        self.data_dir = os.path.join(root, "data")
        self.solves_csv = os.path.join(self.data_dir, "solves.csv")
        self.sessions_csv = os.path.join(self.data_dir, "sessions.csv")
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    # ---- write side (used by the engine) ---------------------------------- #
    def save_json(self, base: str, session: dict):
        with open(os.path.join(self.log_dir, base + ".json"), "w") as f:
            json.dump(session, f, indent=2)

    def _append_csv(self, path: str, row: dict):
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)

    def append_solve(self, row: dict):
        self._append_csv(self.solves_csv, row)

    def append_session(self, row: dict):
        self._append_csv(self.sessions_csv, row)

    # ---- read side (dashboard / setup) ------------------------------------ #
    def next_session_number(self, subject: int) -> int:
        if os.path.exists(self.sessions_csv):
            with open(self.sessions_csv) as f:
                rows = [r for r in csv.DictReader(f) if int(r["subject"]) == subject]
            if rows:
                return max(int(r["session"]) for r in rows) + 1
        return 1

    def list_sessions(self) -> list[dict]:
        if not os.path.exists(self.sessions_csv):
            return []
        with open(self.sessions_csv) as f:
            return list(csv.DictReader(f))

    def list_solves(self) -> list[dict]:
        if not os.path.exists(self.solves_csv):
            return []
        with open(self.solves_csv) as f:
            return list(csv.DictReader(f))

    def read_log(self, base: str) -> dict:
        if os.sep in base or base.startswith(".") or "/" in base:
            raise FileNotFoundError(base)
        with open(os.path.join(self.log_dir, base + ".json")) as f:
            return json.load(f)

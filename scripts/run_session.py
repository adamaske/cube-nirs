#!/usr/bin/env python3
"""Rubik's Cube fNIRS session runner.

Block design per trial:
    REST_PRE (20 s, timed) -> PLAN (self-paced, ENTER) -> SOLVE (self-paced, ENTER)
    -> REST_POST (45 s, timed) -> BREAK (free length, scramble the cube; ends on ENTER)

Markers are pushed as int32 samples on an LSL stream (default name "Trigger",
type "Markers").  Codes are defined in triggers.py.

Usage:
    python scripts/run_session.py --subject 1 --session 1 --trials 5
    python scripts/run_session.py --no-lsl          # dry run without pylsl
    python scripts/run_session.py --scramble-len 25 --rest-post 60

Controls during a session:
    ENTER  advance a self-paced block (PLAN -> SOLVE -> REST_POST) or end the break
    d      (typed before ENTER at the end of SOLVE) flag the solve as DNF
    Ctrl-C abort the session (ABORT marker is pushed, log is still written)
"""
import argparse
import csv
import datetime as dt
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from triggers import TRIGGERS, code  # noqa: E402
import scramble as scramble_gen  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
DATA_DIR = os.path.join(ROOT, "data")
SOLVES_CSV = os.path.join(DATA_DIR, "solves.csv")
SESSIONS_CSV = os.path.join(DATA_DIR, "sessions.csv")


# --------------------------------------------------------------------------- #
# Marker outlet
# --------------------------------------------------------------------------- #
class MarkerOutlet:
    def __init__(self, enabled: bool, name: str, stype: str, source_id: str):
        self.enabled = enabled
        self.outlet = None
        self.lsl_clock = None
        if enabled:
            from pylsl import StreamInfo, StreamOutlet, local_clock
            info = StreamInfo(name=name, type=stype, channel_count=1,
                              nominal_srate=0, channel_format="int32",
                              source_id=source_id)
            self.outlet = StreamOutlet(info)
            self.lsl_clock = local_clock
            logging.info(f"LSL outlet '{name}' ({stype}, int32) source_id={source_id}")
        else:
            logging.warning("LSL disabled (--no-lsl): markers are only logged")

    def push(self, name: str) -> dict:
        c = code(name)
        t_wall = time.time()
        t_lsl = self.lsl_clock() if self.lsl_clock else None
        if self.outlet is not None:
            self.outlet.push_sample([c])
        logging.info(f"MARKER {c:3d} {name}")
        print(f"\n  >> marker {c} {name}")
        return {"code": c, "name": name, "t_wall": t_wall, "t_lsl": t_lsl}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def countdown(label: str, seconds: float, next_label: str):
    """Blocking timed block with a live countdown."""
    t0 = time.time()
    while True:
        remaining = seconds - (time.time() - t0)
        if remaining <= 0:
            print()
            return
        print(f"  [{label}] {remaining:6.1f} s left -> {next_label}   ", end="\r", flush=True)
        time.sleep(0.1)


def break_timer() -> float:
    """Inter-trial break of free length. Shows elapsed time; ends on ENTER.
    Returns the actual break duration in seconds."""
    import threading
    t0 = time.time()
    done = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), done.set()), daemon=True).start()
    while not done.is_set():
        print(f"  [BREAK] {time.time() - t0:6.1f} s elapsed. Scramble, put the cube down, press ENTER to start the next trial   ",
              end="\r", flush=True)
        done.wait(0.1)
    print()
    return time.time() - t0


def wait_enter(prompt: str) -> str:
    return input(prompt).strip().lower()


def append_csv(path: str, row: dict):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--subject", type=int, default=1)
    p.add_argument("--session", type=int, default=None, help="session number (default: auto-increment from data/sessions.csv)")
    p.add_argument("--trials", type=int, default=5, help="number of solves (default 5)")
    p.add_argument("--rest-pre", type=float, default=20.0)
    p.add_argument("--rest-post", type=float, default=45.0)
    p.add_argument("--scramble-len", type=int, default=20)
    p.add_argument("--seed", type=int, default=None, help="RNG seed for scrambles (default: derived from timestamp)")
    p.add_argument("--stream-name", default="Trigger")
    p.add_argument("--stream-type", default="Markers")
    p.add_argument("--source-id", default="cube-nirs")
    p.add_argument("--no-lsl", action="store_true", help="dry run without pushing LSL markers")
    p.add_argument("--comment", default="")
    args = p.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if args.session is None:
        args.session = 1
        if os.path.exists(SESSIONS_CSV):
            with open(SESSIONS_CSV) as f:
                rows = [r for r in csv.DictReader(f) if int(r["subject"]) == args.subject]
            if rows:
                args.session = max(int(r["session"]) for r in rows) + 1

    started = dt.datetime.now()
    stamp = started.strftime("%Y%m%d_%H%M%S")
    base = f"sub-{args.subject:02d}_ses-{args.session:02d}_{stamp}"
    seed = args.seed if args.seed is not None else int(started.timestamp())

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(LOG_DIR, base + ".log")), logging.StreamHandler()],
    )
    logging.getLogger().handlers[1].setLevel(logging.WARNING)

    session = {
        "subject": args.subject, "session": args.session, "started": started.isoformat(),
        "params": {k: v for k, v in vars(args).items()}, "seed": seed,
        "stream": {"name": args.stream_name, "type": args.stream_type, "source_id": args.source_id},
        "triggers": {c: n for c, (n, _) in TRIGGERS.items()},
        "markers": [], "trials": [], "completed": False,
    }

    def save():
        with open(os.path.join(LOG_DIR, base + ".json"), "w") as f:
            json.dump(session, f, indent=2)

    print("=" * 70)
    print(f" Rubik's Cube fNIRS  |  subject {args.subject}  session {args.session}  |  {started:%Y-%m-%d %H:%M}")
    print(f" {args.trials} trials: REST {args.rest_pre:.0f}s -> PLAN -> SOLVE -> REST {args.rest_post:.0f}s -> BREAK (ENTER)")
    print(f" LSL stream: {args.stream_name} ({args.stream_type})" + ("  [DISABLED]" if args.no_lsl else ""))
    print("=" * 70)

    outlet = MarkerOutlet(not args.no_lsl, args.stream_name, args.stream_type, args.source_id)

    def mark(name):
        m = outlet.push(name)
        session["markers"].append(m)
        save()
        return m

    # Scramble is done BEFORE the first trial (outside recording), so print it now.
    first_scramble = scramble_gen.generate(args.scramble_len, seed)
    print(f"\nScramble the cube now:\n\n    {first_scramble}\n")
    print("Make sure Aurora is recording and the 'Trigger' LSL stream is selected.")
    wait_enter("Press ENTER when the cube is scrambled and on the table to start the session...")

    completed_trials = 0
    try:
        mark("SESSION_START")
        scramble = first_scramble
        for i in range(1, args.trials + 1):
            trial = {"trial": i, "scramble": scramble, "dnf": False}
            print(f"\n----- Trial {i}/{args.trials} -----")

            m = mark("REST_PRE")
            trial["t_rest_pre"] = m["t_lsl"] or m["t_wall"]
            countdown("REST", args.rest_pre, "PLAN")

            m = mark("PLAN")
            trial["t_plan"] = m["t_lsl"] or m["t_wall"]
            wait_enter("  [PLAN] Pick up the cube and inspect. Press ENTER at your FIRST TURN...")

            m = mark("SOLVE")
            trial["t_solve"] = m["t_lsl"] or m["t_wall"]
            ans = wait_enter("  [SOLVE] Solving... Press ENTER when solved and the cube is DOWN (type d + ENTER for DNF)...")

            m = mark("REST_POST")
            trial["t_rest_post"] = m["t_lsl"] or m["t_wall"]
            if ans.startswith("d"):
                trial["dnf"] = True
                mark("DNF")
            trial["plan_s"] = round(trial["t_solve"] - trial["t_plan"], 3)
            trial["solve_s"] = round(trial["t_rest_post"] - trial["t_solve"], 3)
            print(f"  plan {trial['plan_s']:.1f} s | solve {trial['solve_s']:.1f} s" + ("  (DNF)" if trial["dnf"] else ""))
            countdown("REST", args.rest_post, "BREAK" if i < args.trials else "END")

            session["trials"].append(trial)
            completed_trials = i
            save()

            if i < args.trials:
                scramble = scramble_gen.generate(args.scramble_len, seed + i)
                mark("BREAK")
                print(f"\n  [BREAK] Scramble the cube:\n\n      {scramble}\n")
                trial["break_s"] = round(break_timer(), 1)
                save()

            append_csv(SOLVES_CSV, {
                "subject": args.subject, "session": args.session, "trial": i,
                "date": started.strftime("%Y-%m-%d"), "plan_s": trial["plan_s"],
                "solve_s": trial["solve_s"], "dnf": int(trial["dnf"]),
                "break_s": trial.get("break_s", ""), "scramble": trial["scramble"],
            })

        mark("SESSION_END")
        session["completed"] = True
        print("\nSession complete. Stop the recording now.")
    except KeyboardInterrupt:
        print("\nAborted.")
        mark("ABORT")
    finally:
        session["ended"] = dt.datetime.now().isoformat()
        save()
        solved = [t for t in session["trials"] if not t["dnf"]]
        append_csv(SESSIONS_CSV, {
            "subject": args.subject, "session": args.session, "date": started.strftime("%Y-%m-%d %H:%M"),
            "trials_completed": completed_trials, "trials_planned": args.trials,
            "mean_solve_s": round(sum(t["solve_s"] for t in solved) / len(solved), 2) if solved else "",
            "best_solve_s": round(min(t["solve_s"] for t in solved), 2) if solved else "",
            "completed": int(session["completed"]), "log": base, "comment": args.comment,
        })
        print(f"Log written: logs/{base}.json")


if __name__ == "__main__":
    main()

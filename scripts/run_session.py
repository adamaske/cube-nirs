#!/usr/bin/env python3
"""Rubik's Cube fNIRS session runner (terminal fallback for the GUI).

Block design per trial:
    REST_PRE (20 s, timed) -> PLAN (self-paced, ENTER) -> SOLVE (self-paced, ENTER)
    -> REST_POST (45 s, timed) -> BREAK (free length, scramble the cube; ends on ENTER)

Markers are pushed as int32 samples on an LSL stream (default name "Trigger",
type "Markers").  Codes are defined in triggers.py.

Usage:
    python scripts/run_session.py --subject 1 --session 1 --trials 5
    python scripts/run_session.py --no-lsl          # dry run without pylsl
    python scripts/run_session.py --scramble-len 25 --rest-post 60

Audio: a 1 kHz beep (200 ms) sounds when a timed rest ends (start of PLAN,
start of BREAK); a double beep marks the end of the session. --no-beep disables it.

Controls during a session:
    ENTER  advance a self-paced block (PLAN -> SOLVE -> REST_POST) or end the break
    d      (typed before ENTER at the end of SOLVE) flag the solve as DNF
    Ctrl-C abort the session (ABORT marker is pushed, log is still written)

This is a thin wrapper over app.server.engine; the GUI (`python -m app.server`)
drives the exact same engine.
"""
import argparse
import logging
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.server import engine  # noqa: E402
from app.server.beeper import Beeper  # noqa: E402
from app.server.engine import Session, SessionConfig  # noqa: E402
from app.server.lsl_out import MarkerOutlet, NullOutlet  # noqa: E402
from app.server.store import Store  # noqa: E402
from scripts import scramble as scramble_gen  # noqa: E402


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
    p.add_argument("--no-beep", action="store_true", help="disable the 1 kHz audio cue")
    p.add_argument("--comment", default="")
    args = p.parse_args()

    store = Store(ROOT)
    if args.session is None:
        args.session = store.next_session_number(args.subject)

    config = SessionConfig(
        subject=args.subject, session=args.session, trials=args.trials,
        rest_pre=args.rest_pre, rest_post=args.rest_post,
        scramble_len=args.scramble_len, seed=args.seed,
        stream_name=args.stream_name, stream_type=args.stream_type,
        source_id=args.source_id, no_lsl=args.no_lsl, no_beep=args.no_beep,
        comment=args.comment,
    )

    ended = threading.Event()
    printer_lock = threading.Lock()

    def render(ev):
        with printer_lock:
            _render(ev)

    def _render(ev):
        cfg = config
        if isinstance(ev, engine.MarkerPushed):
            print(f"\n  >> marker {ev.code} {ev.name}")
            if ev.name == "PLAN":
                print("  [PLAN] Pick up the cube and inspect. Press ENTER at your FIRST TURN...", end="", flush=True)
            elif ev.name == "SOLVE":
                print("  [SOLVE] Solving... Press ENTER when solved and the cube is DOWN (type d + ENTER for DNF)...", end="", flush=True)
            elif ev.name == "BREAK":
                print(f"\n  [BREAK] Scramble the cube:\n\n      {session.scramble}\n")
        elif isinstance(ev, engine.StateChanged):
            if ev.state == engine.REST_PRE:
                print(f"\n----- Trial {ev.trial}/{cfg.trials} -----")
            elif ev.state == engine.DONE:
                print("\nSession complete. Stop the recording now.")
            elif ev.state == engine.ABORTED:
                print("\nAborted.")
        elif isinstance(ev, engine.Tick):
            if ev.remaining is not None:
                nxt = "PLAN" if ev.state == engine.REST_PRE else ("BREAK" if ev.trial < cfg.trials else "END")
                print(f"  [REST] {ev.remaining:6.1f} s left -> {nxt}   ", end="\r", flush=True)
            elif ev.state == engine.BREAK:
                print(f"  [BREAK] {ev.elapsed:6.1f} s elapsed. Scramble, put the cube down, press ENTER to start the next trial   ",
                      end="\r", flush=True)
        elif isinstance(ev, engine.TrialCompleted):
            t = ev.trial
            print(f"  plan {t['plan_s']:.1f} s | solve {t['solve_s']:.1f} s" + ("  (DNF)" if t["dnf"] else ""))
        elif isinstance(ev, engine.SessionEnded):
            ended.set()

    import datetime as dt
    started = dt.datetime.now()
    base = f"sub-{args.subject:02d}_ses-{args.session:02d}_{started:%Y%m%d_%H%M%S}"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(store.log_dir, base + ".log")),
                  logging.StreamHandler()],
    )
    logging.getLogger().handlers[1].setLevel(logging.WARNING)

    try:
        outlet = NullOutlet() if args.no_lsl else MarkerOutlet(args.stream_name, args.stream_type, args.source_id)
    except Exception as e:
        print(f"ERROR: could not create LSL outlet: {e}", file=sys.stderr)
        print("Refusing to run unmarked. Use --no-lsl for an explicit dry run.", file=sys.stderr)
        sys.exit(1)

    session = Session(
        config,
        marker_sink=outlet,
        beeper=engine.NullBeeper() if args.no_beep else Beeper(),
        store=store,
        scramble_fn=scramble_gen.generate,
        emit=render,
        started=started,
        # the old input()-driven CLI had no double-advance guard; a single
        # keyboard doesn't need one, and dwell would inflate plan_s/solve_s
        dwell_s=0.0,
    )

    print("=" * 70)
    print(f" Rubik's Cube fNIRS  |  subject {args.subject}  session {args.session}  |  {session.started:%Y-%m-%d %H:%M}")
    print(f" {args.trials} trials: REST {args.rest_pre:.0f}s -> PLAN -> SOLVE -> REST {args.rest_post:.0f}s -> BREAK (ENTER)")
    print(f" LSL stream: {args.stream_name} ({args.stream_type})" + ("  [DISABLED]" if args.no_lsl else ""))
    print("=" * 70)
    print(f"\nScramble the cube now:\n\n    {session.first_scramble}\n")
    print("Make sure Aurora is recording and the 'Trigger' LSL stream is selected.")
    print("Press ENTER when the cube is scrambled and on the table to start the session...", end="", flush=True)

    def stdin_reader():
        """Feed each stdin line to the engine as an advance (buffered like the
        old input() prompts: a line waits until a self-paced block accepts it)."""
        for line in sys.stdin:
            want_dnf = line.strip().lower().startswith("d")
            while not ended.is_set():
                st = session.state
                if st in engine.SELF_PACED:
                    if want_dnf and st == engine.SOLVE:
                        session.flag_dnf()
                    ok, _reason = session.advance(st)
                    if ok:
                        break
                time.sleep(0.05)
            if ended.is_set():
                return

    threading.Thread(target=stdin_reader, daemon=True).start()

    session.start()
    try:
        while not ended.wait(0.2):
            pass
    except KeyboardInterrupt:
        session.abort()
        ended.wait(10)
    print(f"Log written: logs/{session.base}.json")


if __name__ == "__main__":
    main()

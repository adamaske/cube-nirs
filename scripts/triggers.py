"""Trigger (event marker) table for the Rubik's Cube fNIRS project.

This is the single source of truth for the integer codes pushed on the LSL
stream.  `protocol/protocol.tex` documents the same table; if you change it
here, regenerate the tex table with `python scripts/make_tables.py`.

Convention: tens digit = phase, ones digit = sub-event.
"""

TRIGGERS = {
    # code : (name, meaning)
    1:  ("SESSION_START", "Session begins; recording should already be running"),
    2:  ("SESSION_END",   "Session ends; stop the recording after this"),

    10: ("REST_PRE",      "Pre-trial rest onset (eyes open, cube on table, 20 s)"),
    20: ("PLAN",          "Planning/inspection onset: subject picks up the cube and inspects, no turning"),
    30: ("SOLVE",         "Solve onset: first turn allowed. Also marks end of PLAN"),
    40: ("REST_POST",     "Post-trial rest onset: cube put down. Also marks end of SOLVE (solve time = t40 - t30)"),

    50: ("BREAK",         "Inter-trial break onset (2 min). Subject scrambles the cube during this"),

    60: ("DNF",           "Trial flagged as not properly solved / aborted by the subject"),
    99: ("ABORT",         "Session aborted by the experimenter"),
}

NAME_TO_CODE = {name: code for code, (name, _) in TRIGGERS.items()}


def code(name: str) -> int:
    return NAME_TO_CODE[name]


if __name__ == "__main__":
    for c, (n, m) in TRIGGERS.items():
        print(f"{c:3d}  {n:14s} {m}")

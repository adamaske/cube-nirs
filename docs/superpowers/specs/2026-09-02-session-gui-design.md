# Session GUI — Design

**Date:** 2026-09-02
**Status:** approved design, pre-implementation

## Goal

Replace the terminal-only session runner with a GUI serving three roles:
an experimenter control panel, a subject-facing display (second monitor,
same PC), and a read-only dashboard of past sessions. The CLI runner is
kept as a fallback. Everything timing-critical (LSL markers, timers,
beeps, logging) stays in Python, unchanged in behavior.

## Architecture

Python backend (FastAPI) + browser frontend (Svelte), one process, one
machine (Windows 11 acquisition PC).

```
scripts/run_session.py        thin CLI wrapper over the engine (kept)
app/
  server/
    engine.py                 session state machine (extracted from run_session.py)
    lsl_out.py                MarkerOutlet (moved, behavior unchanged)
    store.py                  logs/*.json + data/*.csv read/write
    main.py                   FastAPI: REST + WebSocket + static files
  web/                        Svelte source; built output committed in app/web/dist/
```

- Launch: `python -m app.server` → serves `http://localhost:8765/`
  (control panel) and `/subject` (subject display, F11 on monitor 2)
  and `/dashboard`.
- The acquisition PC needs only Python; Node is a dev-machine-only
  dependency because `app/web/dist/` is committed.
- New Python deps: `fastapi`, `uvicorn` (added to requirements.txt).

## Engine (`engine.py`)

A `Session` object owning the block state machine, running its loop in a
background thread. Interface: `start(config)`, `advance(from_state)`,
`flag_dnf()`, `abort()`, plus an event callback fired on every state
change, marker push, and timer tick.

- States: `idle`, `configured` (scramble shown, awaiting start),
  `rest_pre`, `plan`, `solve`, `rest_post`, `break`, `done`, `aborted`.
- Block flow, marker codes (`triggers.py`), beep points, JSON log
  schema, and CSV schemas are identical to the current
  `run_session.py`. Output byte-compatibility is a test requirement.
- Timed blocks (REST_PRE, REST_POST) run on the engine's own clock.
  The frontend only renders; browser clocks never touch data.
- Self-paced blocks wait on an advance event instead of blocking
  `input()`. DNF is an explicit `flag_dnf()` call, valid during SOLVE.
- One session at a time; `start` while a session runs is rejected.
- `t_wall`/`t_lsl` are taken in the engine at marker push, as today.

### Double-advance guards

Multiple input sources (two windows' keyboards, subject touch button)
could fire `advance` twice within milliseconds and skip a block.

1. Every `advance` carries the state it believes it is advancing from;
   the engine drops mismatches.
2. A 500 ms minimum dwell time per self-paced state absorbs two
   advances that both carry the still-current state.
3. Ignored advances are logged and shown in the control panel event log.

## API

### WebSocket (one, shared by all views)

Server → clients:
- `state` — full snapshot: state, trial i/N, scramble, config,
  per-trial results so far. Sent on connect and on every transition, so
  any view opened or refreshed mid-session renders correctly. The
  frontend holds no authoritative state.
- `tick` — server clock + remaining/elapsed, ~5 Hz, only during a
  session.

Client → server: `start`, `advance` (with `from` state), `dnf`,
`abort`. Server validates against current state; invalid commands are
ignored and logged, never fatal.

### REST

- `GET/POST /api/config` — default session parameters.
- `GET /api/next-session?subject=N` — auto-increment from sessions.csv.
- `GET /api/sessions`, `GET /api/sessions/{log}` — dashboard reads of
  `data/*.csv` and `logs/*.json`.

## Control panel (`/`)

- **Setup zone** (idle): subject, trials, rest durations, scramble
  length, seed, session number (prefilled from auto-increment,
  overridable), comment, stream name, no-LSL / no-beep toggles,
  advance-source
  mode (`experimenter | subject | both`, default `both`); LSL outlet
  status line; first scramble shown pre-start (scramble → confirm
  Aurora recording → start), matching today's flow.
- **Live zone**: current-state banner, trial i/N, countdown/elapsed,
  current scramble, marker event log, per-trial results table
  (plan_s, solve_s, DNF, break_s) filling in live.
- **Controls**: large ADVANCE button + spacebar; DNF button enabled
  only during SOLVE; ABORT behind a confirmation dialog (the one place
  a confirm is correct — aborting a recording is unrecoverable).

## Subject display (`/subject`)

The display is itself a visual stimulus and occipital cortex is being
recorded, so it is deliberately minimal and static — not a mirror of
the control panel:

- **REST_PRE / REST_POST**: static fixation cross, neutral mid-grey
  background. No numbers, no motion. The beep cues transitions.
- **PLAN / SOLVE**: one static word ("PLAN" / "SOLVE").
- **BREAK**: scramble in large type, elapsed time (break is
  unrecorded), big touch ADVANCE button.
- **DONE**: "Session complete."
- Constant background luminance across all in-trial states; no theme
  flashes or layout shifts.
- In `subject`/`both` advance mode, the ADVANCE button also appears
  during PLAN ("press at first turn") and SOLVE ("press when cube is
  down"), with adapted labels.

## Dashboard (`/dashboard`)

Read-only; only reads files, so harmless during a live session.

- Sessions table from `data/sessions.csv`; row click opens session
  detail from its `logs/*.json` (marker timeline, per-trial breakdown).
- Trend chart: solve time per trial across sessions, plan time as a
  second series, DNFs marked distinctly. Inline SVG, no chart library.
- No editing. Data correction stays a manual CSV/git operation.

## Error handling

- LSL outlet creation failure → session refuses to arm; error shown in
  setup zone. Running unmarked silently is the worst failure mode.
  `--no-lsl` remains an explicit dry-run toggle.
- Browser crash/refresh mid-session → engine unaffected (server-side,
  timers included); reconnect gets a snapshot. All views dead → session
  still runs to completion (markers, beeps, logs are server-side).
- Server crash → same guarantee as today: JSON saved after every
  marker, CSVs appended per trial; at most the in-flight block is lost.
- Multiple control panels → all views are equal peers of one broadcast
  state.

## Testing

- **Engine unit tests** (bulk of the suite): fake clock, LSL/beep
  stubs. Happy path, DNF, abort mid-block, double-advance rejection,
  dwell-time guard, stale-`from` rejection, session auto-increment,
  and JSON/CSV byte-compatibility against fixtures generated from the
  pre-refactor code.
- **WebSocket integration tests** (FastAPI TestClient): snapshot on
  connect, advance validation, reconnect mid-session.
- **CLI parity**: `run_session.py --no-lsl --no-beep` smoke test, same
  outputs as before the refactor.
- Frontend is deliberately too thin to carry logic; manual checklist
  for the two displays.

## Out of scope

- Remote/second-device subject display (architecture permits it later;
  nothing built for it now).
- Editing experiment data from the GUI.
- Multi-session concurrency, authentication, packaging as an exe.

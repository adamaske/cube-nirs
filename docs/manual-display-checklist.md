# Manual checklist — control panel & subject display

The frontend is deliberately too thin to carry logic, so it is verified by
hand before a recording day. Run `python -m app.server`, open `/` on monitor 1
and `/subject` (F11) on monitor 2, and walk through a `--no-lsl`-style dry
run (no LSL box needed: tick "no LSL (dry run)" and "no beep" off).

## Control panel (`/`)

- [ ] Setup zone shows all fields; session number prefills from
      `data/sessions.csv` and updates when subject changes; typing a session
      number stops the auto-prefill.
- [ ] LSL status line shows green/red correctly (red on a machine without pylsl).
- [ ] ARM SESSION → banner shows READY with the first scramble; the same
      scramble appears in the JSON log afterwards.
- [ ] START SESSION button and spacebar both advance; two rapid presses
      produce one advance plus a logged rejection in the event log.
- [ ] REST countdowns tick down (~5 Hz) and match the configured durations.
- [ ] DNF button is disabled except during SOLVE; pressing it shows the ✓
      and the trial row goes red when completed.
- [ ] ABORT asks for confirmation; cancel does nothing; confirm pushes the
      ABORT marker and ends the session.
- [ ] Trial table fills in live (plan_s, solve_s, DNF, break_s).
- [ ] Refresh the tab mid-session: it reconnects and re-renders the current
      state; the session is unaffected.

## Subject display (`/subject`)

- [ ] REST (pre/post): static fixation cross on mid-grey; no numbers, no motion.
- [ ] PLAN / SOLVE: single static word; background luminance unchanged.
- [ ] BREAK: scramble in large type, elapsed seconds, big ADVANCE button.
- [ ] Advance-source mode: in `experimenter` mode no buttons appear; in
      `subject`/`both` mode buttons appear during PLAN ("press at first
      turn"), SOLVE ("press when cube is down"), BREAK.
- [ ] Touch/click on the subject button advances exactly one block.
- [ ] DONE shows "Session complete."; no flashes or layout shifts between states.

## Dashboard (`/dashboard`)

- [ ] Sessions table lists `data/sessions.csv`; row click opens marker
      timeline and per-trial breakdown from the JSON log.
- [ ] Trend chart shows solve and plan series; DNF trials marked with ✕.
- [ ] Opening the dashboard during a live session does not disturb it.

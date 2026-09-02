"""Real Beeper for the engine: wraps the 1 kHz cue in scripts/beep.py.
Inject engine.NullBeeper instead for --no-beep."""
from scripts import beep as beep_mod


class Beeper:
    def cue(self, times: int = 1):
        beep_mod.beep(times=times)

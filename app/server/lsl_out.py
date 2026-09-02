"""LSL marker outlet (moved from scripts/run_session.py, behavior unchanged).

`MarkerOutlet` pushes int32 samples on an LSL stream. `NullOutlet` is the
--no-lsl stand-in so the engine never branches on whether LSL is enabled.
Both return the same marker dict; `t_lsl` is None without LSL.
"""
import logging
import time

from scripts.triggers import code


class MarkerOutlet:
    def __init__(self, name: str, stype: str, source_id: str):
        from pylsl import StreamInfo, StreamOutlet, local_clock
        info = StreamInfo(name=name, type=stype, channel_count=1,
                          nominal_srate=0, channel_format="int32",
                          source_id=source_id)
        self.outlet = StreamOutlet(info)
        self.lsl_clock = local_clock
        logging.info(f"LSL outlet '{name}' ({stype}, int32) source_id={source_id}")

    def push(self, name: str) -> dict:
        c = code(name)
        t_wall = time.time()
        t_lsl = self.lsl_clock()
        self.outlet.push_sample([c])
        logging.info(f"MARKER {c:3d} {name}")
        return {"code": c, "name": name, "t_wall": t_wall, "t_lsl": t_lsl}


class NullOutlet:
    def __init__(self):
        logging.warning("LSL disabled (--no-lsl): markers are only logged")

    def push(self, name: str) -> dict:
        c = code(name)
        t_wall = time.time()
        logging.info(f"MARKER {c:3d} {name}")
        return {"code": c, "name": name, "t_wall": t_wall, "t_lsl": None}

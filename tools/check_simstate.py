#!/usr/bin/env python3
"""Debug helper: start SITL instance 2 and confirm SIM_STATE (true position) arrives."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt import mission  # noqa: E402
from dtt.flight import Vehicle  # noqa: E402
from dtt.sitl import Sitl  # noqa: E402

s = Sitl(os.path.expanduser("~/dtt-work/check_simstate"), mission.SITES["delhi"], instance=2)
s.start()
try:
    v = Vehicle(s.port)
    end = time.time() + 10
    n = 0
    while time.time() < end:
        msg = v.pump()
        if msg is not None and msg.get_type() == "SIM_STATE":
            n += 1
    print("SIM_STATE messages in 10 s:", n, "last true alt:", v.true_alt_m)
finally:
    s.stop()

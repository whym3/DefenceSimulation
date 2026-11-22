#!/usr/bin/env python3
"""Debug helper: start SITL, upload the patrol mission, print every mission/status message."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt import mission  # noqa: E402
from dtt.flight import Vehicle, _CMDS, _FRAMES, mavlink  # noqa: E402
from dtt.sitl import Sitl  # noqa: E402

home = mission.SITES["delhi"]
s = Sitl(os.path.expanduser("~/dtt-work/debug"), home, instance=1)
s.start()
try:
    v = Vehicle(s.port)
    items = mission.patrol_square(home)
    ts, tc = v.m.target_system, v.m.target_component
    print("target", ts, tc)
    end = time.time() + 8
    while time.time() < end:
        msg = v.m.recv_match(type="STATUSTEXT", blocking=True, timeout=1)
        if msg:
            print("STATUS", msg.text)
    v.m.mav.mission_count_send(ts, tc, len(items), mavlink.MAV_MISSION_TYPE_MISSION)
    end = time.time() + 15
    while time.time() < end:
        msg = v.m.recv_match(blocking=True, timeout=1)
        if msg is None:
            continue
        t = msg.get_type()
        if t.startswith("MISSION") or t == "STATUSTEXT":
            print(t, msg.to_dict())
        if t in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
            it = items[msg.seq]
            v.m.mav.mission_item_int_send(
                ts, tc, msg.seq, _FRAMES[it["frame"]], _CMDS[it["cmd"]], 0, 1, 0, 0, 0, 0,
                int(it["lat"] * 1e7), int(it["lon"] * 1e7), float(it["alt"]),
                mavlink.MAV_MISSION_TYPE_MISSION)
        if t == "MISSION_ACK" and msg.mission_type == 0:
            break
finally:
    s.stop()

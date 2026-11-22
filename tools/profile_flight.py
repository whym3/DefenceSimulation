#!/usr/bin/env python3
"""Times each phase of one baseline flight, to find what limits flights per minute.

Usage: profile_flight.py [speedup] [instance]   (default 120, instance 14)
Mirrors run_one.fly() without the fault, printing wall-clock seconds per phase.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt import analyze, conditions, faults, mission  # noqa: E402
from dtt.flight import Vehicle  # noqa: E402
from dtt.sitl import Sitl  # noqa: E402

speedup = int(sys.argv[1]) if len(sys.argv) > 1 else 120
instance = int(sys.argv[2]) if len(sys.argv) > 2 else 14
t0 = time.time()
marks = []


def mark(name):
    marks.append((name, time.time()))


home = conditions.home("delhi")
work = os.path.expanduser("~/dtt-work/profile_%d" % instance)
shutil.rmtree(work, ignore_errors=True)
s = Sitl(work, home, instance=instance, speedup=speedup)
s.start()
mark("sitl started")
msgs = 0
try:
    v = Vehicle(s.port)
    mark("connected")
    v.wait_ready()
    mark("EKF using GPS (sim %.0f s)" % (v.sim_time_ms / 1000))
    for k, val in list(mission.BASE_PARAMS.items()) + list(faults.wind_for_repeat(0, 4.2, 1.26).items()):
        v.set_param(k, val)
    mark("params set")
    v.upload_mission(mission.patrol_square(home))
    mark("mission uploaded")
    v.set_mode("GUIDED")
    v.arm()
    mark("armed (sim %.0f s)" % (v.sim_time_ms / 1000))
    v.takeoff(mission.PATROL_ALT_M)
    v.set_mode("AUTO")
    mark("took off (sim %.0f s)" % (v.sim_time_ms / 1000))
    sim0, wall0 = v.sim_time_ms, time.time()
    while v.armed:
        if v.pump() is not None:
            msgs += 1
    rate = (v.sim_time_ms - sim0) / 1000.0 / max(1e-6, time.time() - wall0)
    mark("landed (sim %.0f s; mission ran at %.0fx; %d msgs = %.0f msg/s)" % (
        v.sim_time_ms / 1000, rate, msgs, msgs / max(1e-6, time.time() - wall0)))
finally:
    s.stop()
mark("sitl stopped")
log = s.dataflash_logs()[-1]
dst = "/tmp/profile_flight.BIN"
shutil.copy(log, dst)
mark("log copied (%.1f MB)" % (os.path.getsize(dst) / 1e6))
analyze.score(dst, {}, True, mission.FENCE_RADIUS_M)
mark("log analysed")

prev = t0
for name, t in marks:
    print("%6.1f s  (+%5.1f)  %s" % (t - t0, t - prev, name))
    prev = t

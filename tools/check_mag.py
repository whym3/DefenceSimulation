#!/usr/bin/env python3
"""Debug helper: shows compass readings (MAG log messages) before and after the fault in a run."""
import json
import os
import sys

from pymavlink import mavutil

run_dir = sys.argv[1]
with open(os.path.join(run_dir, "result.json")) as f:
    fault_t = json.load(f)["result"]["fault_time_s"]
log = mavutil.mavlink_connection(os.path.join(run_dir, "flight.BIN"))
samples = {}
while True:
    m = log.recv_match(type=["MAG", "XKF2"])
    if m is None:
        break
    t = m.TimeUS / 1e6
    for label, when in (("before", fault_t - 2), ("after", fault_t + 20)):
        key = (m.get_type(), getattr(m, "I", getattr(m, "C", 0)), label)
        if key not in samples and t >= when:
            if m.get_type() == "MAG":
                samples[key] = "MagX=%.0f MagY=%.0f MagZ=%.0f OfsX=%.0f" % (m.MagX, m.MagY, m.MagZ, m.OfsX)
            else:
                samples[key] = "EKF earth/body mag bias MX=%s" % getattr(m, "MX", "?")
for k in sorted(samples):
    print(k, samples[k])

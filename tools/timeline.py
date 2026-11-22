#!/usr/bin/env python3
"""Prints what happened around the fault: messages, errors, mode changes, and drift over time.

Usage: timeline.py <run_dir | flight.BIN> [fault_time_s] [--every SECONDS]
With a run directory, the fault time is read from its result.json.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt.analyze import dist_m, read_log  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("fault_time", nargs="?", type=float)
ap.add_argument("--every", type=float, default=1.0)
args = ap.parse_args()

path, start = args.path, args.fault_time
if os.path.isdir(path):
    with open(os.path.join(path, "result.json")) as f:
        res = json.load(f)["result"]
    if start is None:
        start = res.get("fault_time_s")
    print("verdict:", res["verdict"], "-", res["reason"])
    path = os.path.join(path, "flight.BIN")
start = start or 0.0

d = read_log(path)
events = []
for ts, name, val in d["parms"]:
    if name.startswith("SIM_") and ts > d["sim"][0][0] + 1:
        events.append((ts, "PARM %s=%g" % (name, val)))
for ts, sub, code in d["errs"]:
    events.append((ts, "ERR subsys %d code %d" % (sub, code)))
for ts, mode, rsn in d["modes"]:
    events.append((ts, "MODE %d reason %d" % (mode, rsn)))
for ts, text in d["msgs"]:
    events.append((ts, "MSG " + text))
events.sort()
for ts, e in events:
    if ts >= start - 5:
        print("%8.2f  %s" % (ts, e))

print("\n   time  horiz-err(m)  est-age(s)  true-height(m)  est-height(m)")
pos = d["pos"]
pi, last, next_print = 0, None, start
ground = d["sim"][0][3]
est_ground = pos[0][3] if pos else ground
for ts, lat, lon, alt in d["sim"]:
    while pi < len(pos) and pos[pi][0] <= ts:
        last = pos[pi]
        pi += 1
    if ts >= next_print and last is not None:
        print("%7.1f  %10.1f  %10.1f  %12.1f  %12.1f" % (
            ts, dist_m(lat, lon, last[1], last[2]), ts - last[0], alt - ground, last[3] - est_ground))
        next_print = ts + args.every

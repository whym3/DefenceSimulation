#!/usr/bin/env python3
"""Prints the average throttle while cruising (CTUN.ThO) for one or more runs: a direct read of
how hard the motors work. Thinner air (higher density altitude) should need more throttle.

Usage: hover_throttle.py <run_dir> [<run_dir> ...]
"""
import os
import sys

from pymavlink import mavutil

for run_dir in sys.argv[1:]:
    log = mavutil.mavlink_connection(os.path.join(run_dir, "flight.BIN"))
    vals, peak, pwm, cruising = [], 0.0, [], False
    while True:
        m = log.recv_match(type=["CTUN", "RCOU"])
        if m is None:
            break
        if m.get_type() == "CTUN":
            cruising = m.Alt > 40  # at patrol height
            if cruising:
                vals.append(m.ThO)
                peak = max(peak, m.ThO)
        elif cruising:
            pwm.append((m.C1 + m.C2 + m.C3 + m.C4) / 4.0)
    if vals:
        # ThO is the autopilot's throttle demand, which ArduPilot already compensates for air
        # density; the motor PWM is what the motors actually receive.
        print("%-55s throttle demand %.3f  motor PWM %.0f us  (%d samples)" % (
            os.path.basename(run_dir.rstrip("/")), sum(vals) / len(vals), sum(pwm) / max(1, len(pwm)), len(vals)))
    else:
        print(os.path.basename(run_dir), "no cruise samples")

#!/usr/bin/env python3
"""Real fault sizes in physical units for each RflyMAD sensor-fault case: the faulted sensor's
standard deviation before vs during the fault, and its largest jump from the pre-fault mean.

Usage: rflymad_magnitudes.py <extracted_dir> <survey_csv> <out_csv>
"""
import csv
import glob
import os
import sys

import numpy as np
from pyulog import ULog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rflymad_survey import gps_xy, series  # noqa: E402

TARGET = {
    "acce": ("accelerometer", lambda u: series(u, "sensor_accel", ["x", "y", "z"]), "m/s^2"),
    "gyro": ("gyro", lambda u: series(u, "sensor_gyro", ["x", "y", "z"]), "rad/s"),
    "mag": ("compass", lambda u: series(u, "sensor_mag", ["x", "y", "z"], 1000.0), "mGauss"),
    "baro": ("barometer", lambda u: series(u, "vehicle_air_data", ["baro_alt_meter"]), "m"),
    "GPS": ("gps", lambda u: gps_xy(u), "m"),
}
WINDOW_S = 10.0


def main():
    root, survey_csv, out_csv = sys.argv[1:4]
    survey = {(r["folder"], r["case"]): r for r in csv.DictReader(open(survey_csv))}
    out = []
    for (folder, case), r in sorted(survey.items()):
        if r.get("error") or not r.get("inject_log_s"):
            continue
        sensor = r["sensor_folder"]
        name, get, unit = TARGET[sensor]
        ulgs = glob.glob(os.path.join(root, folder, case, "log_*", "*.ulg"))
        if not ulgs:
            continue
        s = get(ULog(ulgs[0]))
        if s is None:
            continue
        t, x = s
        if sensor == "GPS":
            x = x[:, :2]  # horizontal position
        t0 = float(r["inject_log_s"])
        t1 = t0 + min(WINDOW_S, float(r.get("fault_duration_s") or WINDOW_S))
        pre = x[(t >= t0 - WINDOW_S) & (t < t0)]
        post = x[(t >= t0) & (t < t1)]
        if len(pre) < 5 or len(post) < 5:
            continue
        # High-pass: remove the slow flight motion with a 1 s moving average, keep fast changes.
        def hp(arr, tt):
            # Remove the window mean first (np.convolve pads with zeros, which would otherwise make
            # the edges look like huge noise for signals such as altitude), then drop the edges.
            arr = arr - arr.mean(0)
            dt = max(np.median(np.diff(tt)), 1e-3)
            k = max(2, int(round(1.0 / dt)))
            kern = np.ones(k) / k
            smooth = np.vstack([np.convolve(arr[:, i], kern, mode="same") for i in range(arr.shape[1])]).T
            res = (arr - smooth)[k:-k] if len(arr) > 3 * k else arr - smooth
            return res
        tp, tq = t[(t >= t0 - WINDOW_S) & (t < t0)], t[(t >= t0) & (t < t1)]
        sd_pre = float(np.max(hp(pre, tp).std(0)))
        sd_post = float(np.max(hp(post, tq).std(0)))
        jump = float(np.max(np.abs(post - pre.mean(0))))
        out.append(dict(sensor=name, folder=folder, case=case, mode={"3": "noise", "4": "scale"}.get(r["fault_mode"], r["fault_mode"]),
                        params=r["fault_params"], unit=unit, fast_noise_before=round(sd_pre, 4),
                        fast_noise_during=round(sd_post, 4), max_jump_from_pre_mean=round(jump, 3)))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    import collections
    import statistics
    g = collections.defaultdict(list)
    for o in out:
        g[(o["sensor"], o["mode"])].append(o)
    print("%-13s %-6s %3s %-7s %-22s %-22s %s" % ("sensor", "mode", "n", "unit", "fast noise before", "fast noise during",
                                                 "max jump (median / max)"))
    for (s, m), rs in sorted(g.items()):
        q = lambda k: [o[k] for o in rs]  # noqa: E731
        print("%-13s %-6s %3d %-7s %-22s %-22s %.2f / %.2f" % (
            s, m, len(rs), rs[0]["unit"], "%.3f" % statistics.median(q("fast_noise_before")),
            "%.3f (max %.3f)" % (statistics.median(q("fast_noise_during")), max(q("fast_noise_during"))),
            statistics.median(q("max_jump_from_pre_mean")), max(q("max_jump_from_pre_mean"))))


if __name__ == "__main__":
    main()

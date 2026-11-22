#!/usr/bin/env python3
"""Surveys every RflyMAD real-flight sensor-fault case: what fault was injected, how much each
sensor's readings actually changed, and how PX4 reacted.

Usage: rflymad_survey.py <extracted_dir> <out_csv>
Reads the dataset only (it is untrusted input); writes one CSV row per case.

For each sensor, compares the 10 s before the injection with the fault window (injection to
injection + 10 s):
  shift = change of the mean, noise_x = ratio of standard deviations.
Units: accel m/s^2, gyro rad/s, mag milligauss, baro altitude m (vehicle_air_data), GPS m
(horizontal position relative to the pre-fault mean) and GPS altitude m.
"""
import ast
import csv
import glob
import math
import os
import sys

import numpy as np
import openpyxl
from pyulog import ULog

WINDOW_S = 10.0
NAV_STATES = {0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 3: "AUTO_MISSION", 4: "AUTO_LOITER", 5: "AUTO_RTL",
              10: "ACRO", 12: "DESCEND", 13: "TERMINATION", 14: "OFFBOARD", 15: "STAB", 17: "AUTO_TAKEOFF",
              18: "AUTO_LAND", 19: "AUTO_FOLLOW", 20: "AUTO_PRECLAND", 21: "ORBIT"}


def test_info(case):
    out = {}
    for x in glob.glob(os.path.join(case, "TestInfo*.xlsx")):
        ws = openpyxl.load_workbook(x, read_only=True, data_only=True).worksheets[0]
        for row in ws.iter_rows(values_only=True):
            vals = [c for c in row if c is not None]
            if len(vals) >= 2:
                out[str(vals[0]).strip()] = vals[1]
    return out


def parse_floats(s):
    s = str(s).strip().strip("[]")
    return [float(v) for v in s.replace(",", " ").split() if v]


def topic(u, name):
    for d in u.data_list:
        if d.name == name and d.multi_id == 0:
            return d
    return None


def series(u, name, fields, scale=1.0):
    d = topic(u, name)
    if d is None:
        return None
    t = (d.data["timestamp"] - u.start_timestamp) / 1e6
    cols = [d.data[f].astype(float) * scale for f in fields if f in d.data]
    if not cols:
        return None
    return t, np.vstack(cols).T


def compare(s, t0, t1):
    """Mean shift (max over axes) and noise ratio (max over axes) between [t0-W, t0) and [t0, t1)."""
    if s is None:
        return None, None
    t, x = s
    pre = x[(t >= t0 - WINDOW_S) & (t < t0)]
    post = x[(t >= t0) & (t < t1)]
    if len(pre) < 5 or len(post) < 5:
        return None, None
    shift = float(np.max(np.abs(post.mean(0) - pre.mean(0))))
    sd_pre = pre.std(0) + 1e-9
    ratio = float(np.max(post.std(0) / sd_pre))
    return shift, ratio


def gps_xy(u):
    d = topic(u, "sensor_gps") or topic(u, "vehicle_gps_position")
    if d is None:
        return None
    t = (d.data["timestamp"] - u.start_timestamp) / 1e6
    lat = d.data["lat"].astype(float) / 1e7 if "lat" in d.data else None
    lon = d.data["lon"].astype(float) / 1e7 if "lon" in d.data else None
    alt = d.data["alt"].astype(float) / 1e3 if "alt" in d.data else np.zeros_like(t)
    if lat is None or not np.any(lat):
        return None
    lat0, lon0 = np.median(lat[lat != 0]), np.median(lon[lon != 0])
    n = np.radians(lat - lat0) * 6371000.0
    e = np.radians(lon - lon0) * 6371000.0 * math.cos(math.radians(lat0))
    return t, np.vstack([n, e, alt]).T


def reactions(u, t0):
    out = {}
    d = topic(u, "vehicle_status")
    if d is not None:
        t = (d.data["timestamp"] - u.start_timestamp) / 1e6
        nav = d.data["nav_state"].astype(int)
        before = nav[t < t0]
        start = int(before[-1]) if len(before) else None
        changes = [(round(float(tt - t0), 1), NAV_STATES.get(int(n), str(int(n))))
                   for tt, n, p in zip(t[1:], nav[1:], nav[:-1]) if n != p and tt >= t0]
        out["nav_before"] = NAV_STATES.get(start, str(start))
        out["nav_changes_after_fault"] = "; ".join("%s@%ss" % (n, tt) for tt, n in changes[:4])
        if "failsafe" in d.data:
            fs = d.data["failsafe"].astype(int)
            on = t[(fs > 0) & (t >= t0)]
            out["failsafe_after_s"] = round(float(on[0] - t0), 1) if len(on) else None
    d = topic(u, "estimator_innovation_test_ratios")
    if d is not None:
        t = (d.data["timestamp"] - u.start_timestamp) / 1e6
        post = (t >= t0) & (t < t0 + WINDOW_S)
        for key, fields in (("gps_pos", ["gps_hpos[0]", "gps_hpos[1]"]), ("baro", ["baro_vpos"]),
                            ("mag", ["mag_field[0]", "mag_field[1]", "mag_field[2]"])):
            vals = [d.data[f][post] for f in fields if f in d.data]
            if vals and post.any():
                out["max_test_ratio_%s" % key] = round(float(np.max(np.abs(np.vstack(vals)))), 2)
    d = topic(u, "vehicle_land_detected")
    if d is not None:
        t = (d.data["timestamp"] - u.start_timestamp) / 1e6
        landed = d.data["landed"].astype(int)
        after = t >= t0
        out["landed_during_fault"] = bool(np.any(landed[after & (t < t0 + 25)] > 0)) if after.any() else None
    return out


def main():
    root, out_csv = sys.argv[1], sys.argv[2]
    rows = []
    for case in sorted(glob.glob(os.path.join(root, "*-*", "*"))):
        if not os.path.isdir(case):
            continue
        folder = os.path.basename(os.path.dirname(case))
        status, sensor = folder.split("-", 1)
        row = dict(folder=folder, flight=status, sensor_folder=sensor, case=os.path.basename(case))
        try:
            info = test_info(case)
            row["fault_id"] = int(parse_floats(info.get("Fault ID", "0"))[0]) if info.get("Fault ID") else None
            params = parse_floats(info.get("Fault parameter", ""))
            row["fault_mode"] = int(params[0]) if params else None
            row["fault_params"] = " ".join("%g" % p for p in params[1:])
            t0 = float(info.get("Fault injection time", "nan"))
            t_end = float(info.get("Test end time", "nan"))
            ulgs = glob.glob(os.path.join(case, "log_*", "*.ulg")) + glob.glob(os.path.join(case, "*.ulg"))
            if not ulgs:
                row["error"] = "no ulog"
                rows.append(row)
                continue
            u = ULog(ulgs[0])
            # Use the onboard fault marker for the injection time when present (TestInfo is relative
            # to the script start, the ULog to the log start).
            d = topic(u, "rfly_ctrl_lxl")
            if d is not None and "id" in d.data:
                ids = d.data["id"].astype(float)
                tt = (d.data["timestamp"] - u.start_timestamp) / 1e6
                hit = tt[(ids > 100000) & (ids < 200000)]
                if len(hit):
                    row["inject_log_s"] = round(float(hit[0]), 1)
                    t0 = float(hit[0])
                    later = tt[(tt > hit[0]) & ~((ids > 100000) & (ids < 200000))]
                    t_end = float(later[0]) if len(later) else t0 + 20
            row["fault_duration_s"] = round(t_end - t0, 1)
            t1 = min(t0 + WINDOW_S, t_end)
            for name, s in (("accel", series(u, "sensor_accel", ["x", "y", "z"])),
                            ("gyro", series(u, "sensor_gyro", ["x", "y", "z"])),
                            ("mag", series(u, "sensor_mag", ["x", "y", "z"], 1000.0)),
                            ("baro_alt", series(u, "vehicle_air_data", ["baro_alt_meter"])),
                            ("gps_pos", gps_xy(u))):
                if name == "gps_pos" and s is not None:
                    t, x = s
                    sh, ra = compare((t, x[:, :2]), t0, t1)
                    row["gps_alt_shift"], row["gps_alt_noise_x"] = [None if v is None else round(v, 3) for v in compare((t, x[:, 2:]), t0, t1)]
                else:
                    sh, ra = compare(s, t0, t1)
                row["%s_shift" % name] = None if sh is None else round(sh, 3)
                row["%s_noise_x" % name] = None if ra is None else round(ra, 2)
            row.update(reactions(u, t0))
        except Exception as e:  # keep going: one broken case must not stop the survey
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        rows.append(row)
        print("%-16s %-6s id=%s mode=%s p=[%s]  %s" % (folder, row["case"], row.get("fault_id"), row.get("fault_mode"),
                                                       row.get("fault_params", ""), row.get("error", "")), flush=True)
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print("wrote", out_csv, len(rows), "cases")


if __name__ == "__main__":
    main()

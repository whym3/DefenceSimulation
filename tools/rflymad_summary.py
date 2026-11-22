#!/usr/bin/env python3
"""Summarises validation/rflymad_real_sensor_cases.csv by sensor folder and fault mode.

Usage: rflymad_summary.py validation/rflymad_real_sensor_cases.csv
"""
import collections
import csv
import statistics
import sys

MODES = {"3": "noise", "4": "scale"}
SENSOR_COLS = ["accel", "gyro", "mag", "baro_alt", "gps_pos"]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def fmt(v, nd=2):
    return "-" if v is None else ("%.*f" % (nd, v))


rows = list(csv.DictReader(open(sys.argv[1])))
print("cases: %d, with errors: %d" % (len(rows), sum(1 for r in rows if r.get("error"))))
for r in rows:
    if r.get("error"):
        print("  error:", r["folder"], r["case"], r["error"])

groups = collections.defaultdict(list)
for r in rows:
    if not r.get("error"):
        groups[(r["sensor_folder"], MODES.get(r.get("fault_mode", ""), r.get("fault_mode")))].append(r)

print("\nfault IDs found per sensor folder:")
by_folder = collections.defaultdict(collections.Counter)
for r in rows:
    by_folder[r["sensor_folder"]][r.get("fault_id")] += 1
for k, c in sorted(by_folder.items()):
    print("  %-6s %s" % (k, dict(c)))

print("\nmedian change in each sensor during the fault window (shift = mean change; x = noise ratio)")
print("%-6s %-6s %3s  " % ("folder", "mode", "n") + "  ".join("%-17s" % c for c in SENSOR_COLS))
for (sensor, mode), rs in sorted(groups.items()):
    cells = []
    for c in SENSOR_COLS:
        sh = med([num(r.get("%s_shift" % c)) for r in rs])
        nx = med([num(r.get("%s_noise_x" % c)) for r in rs])
        cells.append("%-17s" % ("%s / x%s" % (fmt(sh, 3), fmt(nx, 1))))
    print("%-6s %-6s %3d  " % (sensor, mode, len(rs)) + "  ".join(cells))

print("\nparameters used and PX4 reaction")
for (sensor, mode), rs in sorted(groups.items()):
    params = collections.Counter(r["fault_params"] for r in rs)
    fs = [num(r.get("failsafe_after_s")) for r in rs]
    n_fs = sum(1 for v in fs if v is not None)
    changes = collections.Counter()
    for r in rs:
        for ch in (r.get("nav_changes_after_fault") or "").split("; "):
            if ch:
                changes[ch.split("@")[0]] += 1
    landed = sum(1 for r in rs if r.get("landed_during_fault") == "True")
    tr = {k: med([num(r.get("max_test_ratio_%s" % k)) for r in rs]) for k in ("gps_pos", "baro", "mag")}
    print("- %s / %s (%d cases)" % (sensor, mode, len(rs)))
    print("    params: %s" % "; ".join("[%s] x%d" % (p, n) for p, n in params.most_common(6)))
    print("    failsafe flag set: %d/%d (median after %s s); mode changes after fault: %s; landed within 25 s: %d" % (
        n_fs, len(rs), fmt(med(fs), 1), dict(changes) or "none", landed))
    print("    median max innovation test ratio (>1 = measurement rejected): gps %s, baro %s, mag %s" % (
        fmt(tr["gps_pos"]), fmt(tr["baro"]), fmt(tr["mag"])))

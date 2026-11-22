#!/usr/bin/env python3
"""Compares two batches flight by flight (for example 40x vs 80x simulation speed).

Only flights present in both batches are compared (matched on condition, wind, sensor, level, repeat).
Usage: compare_batches.py batches/<a> batches/<b>
"""
import csv
import os
import sys


def load(batch):
    rows = {}
    with open(os.path.join(batch, "summary.csv")) as f:
        for r in csv.DictReader(f):
            key = (r.get("condition", "-"), r.get("wind", "-"), r["fault"], int(r["level"]), int(r["repeat"]))
            rows[key] = r
    return rows


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


a_dir, b_dir = sys.argv[1], sys.argv[2]
a, b = load(a_dir), load(b_dir)
keys = sorted(set(a) & set(b))
if not keys:
    sys.exit("no flights in common")
same, differ = 0, []
for k in keys:
    va, vb = a[k]["verdict"], b[k]["verdict"]
    if va == vb:
        same += 1
    else:
        differ.append(k)
print("compared %d flights present in both batches" % len(keys))
print("verdicts identical: %d of %d" % (same, len(keys)))
if differ:
    print("\n%-9s %-8s %-13s %-3s %-2s  %-9s %-9s  %-15s %-15s" % (
        "condition", "wind", "sensor", "lvl", "r", "A", "B", "reaction A/B s", "drift A/B m"))
    for k in differ:
        ra, rb = a[k], b[k]
        fmt = lambda f: "/".join("-" if num(r[f]) is None else "%.1f" % num(r[f]) for r in (ra, rb))
        print("%-9s %-8s %-13s L%-2d r%-2d %-9s %-9s  %-15s %-15s" % (
            k[0], k[1], k[2], k[3], k[4], ra["verdict"], rb["verdict"], fmt("failsafe_reaction_s"), fmt("max_drift_m")))

# Safe limits for each condition/wind/sensor group, from the common flights only.
ok = {"PASS", "SAFE_FAIL"}
groups = sorted({(k[0], k[1], k[2]) for k in keys if k[2] != "none"})
mismatch = 0
for g in groups:
    lim = []
    for rows in (a, b):
        safe = 0
        for lv in sorted({k[3] for k in keys if k[:3] == g}):
            vs = [rows[k]["verdict"] for k in keys if k[:3] == g and k[3] == lv]
            if all(v in ok for v in vs):
                safe = lv
            else:
                break
        lim.append(safe)
    if lim[0] != lim[1]:
        mismatch += 1
        print("safe limit differs: %s/%s %s  A=L%d B=L%d" % (g[0], g[1], g[2], lim[0], lim[1]))
print("safe limits identical in %d of %d sensor groups" % (len(groups) - mismatch, len(groups)))

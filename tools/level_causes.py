#!/usr/bin/env python3
"""Per fault family and level: verdict counts, main reasons and median reaction time, over flyable
condition/wind groups (baseline all OK).

Usage: level_causes.py batches/<name> [sensor ...]
"""
import collections
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt.report import cause  # noqa: E402

batch = sys.argv[1]
only = set(sys.argv[2:])
rows = list(csv.DictReader(open(os.path.join(batch, "summary.csv"))))
base = collections.defaultdict(list)
for r in rows:
    if r["fault"] == "none":
        base[(r["condition"], r["wind"])].append(r["verdict"])
flyable = {k for k, v in base.items() if all(x in ("PASS", "SAFE_FAIL") for x in v)}
by = collections.defaultdict(list)
for r in rows:
    if r["fault"] != "none" and (r["condition"], r["wind"]) in flyable and r["verdict"] != "NOT_TESTED":
        if not only or r["fault"] in only:
            by[(r["fault"], int(r["level"]))].append(r)
for (s, lv), rs in sorted(by.items()):
    v = collections.Counter(r["verdict"] for r in rs)
    c = collections.Counter(cause(r["reason"]) for r in rs if r["verdict"] not in ("PASS", "SAFE_FAIL"))
    react = [float(r["failsafe_reaction_s"]) for r in rs if r["failsafe_reaction_s"] not in ("", None)]
    print("%-14s L%d  n=%-3d P=%-3d S=%-3d U=%-3d  reaction %s  causes: %s" % (
        s, lv, len(rs), v["PASS"], v["SAFE_FAIL"], v["UNSAFE"],
        ("%.1fs" % statistics.median(react)) if react else "-", dict(c.most_common(3))))

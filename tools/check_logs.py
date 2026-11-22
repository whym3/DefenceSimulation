#!/usr/bin/env python3
"""Checks a batch for flights whose log has no touchdown (incomplete logs) and lists verdict counts.

Usage: check_logs.py batches/<name> [batches/<name> ...]
"""
import collections
import csv
import os
import sys

for batch in sys.argv[1:]:
    with open(os.path.join(batch, "summary.csv")) as f:
        rows = list(csv.DictReader(f))
    no_td = [r for r in rows if r["verdict"] != "NOT_TESTED" and not r.get("touchdown_speed_ms")]
    counts = collections.Counter(r["verdict"] for r in rows)
    print("%s: %d flights, %s; no touchdown in log: %d" % (
        os.path.basename(batch.rstrip("/")), len(rows), dict(counts), len(no_td)))
    for r in no_td:
        print("   %s %s %s L%s r%s  %s  %s" % (r.get("condition"), r.get("wind"), r["fault"], r["level"],
                                           r["repeat"], r["verdict"], r["reason"][:70]))

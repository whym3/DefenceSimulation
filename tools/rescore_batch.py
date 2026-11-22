#!/usr/bin/env python3
"""Re-scores every flight in a batch folder with the current analyser and rebuilds summary.csv and
envelope.json. No re-flying. Usage: rescore_batch.py batches/<name>
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_batch  # noqa: E402
from dtt import analyze, faults, mission  # noqa: E402

batch = sys.argv[1]
rows = []
for res_path in sorted(glob.glob(os.path.join(batch, "*", "result.json"))):
    run_dir = os.path.dirname(res_path)
    with open(res_path) as f:
        report = json.load(f)
    meta, old = report["meta"], report["result"]
    landed = meta.get("landed", not meta.get("timed_out", False))
    new = analyze.score(analyze.find_log(run_dir), old.get("fault_params", {}),
                        old["mission_completed"], mission.FENCE_RADIUS_M, landed=landed,
                        fault_expected=meta["fault"] != "none")
    new["fault_params"] = old.get("fault_params", {})
    report["result"] = new
    with open(res_path, "w") as f:
        json.dump(report, f, indent=2)
    # Week-2 batches predate conditions: their condition is the site and their wind is "fixed-3ms".
    row = dict(condition=meta["site"], wind=meta.get("wind_level", "fixed-3ms"),
               fault=meta["fault"], level=meta["level"], repeat=meta["repeat"])
    row.update(run_batch.row_from_result(run_dir, new))
    if row["verdict"] != old["verdict"]:
        print("changed: %-13s L%d r%d  %s -> %s  (%s)" % (row["fault"], row["level"], row["repeat"],
                                                       old["verdict"], row["verdict"], row["reason"]))
    rows.append(row)

sensors = [s for s in faults.SENSORS if any(r["fault"] == s for r in rows)]   # set DTT_AUTOPILOT=px4 for a PX4 batch
levels = sorted({r["level"] for r in rows if r["fault"] != "none"})
# Keep the original batch's flying time; re-scoring takes no flying time.
wall_s, vehicle = 0.0, None
env_path = os.path.join(batch, "envelope.json")
if os.path.exists(env_path):
    with open(env_path) as f:
        old_env = json.load(f)
    wall_s, vehicle = 60.0 * (old_env.get("wall_minutes") or 0), old_env.get("vehicle")
run_batch.write_outputs(rows, batch, sensors, levels, wall_s, vehicle)

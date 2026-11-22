#!/usr/bin/env python3
"""Re-scores saved runs with the current analyser (no re-flying). Usage: rescore.py runs/<id> ..."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dtt import analyze, mission  # noqa: E402

for run_dir in sys.argv[1:]:
    path = os.path.join(run_dir, "result.json")
    with open(path) as f:
        report = json.load(f)
    meta, old = report["meta"], report["result"]
    landed = meta.get("landed", not meta.get("timed_out", False))
    new = analyze.score(os.path.join(run_dir, "flight.BIN"), old.get("fault_params", {}),
                        old["mission_completed"], mission.FENCE_RADIUS_M, landed=landed,
                        fault_expected=meta["fault"] not in ("none", None))
    new["fault_params"] = old.get("fault_params", {})
    report["result"] = new
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(os.path.basename(run_dir))
    print(json.dumps(new, indent=2))

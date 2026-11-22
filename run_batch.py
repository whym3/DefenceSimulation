#!/usr/bin/env python3
"""Runs the test matrix on several simulators at once, then writes a summary table and each sensor's
safe limit for every condition and wind level.

Matrix: conditions x wind levels x (baseline + sensors x levels) x repeats. Calm wind has no
direction, so it gets one repeat only.

Examples (inside WSL Ubuntu):
    python run_batch.py                                          # everything
    python run_batch.py --conditions delhi --winds typical       # the week-2 style Delhi matrix
    python run_batch.py --conditions ladakh --sensors gps --levels 1 5 --repeats 1 --parallel 4
"""
import argparse
import concurrent.futures as cf
import csv
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import time

from dtt import conditions, faults
from dtt.sitl import provenance

HERE = os.path.dirname(os.path.abspath(__file__))
OK_VERDICTS = {"PASS", "SAFE_FAIL"}
_PRINT_LOCK = threading.Lock()


def say(text):
    """Thread-safe print: whole lines only, flushed so they stream to a background task's output."""
    with _PRINT_LOCK:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def build_jobs(sensors, levels, repeats, conds, winds):
    jobs = []
    for c in conds:
        for w in winds:
            n_rep = 1 if conditions.wind(c, w)[0] == 0 else repeats
            for r in range(n_rep):
                jobs.append(dict(condition=c, wind=w, fault="none", level=0, repeat=r))
            for s in sensors:
                for lv in levels:
                    for r in range(n_rep):
                        jobs.append(dict(condition=c, wind=w, fault=s, level=lv, repeat=r))
    return jobs


def label(j):
    return "%-9s %-7s %-13s L%d r%d" % (j["condition"], j["wind"], j["fault"], j["level"], j["repeat"])


def run_job(job, instances, out, speedup, max_wall_s, vehicle_args=()):
    inst = instances.get()
    say("  start  %s  on simulator %d" % (label(job), inst))
    try:
        cmd = [sys.executable, os.path.join(HERE, "run_one.py"),
               "--fault", job["fault"], "--level", str(max(job["level"], 1)),
               "--repeat", str(job["repeat"]), "--condition", job["condition"], "--wind", job["wind"],
               "--instance", str(inst), "--speedup", str(speedup),
               "--max-wall-s", str(max_wall_s), "--out", out] + list(vehicle_args)
        # An ERROR (simulator did not start, log cut short) says nothing about the drone: fly it once more.
        for attempt in (1, 2):
            t0 = time.time()
            p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
            saved = [ln.split("saved:", 1)[1].strip() for ln in p.stdout.splitlines() if ln.startswith("saved:")]
            row = dict(job, instance=inst, wall_s=round(time.time() - t0, 1), attempts=attempt)
            if p.returncode != 0 or not saved:
                row.update(verdict="ERROR", reason=(p.stderr.strip().splitlines() or ["?"])[-1][:200])
            else:
                with open(os.path.join(saved[0], "result.json")) as f:
                    res = json.load(f)["result"]
                row.update(row_from_result(saved[0], res))
            if row["verdict"] != "ERROR":
                break
        return row
    finally:
        instances.put(inst)


ROW_FIELDS = ("verdict", "reason", "failsafe_reaction_s", "hazard_after_fault_s", "reaction_after_hazard_s", "failsafe", "first_warning_s", "first_warning",
              "max_drift_m", "max_estimate_error_m", "max_vertical_error_m", "estimate_lost_after_fault_s",
              "max_distance_from_home_m", "final_distance_from_home_m", "touchdown_speed_ms",
              "estimated_height_at_touchdown_m", "crashed", "fence_breached", "fence_alarm", "mission_completed")


def row_from_result(run_dir, res):
    return dict(run_dir=os.path.basename(run_dir), **{k: res.get(k) for k in ROW_FIELDS})


def envelope(rows, sensors, levels):
    """Safe limit per sensor: the highest level at which every repeat (and every milder level) is OK.

    The limit stops at the first level that is not fully OK. If a flight there was UNSAFE, that is
    first_unsafe_level. If its flights could only not be judged (ERROR, NOT_TESTED, or none flown),
    it is not_verified_level: the level is not proven safe, and not proven unsafe either.
    """
    env = {}
    for s in sensors:
        safe_up_to, first_unsafe, not_verified, detail = 0, None, None, {}
        for lv in sorted(levels):
            vs = [r["verdict"] for r in rows if r["fault"] == s and r["level"] == lv]
            detail[lv] = vs
            if first_unsafe is not None or not_verified is not None:
                continue
            if vs and all(v in OK_VERDICTS for v in vs):
                safe_up_to = lv
            elif "UNSAFE" in vs:
                first_unsafe = lv
            else:
                not_verified = lv
        env[s] = dict(safe_up_to_level=safe_up_to, first_unsafe_level=first_unsafe,
                      not_verified_level=not_verified, verdicts=detail)
    return env


def write_outputs(rows, out, sensors, levels, wall_s, vehicle=None):
    """Writes summary.csv and envelope.json, and prints the safe-limit tables."""
    cond_order = {c: i for i, c in enumerate(conditions.CONDITIONS)}
    wind_order = {w: i for i, w in enumerate(conditions.WINDS)}
    fault_order = {s: i for i, s in enumerate(["none"] + list(sensors))}
    rows.sort(key=lambda r: (cond_order.get(r.get("condition"), 99), wind_order.get(r.get("wind"), 99),
                             fault_order.get(r["fault"], 99), r["level"], r["repeat"]))
    first = ["condition", "wind", "fault", "level", "repeat", "verdict", "reason"]
    fields = first + sorted({k for r in rows for k in r} - set(first))
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    groups = {}
    for r in rows:
        groups.setdefault((r.get("condition", "-"), r.get("wind", "-")), []).append(r)
    result = dict(wall_minutes=round(wall_s / 60, 1), vehicle=vehicle, groups={})
    for (c, w), grows in groups.items():
        env = envelope(grows, sensors, levels)
        baseline_ok = all(r["verdict"] in OK_VERDICTS for r in grows if r["fault"] == "none")
        if not baseline_ok:
            # The drone fails without any fault (e.g. wind beyond what it can fly in), so sensor
            # limits in this group are meaningless.
            for s in env:
                env[s]["safe_up_to_level"] = None
                env[s]["note"] = "baseline fails without a fault"
        cond = conditions.describe(c) if c in conditions.CONDITIONS else {}
        speed, turb = conditions.wind(c, w) if (c in conditions.CONDITIONS and w in conditions.WINDS) else (None, None)
        result["groups"]["%s/%s" % (c, w)] = dict(
            condition=c, wind=w, wind_speed_ms=speed, turbulence_ms=turb,
            temperature_c=cond.get("temperature_c"), density_altitude_m=cond.get("density_altitude_m"),
            baseline=[r["verdict"] for r in grows if r["fault"] == "none"], sensors=env)
    with open(os.path.join(out, "envelope.json"), "w") as f:
        json.dump(result, f, indent=2)

    print("\nSafe limit by sensor (highest level where every repeat was PASS or SAFE_FAIL; L0 = none;")
    print("n/a = the drone fails even without a fault in that condition; ? = the next level could not be judged)")
    head = "%-28s %-9s" % ("condition / wind", "baseline") + "".join("%-14s" % s for s in sensors)
    print(head)
    for key, g in result["groups"].items():
        wind_txt = "%s %.1fm/s" % (g["wind"], g["wind_speed_ms"]) if g["wind_speed_ms"] is not None else g["wind"]
        base = "/".join(v[:1] for v in g["baseline"])
        cells = []
        for s in sensors:
            lim = g["sensors"][s]["safe_up_to_level"]
            cells.append("%-14s" % ("n/a" if lim is None else "L%d%s" % (
                lim, "?" if g["sensors"][s].get("not_verified_level") else "")))
        print("%-28s %-9s" % ("%s / %s" % (g["condition"], wind_txt), base) + "".join(cells))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--conditions", nargs="+", default=conditions.CONDITIONS, choices=conditions.CONDITIONS)
    p.add_argument("--winds", nargs="+", default=conditions.WINDS, choices=conditions.WINDS)
    p.add_argument("--group", default="all", choices=["all"] + faults.GROUPS,
                   help="fault group when --sensors is not given: gradual, abrupt or all")
    p.add_argument("--sensors", nargs="+", default=None, choices=faults.SENSORS)
    p.add_argument("--levels", nargs="+", type=int, default=list(faults.LEVELS), choices=faults.LEVELS)
    p.add_argument("--repeats", type=int, default=len(faults.REPEATS["wind_directions_deg"]))
    # Checked: 40x vs 10x (76/78 verdicts equal) and 120x vs 80x (all equal apart from random GPS
    # jamming and the re-scored unreached faults; safe limits identical in all 60 groups).
    # 120x on 12 simulators flies the 780-flight gradual matrix in about 10.5 min.
    p.add_argument("--parallel", type=int, default=12)
    p.add_argument("--speedup", type=int, default=120)
    p.add_argument("--max-wall-s", type=float, default=600)
    p.add_argument("--out", default=None)
    p.add_argument("--no-report", action="store_true", help="skip building report.pdf at the end")
    p.add_argument("--model", default="quad", help="SITL frame model of the drone under test")
    p.add_argument("--params", default=None, help="parameter file of the drone under test")
    args = p.parse_args(argv)
    if args.params and not os.path.isfile(args.params):
        p.error("--params file not found: %s" % args.params)
    vehicle_args = ["--model", args.model] + (["--params", os.path.abspath(args.params)] if args.params else [])
    if args.sensors is None:
        args.sensors = faults.sensors_in(args.group)

    out = args.out or os.path.join(HERE, "batches", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)
    jobs = build_jobs(args.sensors, args.levels, args.repeats, args.conditions, args.winds)
    print("%d flights on %d simulators at %dx -> %s" % (len(jobs), args.parallel, args.speedup, out), flush=True)
    for c in args.conditions:
        d = conditions.describe(c)
        print("  %-9s %s, %.1f C, flown at density altitude %d m (air %.0f%% of sea level); winds: %s" % (
            c, d["site_name"], d["temperature_c"], d["density_altitude_m"], 100 * d["air_density_ratio"],
            ", ".join("%s %.1f m/s" % (w, conditions.wind(c, w)[0]) for w in args.winds)), flush=True)

    instances = queue.Queue()
    for i in range(args.parallel):
        instances.put(i)
    rows, t0 = [], time.time()
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = [ex.submit(run_job, j, instances, out, args.speedup, args.max_wall_s, vehicle_args) for j in jobs]
        for n, fut in enumerate(cf.as_completed(futs), 1):
            r = fut.result()
            rows.append(r)
            elapsed = time.time() - t0
            eta = elapsed / n * (len(jobs) - n)
            say("[%3d/%d] %s  %-9s %s  (%.0f s)" % (n, len(jobs), label(r), r["verdict"],
                                                  r.get("reason", ""), r.get("wall_s", 0)))
            say("  progress: %d/%d done (%d%%), %.1f min elapsed, about %.1f min left" % (
                n, len(jobs), 100 * n // len(jobs), elapsed / 60, eta / 60))

    write_outputs(rows, out, args.sensors, args.levels, time.time() - t0, provenance(args.model, args.params))
    print("done in %.1f min; summary.csv and envelope.json in %s" % ((time.time() - t0) / 60, out))
    if not args.no_report:
        from dtt import report
        say("report: %s" % report.build(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Flies one patrol mission in the simulator, optionally injects a fault, and scores the flight.

Examples (inside WSL Ubuntu):
    python run_one.py                                  # baseline, no fault
    python run_one.py --fault gps --level 5            # GPS lost at the second corner
    python run_one.py --fault compass --level 3 --repeat 1
    python run_one.py --condition ladakh --wind strong --fault barometer --level 2
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import time

from dtt import analyze, conditions, faults, mission
from dtt.flight import FlightError, Vehicle
from dtt.sitl import Sitl, provenance

HERE = os.path.dirname(os.path.abspath(__file__))
# Checked at 60 s too: a drone that disarms by itself does so within about 3 s of touchdown, and one
# that has not by 15 s still has not at 60 s, so a longer wait changes no verdict.
STUCK_ON_GROUND_S = 15.0


def fly(fault="none", level=0, repeat=0, condition="delhi", wind_level="typical", instance=0,
        speedup=120, max_wall_s=300, out=os.path.join(HERE, "runs"), keep_workdir=False,
        model="quad", params=None):
    """params: parameter file of the drone under test, loaded as SITL defaults. The test's own
    settings (mission.BASE_PARAMS and the wind) are still set on top of it."""
    home = conditions.home(condition)
    level = 0 if fault == "none" else level
    run_id = "%s_%s-%s_%s-L%d_r%d" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                                      condition, wind_level, fault, level, repeat)
    workdir = os.path.join(os.path.expanduser("~/dtt-work"), "%s_i%d" % (run_id, instance))
    outdir = os.path.join(out, run_id)
    os.makedirs(outdir, exist_ok=True)

    wind_speed, wind_turb = conditions.wind(condition, wind_level)
    wind = faults.wind_for_repeat(repeat, wind_speed, wind_turb)
    meta = dict(run_id=run_id, site=condition, condition=conditions.describe(condition),
                wind_level=wind_level, fault=fault, level=level, repeat=repeat,
                description=faults.describe(fault, level), wind=wind, speedup=speedup, home=home,
                vehicle=provenance(model, params))
    fault_params = {}
    completed = False
    sitl = Sitl(workdir, home, instance=instance, speedup=speedup, model=model,
                extra_defaults=[os.path.abspath(params)] if params else None)
    sitl.start()
    try:
        v = Vehicle(sitl.port)
        v.wait_ready()
        for k, val in list(mission.BASE_PARAMS.items()) + list(wind.items()):
            if not v.set_param(k, val):
                raise FlightError("parameter %s not accepted" % k)
        items = mission.patrol_square(home)
        v.upload_mission(items)
        last_seq = len(items) - 1

        v.set_mode("GUIDED")
        v.arm()
        v.takeoff(mission.PATROL_ALT_M)
        v.set_mode("AUTO")

        alternatives = faults.param_alternatives(fault, level)
        injected = not alternatives
        wall_deadline = time.time() + max_wall_s
        max_seq = 0
        ground_since = None  # sim time when the drone (truly) reached the ground while still armed
        while time.time() < wall_deadline:
            v.pump()
            max_seq = max(max_seq, v.mission_seq)
            # A drone that flew into the ground while believing it is airborne never disarms.
            # End the flight once it has truly sat on the ground for STUCK_ON_GROUND_S.
            if v.true_alt_m is not None and injected and alternatives:
                if v.true_alt_m - home[2] < 0.5:
                    ground_since = ground_since if ground_since is not None else v.sim_time_ms
                    if (v.sim_time_ms - ground_since) / 1000.0 > STUCK_ON_GROUND_S:
                        meta["stuck_on_ground"] = True
                        break
                else:
                    ground_since = None
            if not injected and v.mission_seq >= mission.FAULT_AT_SEQ:
                applied = v.apply_first_supported(alternatives)
                if applied is None:
                    raise FlightError("simulator rejected every parameter set for %s" % meta["description"])
                fault_params = applied
                meta["fault_injected_sim_s"] = v.sim_time_ms / 1000.0
                injected = True
            if not v.armed:
                break
        else:
            meta["timed_out"] = True
        completed = max_seq >= last_seq and not v.armed
        meta["landed"] = not v.armed
        meta["max_mission_seq"] = max_seq
        meta["final_mode"] = v.mode
        meta["statustext"] = v.statustext
        # Let ArduPilot finish writing its log before the simulator is stopped. A drone still armed
        # (stuck on the ground, or timed out) keeps logging, so force-disarm it first.
        if v.armed:
            v.force_disarm()
        meta["log_flushed"] = sitl.wait_log_flushed()
    finally:
        sitl.stop()

    logs = sitl.dataflash_logs()
    if not logs:
        raise FlightError("no flight log produced; see %s/sitl.out" % workdir)
    log_path = os.path.join(outdir, "flight.BIN")
    shutil.copy(logs[-1], log_path)
    shutil.copy(os.path.join(workdir, "sitl.out"), os.path.join(outdir, "sitl.out"))
    if not keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)

    result = analyze.score(log_path, fault_params, completed, mission.FENCE_RADIUS_M,
                           landed=meta.get("landed", False), fault_expected=fault != "none")
    result["fault_params"] = fault_params
    with open(os.path.join(outdir, "result.json"), "w") as f:
        json.dump(dict(meta=meta, result=result), f, indent=2)
    return outdir, result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fault", default="none", choices=["none"] + faults.SENSORS)
    p.add_argument("--level", type=int, default=5, choices=faults.LEVELS)
    p.add_argument("--repeat", type=int, default=0, help="repeat number; sets the wind direction")
    p.add_argument("--condition", default="delhi", choices=conditions.CONDITIONS,
                   help="site + temperature (flown at its density altitude)")
    p.add_argument("--wind", default="typical", choices=conditions.WINDS)
    p.add_argument("--speedup", type=int, default=120)
    p.add_argument("--instance", type=int, default=0, help="simulator instance (TCP port 5760+10*N)")
    p.add_argument("--max-wall-s", type=float, default=300)
    p.add_argument("--out", default=os.path.join(HERE, "runs"))
    p.add_argument("--keep-workdir", action="store_true")
    p.add_argument("--model", default="quad", help="SITL frame model of the drone under test")
    p.add_argument("--params", default=None, help="parameter file of the drone under test")
    args = p.parse_args()
    if args.params and not os.path.isfile(args.params):
        p.error("--params file not found: %s" % args.params)
    outdir, result = fly(args.fault, args.level, args.repeat, args.condition, args.wind, args.instance,
                         args.speedup, args.max_wall_s, args.out, args.keep_workdir, args.model, args.params)
    print(json.dumps(result, indent=2))
    print("saved:", outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

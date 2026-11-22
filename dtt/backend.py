"""The parts that differ between autopilots: simulator, MAVLink client, settings, wind and log file.

The autopilot is chosen once per process with --autopilot (run_one.py, run_batch.py), which sets
DTT_AUTOPILOT before the fault file is loaded.
"""
import math
import os
from types import SimpleNamespace

from . import conditions, faults, mission

NAME = os.environ.get("DTT_AUTOPILOT", "ardupilot")
NAMES = ("ardupilot", "px4")

# PX4: the same 600 m circle and 120 m ceiling, returning home on a breach.
PX4_BASE_PARAMS = {"GF_MAX_HOR_DIST": mission.FENCE_RADIUS_M, "GF_MAX_VER_DIST": mission.FENCE_ALT_MAX_M, "GF_ACTION": 3}
SIH_T_MAX, SIH_KDV = 5.0, 1.0   # SIH defaults: thrust per rotor (N) and linear drag (N per m/s)


def _px4_wind(repeat, speed_ms, turbulence_ms):
    """SIH has steady wind only. Its north/east values are where the wind comes FROM, like SIM_WIND_DIR."""
    direction = math.radians(faults.wind_for_repeat(repeat, speed_ms, turbulence_ms)["SIM_WIND_DIR"])
    return {"SIH_WIND_N": speed_ms * math.cos(direction), "SIH_WIND_E": speed_ms * math.sin(direction)}


def _px4_sitl(workdir, home, instance, speedup, model, params, condition):
    from .px4_sitl import Px4Sitl
    if params:
        raise ValueError("--params is not supported for PX4 yet")
    # SIH's multicopter thrust and drag ignore air density, so thin air is modelled by scaling both
    # by the condition's density ratio (ArduPilot's simulator does this itself from altitude).
    ratio = conditions.describe(condition)["air_density_ratio"]
    return Px4Sitl(workdir, home, instance=instance, speedup=speedup,
                   model="sihsim_quadx" if model == "quad" else model,
                   boot_params={"SIH_T_MAX": round(SIH_T_MAX * ratio, 4), "SIH_KDV": round(SIH_KDV * ratio, 4)})


def _ardupilot_sitl(workdir, home, instance, speedup, model, params, condition):
    from .sitl import Sitl
    return Sitl(workdir, home, instance=instance, speedup=speedup, model=model,
                extra_defaults=[os.path.abspath(params)] if params else None)


def _vehicle(port):
    if NAME == "px4":
        from .px4_flight import Px4Vehicle
        return Px4Vehicle(port)
    from .flight import Vehicle
    return Vehicle(port)


def get():
    if NAME == "px4":
        # PX4 missions have no home item at seq 0, so every mission sequence number is one lower.
        return SimpleNamespace(name="px4", make_sitl=_px4_sitl, vehicle=_vehicle, base_params=PX4_BASE_PARAMS,
                               wind_params=_px4_wind, seq_shift=-1, log_name="flight.ulg")
    return SimpleNamespace(name="ardupilot", make_sitl=_ardupilot_sitl, vehicle=_vehicle,
                           base_params=mission.BASE_PARAMS, wind_params=faults.wind_for_repeat, seq_shift=0,
                           log_name="flight.BIN")

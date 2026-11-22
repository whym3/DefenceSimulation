"""Sensor faults at five levels, loaded from config/faults.yaml.

A fault level resolves to a list of alternative SIM_* parameter sets. Vehicle.apply_first_supported
applies the first set the simulator accepts, so the tool keeps working when ArduPilot renames
parameters between versions.
"""
import os

import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
FILES = {"ardupilot": "faults.yaml", "px4": "faults_px4.yaml"}   # each autopilot's simulator has its own parameters
METRES_PER_DEG_LAT = 111320.0
LEVELS = (1, 2, 3, 4, 5)


def load(path):
    with open(path) as f:
        return yaml.safe_load(f)


def use(autopilot):
    """Loads one autopilot's fault file. Called at import (DTT_AUTOPILOT) and by the report for old batches."""
    global _CONFIG, SENSORS, GROUP, GROUPS, REPEATS
    _CONFIG = load(os.path.join(CONFIG_DIR, FILES[autopilot]))
    SENSORS = [k for k in _CONFIG if k != "repeats"]
    # Fault group: "gradual" (bias, drift, offsets, jamming, loss), "abrupt" (steps, noise, scale) or "ew".
    GROUP = {s: _CONFIG[s].get("group", "gradual") for s in SENSORS}
    GROUPS = sorted(set(GROUP.values()))
    REPEATS = _CONFIG["repeats"]


use(os.environ.get("DTT_AUTOPILOT", "ardupilot"))


def sensors_in(group):
    return [s for s in SENSORS if group == "all" or GROUP[s] == group]


def _convert(value):
    if isinstance(value, dict) and "north_m" in value:
        return float(value["north_m"]) / METRES_PER_DEG_LAT
    return float(value)


def param_alternatives(sensor, level):
    """Returns the list of alternative parameter sets for one sensor at one level.

    sensor "none" (or level 0) means no fault.
    """
    if sensor == "none" or level == 0:
        return []
    spec = _CONFIG[sensor]["levels"][int(level)]
    options = spec if isinstance(spec, list) else [spec]
    return [{name: _convert(v) for name, v in opt.items() if not _is_ramp(v)} for opt in options]


def _is_ramp(value):
    return isinstance(value, dict) and "north_m_per_s" in value


def ramps(sensor, level):
    """Parameters that grow during the flight: {name: degrees of latitude per simulated second}.

    The runner re-sends them after the fault is switched on (a GPS spoofing drag).
    """
    if sensor == "none" or level == 0:
        return {}
    spec = _CONFIG[sensor]["levels"][int(level)]
    # shortcut: ramps come from the first alternative only, upgrade if a ramp level ever needs alternatives
    opt = spec[0] if isinstance(spec, list) else spec
    return {name: float(v["north_m_per_s"]) / METRES_PER_DEG_LAT for name, v in opt.items() if _is_ramp(v)}


def name(sensor):
    return _CONFIG[sensor].get("name", sensor) if sensor in _CONFIG else sensor


def label(sensor, level):
    """Plain-language description of one fault level, for the report."""
    labels = _CONFIG.get(sensor, {}).get("labels", {})
    return str(labels.get(int(level), "level %d" % level))


def describe(sensor, level):
    if sensor == "none" or level == 0:
        return "no fault"
    return "%s level %d" % (sensor, level)


def wind_for_repeat(repeat, speed_ms, turbulence_ms):
    """SIM_* wind parameters: the given speed and turbulence, from repeat N's direction."""
    dirs = REPEATS["wind_directions_deg"]
    # Repeats beyond the listed directions step by the golden angle, so each one is a new direction.
    direction = dirs[repeat] if repeat < len(dirs) else (repeat * 137.508) % 360
    return {
        "SIM_WIND_SPD": float(speed_ms),
        "SIM_WIND_DIR": float(direction),
        "SIM_WIND_TURB": float(turbulence_ms),
    }

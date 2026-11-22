"""Sensor faults at five levels, loaded from config/faults.yaml.

A fault level resolves to a list of alternative SIM_* parameter sets. Vehicle.apply_first_supported
applies the first set the simulator accepts, so the tool keeps working when ArduPilot renames
parameters between versions.
"""
import os

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "faults.yaml")
METRES_PER_DEG_LAT = 111320.0


def load(path=CONFIG_PATH):
    with open(path) as f:
        return yaml.safe_load(f)


_CONFIG = load()
SENSORS = [k for k in _CONFIG if k != "repeats"]
# Fault group: "gradual" (bias, drift, offsets, jamming, loss) or "abrupt" (steps, noise, scale).
GROUP = {s: _CONFIG[s].get("group", "gradual") for s in SENSORS}
GROUPS = sorted(set(GROUP.values()))


def sensors_in(group):
    return [s for s in SENSORS if group == "all" or GROUP[s] == group]
REPEATS = _CONFIG["repeats"]
LEVELS = (1, 2, 3, 4, 5)


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
    return [{name: _convert(v) for name, v in opt.items()} for opt in options]


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
    return {
        "SIM_WIND_SPD": float(speed_ms),
        "SIM_WIND_DIR": float(dirs[repeat % len(dirs)]),
        "SIM_WIND_TURB": float(turbulence_ms),
    }

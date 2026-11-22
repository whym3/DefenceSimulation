"""Test conditions: site, temperature (as density altitude) and wind level.

Reads config/conditions.yaml and the cached NASA POWER statistics in data/weather_stats.json.
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "config", "conditions.yaml")) as _f:
    _CFG = yaml.safe_load(_f)
_STATS_PATH = os.path.join(ROOT, "data", "weather_stats.json")
if os.path.exists(_STATS_PATH):
    import json
    with open(_STATS_PATH) as _f:
        _STATS = json.load(_f)
else:
    _STATS = {}

SITES = _CFG["sites"]
CONDITIONS = list(_CFG["conditions"])
WINDS = list(_CFG["winds"])


def density_altitude_m(elevation_m, temperature_c):
    """Height in the ISA standard atmosphere with the same air density as the real place.

    Assumes standard pressure at the site's elevation; temperature is the real air temperature.
    """
    pressure = 101325.0 * (1 - 2.25577e-5 * elevation_m) ** 5.25588
    density = pressure / (287.05 * (temperature_c + 273.15))
    return (1 - (density / 1.225) ** (1 / 4.25588)) / 2.25577e-5


def describe(condition):
    c = _CFG["conditions"][condition]
    site = SITES[c["site"]]
    temp = _STATS[c["site"]]["temperature_c"][c["temperature"]]
    da = density_altitude_m(site["elevation_m"], temp)
    return dict(condition=condition, site=c["site"], site_name=site["name"],
                elevation_m=site["elevation_m"], temperature_c=temp, temperature_case=c["temperature"],
                density_altitude_m=round(da), air_density_ratio=round((1 - 2.25577e-5 * da) ** 4.25588, 3))


def home(condition, heading=0.0):
    """SITL home (lat, lon, alt, heading). Altitude is the density altitude (see module doc)."""
    d = describe(condition)
    site = SITES[d["site"]]
    return (site["lat"], site["lon"], float(d["density_altitude_m"]), heading)


def wind(condition, level):
    """(speed m/s, turbulence m/s) for a wind level at the condition's site."""
    w = _CFG["winds"][level]
    if "percentile" in w:
        site = _CFG["conditions"][condition]["site"]
        speed = _STATS[site]["wind50_ms"][str(w["percentile"])]
    else:
        speed = float(w["speed"])
    return float(speed), round(float(speed) * w["turbulence_fraction"], 2)

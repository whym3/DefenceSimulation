#!/usr/bin/env python3
"""Downloads hourly weather (NASA POWER, 2020-2024) for each site in config/conditions.yaml and
writes data/weather/<site>.json (raw hourly values) and data/weather_stats.json (percentiles).

NASA POWER is free and needs no account. Run once; the tool then works offline.
"""
import json
import math
import os
import time
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEARS = range(2020, 2025)
PARAMS = "WS10M,WS50M,T2M"
LAPSE_C_PER_M = 0.0065  # standard atmosphere temperature lapse rate
URL = ("https://power.larc.nasa.gov/api/temporal/hourly/point?parameters={p}&community=RE"
       "&longitude={lon}&latitude={lat}&start={y}0101&end={y}1231&format=JSON&time-standard=UTC")


def fetch_year(lat, lon, year):
    url = URL.format(p=PARAMS, lat=lat, lon=lon, y=year)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # network hiccup or rate limit: back off and retry
            print("  retry %d for %d: %s" % (attempt + 1, year, e))
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("could not fetch %d" % year)


def percentile(values, p):
    v = sorted(values)
    k = (len(v) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def main():
    with open(os.path.join(ROOT, "config", "conditions.yaml")) as f:
        cfg = yaml.safe_load(f)
    os.makedirs(os.path.join(ROOT, "data", "weather"), exist_ok=True)
    stats = {}
    for site, s in cfg["sites"].items():
        print("fetching", site)
        series = {k: [] for k in PARAMS.split(",")}
        grid_elev = None
        for y in YEARS:
            d = fetch_year(s["lat"], s["lon"], y)
            grid_elev = d["geometry"]["coordinates"][2]
            for k in series:
                series[k].extend(v for v in d["properties"]["parameter"][k].values() if v > -900)
        with open(os.path.join(ROOT, "data", "weather", site + ".json"), "w") as f:
            json.dump(dict(source="NASA POWER hourly", years=list(YEARS), grid_elevation_m=grid_elev,
                           lat=s["lat"], lon=s["lon"], series=series), f)
        # NASA POWER values are for a ~50 km grid cell whose mean height can differ a lot from the
        # town (Leh: cell ~4,500 m, town ~3,500 m). Correct temperature to the site's elevation.
        t_corr = (grid_elev - s["elevation_m"]) * LAPSE_C_PER_M
        t = [x + t_corr for x in series["T2M"]]
        stats[site] = dict(
            hours=len(t), grid_elevation_m=grid_elev, temperature_correction_c=round(t_corr, 2),
            temperature_c=dict(mean=round(sum(t) / len(t), 1), hot=round(percentile(t, 99), 1),
                               cold=round(percentile(t, 1), 1)),
            wind50_ms={str(p): round(percentile(series["WS50M"], p), 1) for p in (50, 95, 99, 99.9)},
            wind10_ms={str(p): round(percentile(series["WS10M"], p), 1) for p in (50, 95, 99, 99.9)},
        )
        print("  ", json.dumps(stats[site]))
    with open(os.path.join(ROOT, "data", "weather_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)


if __name__ == "__main__":
    main()

"""Checks the scoring rules and the safe-limit logic on made-up flights. No simulator needed.

Run: python tests/test_verdicts.py   (or pytest tests/)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_batch  # noqa: E402
from dtt import analyze  # noqa: E402

FAULT_T = 20.0
FAULT = {"SIM_X": 1.0}
M_PER_DEG = 111195.0  # metres per degree of latitude in analyze.dist_m


def flight(error_m=lambda t: 0.0, reaction_t=None, end_t=100.0, north_m=lambda t: 0.0, land=True):
    """A 10 Hz log: climbs to 50 m, flies, lands by end_t. The estimate is truth + error_m(t) north."""
    sim, pos = [], []
    for i in range(int(end_t * 10) + 1):
        t = i / 10.0
        alt = min(50.0, 5.0 * t)
        if land:
            alt = min(alt, max(0.0, 2.0 * (end_t - 5.0 - t)))  # 2 m/s descent, on the ground for the last 5 s
        lat = north_m(t) / M_PER_DEG
        sim.append((t, lat, 0.0, alt))
        pos.append((t, lat + error_m(t) / M_PER_DEG, 0.0, alt))
    modes = [] if reaction_t is None else [(reaction_t, 9, 6)]  # LAND, EKF failsafe
    return dict(sim=sim, pos=pos, modes=modes, errs=[], parms=[(FAULT_T, "SIM_X", 1.0)], msgs=[])


def score(log, completed, landed=True, fault=FAULT):
    analyze.read_log = lambda path: log
    return analyze.score("unused", fault, completed, fence_radius_m=600.0, landed=landed)


def slow_drift(t):  # 0.5 m/s from the fault: passes 10 m at t = 40
    return max(0.0, 0.5 * (t - FAULT_T))


def test_clean_flight_passes():
    assert score(flight(), completed=True)["verdict"] == "PASS"


def test_slow_drift_reaction_is_timed_from_the_hazard():
    r = score(flight(slow_drift, reaction_t=43.0), completed=False)
    assert r["verdict"] == "SAFE_FAIL", r["reason"]
    assert r["failsafe_reaction_s"] == 23.0          # from injection: would have been "too slow"
    assert 19.9 < r["hazard_after_fault_s"] < 20.3
    assert 2.7 < r["reaction_after_hazard_s"] < 3.1


def test_reaction_before_the_error_is_large_is_in_time():
    r = score(flight(lambda t: 4.0 if t >= FAULT_T else 0.0, reaction_t=50.0), completed=False)
    assert r["verdict"] == "SAFE_FAIL", r["reason"]
    assert r["hazard_after_fault_s"] is None


def test_late_reaction_is_unsafe():
    r = score(flight(slow_drift, reaction_t=52.0), completed=False)
    assert r["verdict"] == "UNSAFE" and "too slow" in r["reason"], r["reason"]


def test_large_error_without_reaction_is_unsafe():
    assert score(flight(slow_drift), completed=True)["verdict"] == "UNSAFE"


def test_fence_breach_counts_even_if_the_log_ends_in_the_air():
    r = score(flight(north_m=lambda t: 10.0 * t, land=False), completed=False, landed=False)
    assert r["verdict"] == "UNSAFE" and "geofence" in r["reason"], r["reason"]


def test_log_ending_in_the_air_is_error():
    assert score(flight(land=False), completed=False, landed=False)["verdict"] == "ERROR"


def test_fault_never_switched_on_is_not_tested():
    log = flight()
    log["parms"] = []
    assert score(log, completed=True)["verdict"] == "NOT_TESTED"


def rows(per_level):
    return [dict(fault="gps", level=lv, verdict=v) for lv, vs in per_level.items() for v in vs]


def test_envelope_error_flight_is_not_counted_as_safe():
    e = run_batch.envelope(rows({1: ["PASS", "PASS", "PASS"], 2: ["PASS", "ERROR", "ERROR"], 3: ["UNSAFE"]}),
                           ["gps"], [1, 2, 3])["gps"]
    assert (e["safe_up_to_level"], e["first_unsafe_level"], e["not_verified_level"]) == (1, None, 2)


def test_envelope_untested_level_is_not_called_unsafe():
    e = run_batch.envelope(rows({1: ["SAFE_FAIL"], 2: ["NOT_TESTED"]}), ["gps"], [1, 2, 3])["gps"]
    assert (e["safe_up_to_level"], e["first_unsafe_level"], e["not_verified_level"]) == (1, None, 2)


def test_envelope_unsafe_level_stops_the_limit():
    e = run_batch.envelope(rows({1: ["PASS"], 2: ["PASS", "UNSAFE", "ERROR"], 3: ["PASS"]}), ["gps"], [1, 2, 3])["gps"]
    assert (e["safe_up_to_level"], e["first_unsafe_level"], e["not_verified_level"]) == (1, 2, None)


def test_refine_jobs_fly_the_limit_level_and_the_one_above():
    env = dict(groups={
        "delhi/calm": dict(condition="delhi", wind="calm", baseline=["PASS"], sensors={
            "gps": dict(safe_up_to_level=1), "compass": dict(safe_up_to_level=5), "barometer": dict(safe_up_to_level=0)}),
        "delhi/extreme": dict(condition="delhi", wind="extreme", baseline=["UNSAFE"], sensors={
            "gps": dict(safe_up_to_level=None)})})
    jobs = run_batch.refine_jobs(env, 2)
    got = sorted({(j["fault"], j["level"]) for j in jobs})
    assert got == [("barometer", 1), ("compass", 5), ("gps", 1), ("gps", 2)], got
    assert sorted({j["repeat"] for j in jobs}) == [3, 4] and len(jobs) == 8
    assert {j["wind"] for j in jobs} == {"calm"}


def test_extra_repeats_get_new_wind_directions():
    from dtt import faults
    dirs = [faults.wind_for_repeat(n, 5, 1)["SIM_WIND_DIR"] for n in range(10)]
    assert dirs[:3] == [0.0, 120.0, 240.0] and len(set(dirs)) == 10, dirs


def test_spoof_drag_is_a_ramp_not_a_fixed_parameter():
    from dtt import faults
    assert faults.param_alternatives("gps_spoof", 3) == [{"SIM_GPS1_VERR_X": 1.0}]
    ramp = faults.ramps("gps_spoof", 3)
    assert list(ramp) == ["SIM_GPS1_GLTCH_X"]
    assert abs(ramp["SIM_GPS1_GLTCH_X"] * faults.METRES_PER_DEG_LAT - 1.0) < 1e-9   # 1 m/s north
    assert faults.ramps("gps", 3) == {} and faults.ramps("none", 0) == {}
    assert faults.param_alternatives("ew_attack", 5) == [{"SIM_RC_FAIL": 1.0, "SIM_GPS1_VERR_X": 2.0}]


def test_every_fault_family_has_five_levels_with_labels_and_a_fixed_parameter():
    from dtt import faults
    for s in faults.SENSORS:
        for lv in faults.LEVELS:
            # The fault time is read from a parameter that is set once, so each level needs one.
            assert all(faults.param_alternatives(s, lv)), (s, lv)
            assert faults.label(s, lv) != "level %d" % lv, (s, lv)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)

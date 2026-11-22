"""Reads an ArduPilot DataFlash log (.BIN) and scores the flight.

Drift = distance between where the drone really was (simulator truth, SIM message) and where it
believed it was (AHRS/EKF estimate, POS message).
"""
import math

# ArduPilot ModeReason values (libraries/AP_Vehicle/ModeReason.h, Copter-4.7.3) that mean the
# autopilot changed mode by itself because of a problem: radio, battery, GCS, EKF failsafes,
# GPS glitch, fence breach, terrain, terminate, crash, general failsafe, dead-reckoning.
FAILSAFE_MODE_REASONS = {3, 4, 5, 6, 7, 10, 11, 17, 19, 25, 50}
# LogErrorSubsystem values (libraries/AP_Logger/AP_Logger.h) for failsafes and estimator alarms:
# radio, battery, GPS failsafe, GCS, fence, GPS glitch, EKF check, EKF inertial-nav failsafe,
# terrain failsafe, thrust loss, sensors, vibration, dead-reckoning.
FAILSAFE_ERR_SUBSYS = {5, 6, 7, 8, 9, 11, 16, 17, 23, 25, 26, 29, 31}
CRASH_ERR_SUBSYS = 12

COPTER_MODES = {0: "STABILIZE", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED", 5: "LOITER", 6: "RTL",
                9: "LAND", 16: "POSHOLD", 17: "BRAKE", 21: "SMART_RTL"}
MODE_REASON_NAMES = {3: "radio failsafe", 4: "battery failsafe", 5: "GCS failsafe", 6: "EKF failsafe",
                     7: "GPS glitch", 10: "fence breached", 11: "terrain failsafe", 17: "terminate",
                     19: "crash failsafe", 25: "failsafe", 50: "dead-reckoning failsafe"}
ERR_NAMES = {5: "radio failsafe", 6: "battery failsafe", 7: "GPS failsafe", 8: "GCS failsafe",
             9: "fence failsafe", 11: "GPS glitch", 16: "EKF check", 17: "EKF inertial-nav failsafe",
             23: "terrain failsafe", 25: "thrust loss", 26: "sensor failsafe", 29: "vibration failsafe",
             31: "dead-reckoning failsafe"}

PASS_DRIFT_M = 10.0
SAFE_FAIL_REACTION_S = 5.0
UNSAFE_DRIFT_M = 50.0
CRASH_DESCENT_MS = 3.0
UNPLANNED_CONTACT_M = 5.0  # touching ground while the estimate says higher than this = flew into it
LOG_END_AIRBORNE_M = 2.0   # a log ending higher than this above home is incomplete


def dist_m(lat1, lon1, lat2, lon2):
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000.0 * math.hypot(x, y)


def read_log(path):
    from pymavlink import mavutil  # imported here so the scoring rules can be tested without it
    log = mavutil.mavlink_connection(path)
    sim, pos, modes, errs, parms, msgs = [], [], [], [], [], []
    while True:
        m = log.recv_match(type=["SIM", "POS", "MODE", "ERR", "PARM", "MSG"])
        if m is None:
            break
        t = m.get_type()
        ts = m.TimeUS / 1e6
        if t == "SIM":
            sim.append((ts, m.Lat, m.Lng, m.Alt))
        elif t == "POS":
            pos.append((ts, m.Lat, m.Lng, m.Alt))
        elif t == "MODE":
            modes.append((ts, int(m.ModeNum), int(getattr(m, "Rsn", 0))))
        elif t == "ERR":
            errs.append((ts, int(m.Subsys), int(m.ECode)))
        elif t == "PARM":
            parms.append((ts, m.Name, m.Value))
        elif t == "MSG":
            msgs.append((ts, m.Message))
    return dict(sim=sim, pos=pos, modes=modes, errs=errs, parms=parms, msgs=msgs)


def score(log_path, fault_params, mission_completed, fence_radius_m, landed=True, fault_expected=None):
    """Scores one flight. fault_expected=True with no fault in the log gives verdict NOT_TESTED."""
    if fault_expected is None:
        fault_expected = bool(fault_params)
    d = read_log(log_path)
    if not d["sim"]:
        raise ValueError("log has no SIM (simulator truth) messages")

    home = d["sim"][0]
    # Fault time: when the simulator parameter that injects the fault was changed in flight.
    fault_t = None
    for ts, name, value in d["parms"]:
        if name not in fault_params:
            continue
        target = fault_params[name]
        # Relative tolerance: GPS glitch values are tiny (degrees), so an absolute one would match 0.
        if abs(value - target) <= 1e-9 + 1e-3 * abs(target) and ts > d["sim"][0][0] + 1:
            fault_t = ts
            break

    # Drift: pair each truth sample with the latest estimate before it.
    #  - estimate error: truth vs a fresh estimate (estimate younger than 0.3 s)
    #  - once the estimator stops producing positions, the distance from the last estimate is
    #    how far the drone has travelled without knowing where it is.
    #  - vertical error: true height vs estimated height. The two altitude datums can differ by a
    #    constant, so the offset is taken from the first estimate (before any fault).
    max_drift, max_drift_after_fault, est_lost_at = 0.0, 0.0, None
    max_est_error, max_since_lost = 0.0, 0.0
    max_vert_error, max_vert_error_after_fault = 0.0, 0.0
    vert_offset = None
    est_height = []  # (ts, estimated height above home)
    max_from_home = 0.0
    hazard_t = None  # first time after the fault that the position error passes PASS_DRIFT_M
    ground = home[3]
    pi = 0
    pos = d["pos"]
    last_pos = None
    for ts, lat, lon, alt in d["sim"]:
        while pi < len(pos) and pos[pi][0] <= ts:
            last_pos = pos[pi]
            pi += 1
        max_from_home = max(max_from_home, dist_m(home[1], home[2], lat, lon))
        if last_pos is None:
            continue
        drift = dist_m(lat, lon, last_pos[1], last_pos[2])
        # POS is logged at 10 Hz or faster; an older estimate means the estimator has stopped.
        fresh = ts - last_pos[0] <= 0.3
        if fresh:
            if vert_offset is None:
                vert_offset = last_pos[3] - alt
            est_alt = last_pos[3] - vert_offset
            est_height.append((ts, est_alt - ground))
            verr = abs(est_alt - alt)
            max_vert_error = max(max_vert_error, verr)
            if fault_t and ts >= fault_t:
                max_vert_error_after_fault = max(max_vert_error_after_fault, verr)
                if verr > PASS_DRIFT_M and hazard_t is None:
                    hazard_t = ts
            max_est_error = max(max_est_error, drift)
        elif fault_t and ts > fault_t:
            if est_lost_at is None:
                est_lost_at = last_pos[0]  # estimator stopped producing a position
            max_since_lost = max(max_since_lost, drift)
        max_drift = max(max_drift, drift)
        if fault_t and ts >= fault_t:
            max_drift_after_fault = max(max_drift_after_fault, drift)
            if drift > PASS_DRIFT_M and hazard_t is None:
                hazard_t = ts

    # Failsafe reaction = the autopilot switching to a safety mode by itself (a MODE change with a
    # failsafe reason). ERR entries such as "GPS glitch" are only warnings: they are reported as
    # first_warning but do not count as the safety mode switching on.
    reaction_t, reaction_desc = None, None
    warning_t, warning_desc = None, None
    if fault_t is not None:
        for ts, mode, rsn in d["modes"]:
            if ts >= fault_t and rsn in FAILSAFE_MODE_REASONS:
                reaction_t, reaction_desc = ts, "%s (%s)" % (
                    COPTER_MODES.get(mode, "mode %d" % mode), MODE_REASON_NAMES.get(rsn, "reason %d" % rsn))
                break
        for ts, sub, code in d["errs"]:
            if ts >= fault_t and sub in FAILSAFE_ERR_SUBSYS and code != 0:
                warning_t, warning_desc = ts, ERR_NAMES.get(sub, "ERR subsystem %d" % sub) + " code %d" % code
                break

    # Crash: crash-check error, touching the ground faster than CRASH_DESCENT_MS, or touching the
    # ground while the drone believes it is still well above it (it flew into the ground).
    crashed = any(sub == CRASH_ERR_SUBSYS and code != 0 for _, sub, code in d["errs"])
    crash_why = "crash detected by the autopilot" if crashed else None
    touchdown_speed, est_height_at_touchdown = None, None
    airborne = False
    for i in range(1, len(d["sim"])):
        t0, _, _, a0 = d["sim"][i - 1]
        t1, _, _, a1 = d["sim"][i]
        if a1 - ground > 2.0:
            airborne = True
        if airborne and a1 - ground < 0.3 and t1 > t0:
            touchdown_speed = (a0 - a1) / (t1 - t0)
            # Only a current estimate counts: if the estimator had stopped, the drone had no belief.
            before = [h for ts, h in est_height if t1 - 1.0 <= ts <= t1]
            est_height_at_touchdown = before[-1] if before else None
            if touchdown_speed > CRASH_DESCENT_MS:
                crashed, crash_why = True, "hit the ground at %.1f m/s" % touchdown_speed
            elif (est_height_at_touchdown is not None and est_height_at_touchdown > UNPLANNED_CONTACT_M
                  and not landed):
                # It hit the ground still believing it was flying and never landed and switched its
                # motors off by itself (e.g. sat on the ground with motors running). A drone that
                # touches down gently and then disarms on its own (a 5 m barometer step: believed
                # 5.2 m, touched down at 0.5 m/s) is not counted as a crash.
                crashed, crash_why = True, "hit the ground while believing it was %.0f m up" % est_height_at_touchdown
            break

    # A breach is the TRUE position leaving the fence. The autopilot's own fence alarm (ERR 9) can
    # fire on a false position (e.g. GPS jamming) while the drone is really inside; report it apart.
    fence_breached = max_from_home > fence_radius_m
    fence_alarm = any(sub == 9 and code != 0 for _, sub, code in d["errs"])
    landed_dist = dist_m(home[1], home[2], d["sim"][-1][1], d["sim"][-1][2])

    reaction_s = (reaction_t - fault_t) if (reaction_t is not None and fault_t is not None) else None
    # The reaction is timed from when the fault became dangerous (position error over PASS_DRIFT_M),
    # not from when it was switched on: a slow drift is harmless at first, so no autopilot can react
    # to it within seconds of injection. A reaction before the error gets that large is in time.
    late_s = (reaction_t - hazard_t) if (reaction_t is not None and hazard_t is not None) else None
    in_time = reaction_t is not None and (late_s is None or late_s <= SAFE_FAIL_REACTION_S)
    # The 10 m / 50 m limits apply to whichever is worse: horizontal or vertical position error.
    horiz = max_drift_after_fault if fault_t else max_drift
    vert = max_vert_error_after_fault if fault_t else max_vert_error
    drift_for_rules = max(horiz, vert)

    # The log stops while the drone is still in the air (log not fully written, or the run hit its
    # time limit): the ending is unknown. A fence breach or crash already in the log still counts.
    end_height = d["sim"][-1][3] - ground
    incomplete = end_height > LOG_END_AIRBORNE_M
    incomplete_why = "flight log incomplete: it ends with the drone %.0f m up" % end_height
    if fault_expected and fault_t is None and incomplete:
        verdict, why = "ERROR", incomplete_why
    elif fault_expected and fault_t is None:
        # The drone never reached the fault point (e.g. could not fly upwind), so the fault was
        # never switched on: this flight says nothing about the sensor.
        verdict, why = "NOT_TESTED", "fault never switched on: drone did not reach the fault point%s" % (
            " (geofence breached)" if fence_breached else "")
    elif fence_breached:
        verdict, why = "UNSAFE", "geofence breached"
    elif crashed:
        verdict, why = "UNSAFE", crash_why
    elif incomplete:
        verdict, why = "ERROR", incomplete_why
    elif mission_completed and drift_for_rules < PASS_DRIFT_M and landed_dist < PASS_DRIFT_M:
        verdict, why = "PASS", "mission completed, drift %.1f m" % drift_for_rules
    elif in_time and landed:
        # Say where it came down: a spoofed drone can "return home" to a place far from home.
        verdict, why = "SAFE_FAIL", "failsafe after %.1f s (%s), landed safely %.0f m from home" % (
            reaction_s, reaction_desc, landed_dist)
    elif drift_for_rules > UNSAFE_DRIFT_M and reaction_s is None:
        verdict, why = "UNSAFE", "drift %.1f m with no failsafe" % drift_for_rules
    elif reaction_s is not None and not in_time:
        verdict, why = "UNSAFE", "failsafe too slow (%.1f s after the position error passed %.0f m, limit %.0f s)%s" % (
            late_s, PASS_DRIFT_M, SAFE_FAIL_REACTION_S, ", then landed without crash" if landed else "")
    elif reaction_s is not None:
        # Most of these did reach the ground and then sat there armed (the runner's stuck-on-ground end).
        verdict, why = "UNSAFE", ("failsafe engaged, came down but never switched its motors off"
                                  if touchdown_speed is not None else "failsafe engaged but the drone did not land")
    elif mission_completed:
        verdict, why = "UNSAFE", "position error %.1f m (over the %.0f m limit) with no safety mode; landed %.0f m from home" % (
            drift_for_rules, PASS_DRIFT_M, landed_dist)
    elif not landed:
        verdict, why = "UNSAFE", "did not land before the time limit and no safety mode"
    else:
        verdict, why = "UNSAFE", "mission not completed and no safety mode (position error %.1f m)" % drift_for_rules

    return dict(
        verdict=verdict,
        reason=why,
        fault_time_s=fault_t,
        failsafe_reaction_s=reaction_s,
        hazard_after_fault_s=None if (hazard_t is None or fault_t is None) else round(hazard_t - fault_t, 1),
        reaction_after_hazard_s=None if late_s is None else round(late_s, 1),
        failsafe=reaction_desc,
        first_warning_s=None if (warning_t is None or fault_t is None) else round(warning_t - fault_t, 1),
        first_warning=warning_desc,
        max_drift_m=round(max_drift, 2),
        max_drift_after_fault_m=round(max_drift_after_fault, 2),
        max_estimate_error_m=round(max_est_error, 2),
        max_vertical_error_m=round(max_vert_error, 2),
        max_vertical_error_after_fault_m=round(max_vert_error_after_fault, 2),
        estimated_height_at_touchdown_m=None if est_height_at_touchdown is None else round(est_height_at_touchdown, 1),
        estimate_lost_after_fault_s=None if (est_lost_at is None or fault_t is None) else round(est_lost_at - fault_t, 1),
        max_distance_from_last_estimate_m=round(max_since_lost, 1),
        landed=landed,
        max_distance_from_home_m=round(max_from_home, 1),
        final_distance_from_home_m=round(landed_dist, 1),
        touchdown_speed_ms=None if touchdown_speed is None else round(touchdown_speed, 2),
        crashed=crashed,
        fence_breached=fence_breached,
        fence_alarm=fence_alarm,
        mission_completed=mission_completed,
        flight_time_s=round(d["sim"][-1][0] - d["sim"][0][0], 1),
    )

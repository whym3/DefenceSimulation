"""Reads a PX4 flight log (ULog) into the same dictionary as analyze.read_log, so one scorer serves both.

Truth is SIH's vehicle_global_position_groundtruth; the estimate is vehicle_global_position.
"""
# vehicle_status.nav_state values (PX4 v1.18)
MODES = {0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 3: "MISSION", 4: "HOLD", 5: "RTL", 12: "DESCEND",
         13: "TERMINATION", 17: "TAKEOFF", 18: "LAND"}
FAILSAFE_REASON = 25   # analyze.FAILSAFE_MODE_REASONS: "failsafe"
FENCE_ERR = 9          # analyze: ERR subsystem reported as fence_alarm


def read_log(path):
    from pyulog import ULog  # imported here so the rest of the tool does not need pyulog

    u = ULog(path)
    return from_topics({d.name: d.data for d in u.data_list if d.multi_id == 0},
                       u.changed_parameters, [(m.timestamp, m.message) for m in u.logged_messages])


def from_topics(topics, changed_parameters, messages):
    """topics: {name: {field: sequence}} with timestamps in microseconds."""
    def rows(name, *fields):
        t = topics.get(name)
        if t is None:
            return []
        return list(zip(*([[x / 1e6 for x in t["timestamp"]]] + [list(t[f]) for f in fields])))

    sim = [(ts, float(lat), float(lon), float(alt))
           for ts, lat, lon, alt in rows("vehicle_global_position_groundtruth", "lat", "lon", "alt")]
    # An estimate PX4 itself marks invalid is no estimate: drop it, so the scorer sees it as lost.
    pos = [(ts, float(lat), float(lon), float(alt))
           for ts, lat, lon, alt, ok in rows("vehicle_global_position", "lat", "lon", "alt", "lat_lon_valid") if ok]
    # A mode change counts as the autopilot's own reaction when PX4 flags a failsafe and the mode is
    # not the one that was commanded (the mission's own final return-home changes the commanded mode).
    modes, last = [], None
    for ts, nav, wanted, failsafe in rows("vehicle_status", "nav_state", "nav_state_user_intention", "failsafe"):
        reacted = bool(failsafe) and nav != wanted
        if (nav, reacted) != last:
            modes.append((ts, int(nav), FAILSAFE_REASON if reacted else 0))
            last = (nav, reacted)
    errs, was = [], False
    for ts, breached in rows("failsafe_flags", "geofence_breached"):
        if breached and not was:
            errs.append((ts, FENCE_ERR, 1))
        was = bool(breached)
    parms = [(ts / 1e6, name, float(value)) for ts, name, value in changed_parameters]
    return dict(sim=sim, pos=pos, modes=modes, errs=errs, parms=parms, msgs=[(ts / 1e6, m) for ts, m in messages])

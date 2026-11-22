"""Controls one simulated flight over MAVLink: parameters, mission upload, arming, fault injection."""
import time

from pymavlink import mavutil

mavlink = mavutil.mavlink
TELEMETRY_HZ = 2  # per simulated second; the scoring uses the onboard log, not telemetry

_FRAMES = {
    "GLOBAL": mavlink.MAV_FRAME_GLOBAL,
    "RELATIVE": mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
}
_CMDS = {
    "WAYPOINT": mavlink.MAV_CMD_NAV_WAYPOINT,
    "TAKEOFF": mavlink.MAV_CMD_NAV_TAKEOFF,
    "RTL": mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
}


class FlightError(RuntimeError):
    pass


class Vehicle:
    def __init__(self, port, connect_retries=60):
        self.m = mavutil.mavlink_connection(
            "tcp:127.0.0.1:%d" % port, source_system=255, retries=connect_retries)
        # Lock onto the autopilot's own heartbeat (component 1), not any other component.
        hb = self.m.recv_match(type="HEARTBEAT", blocking=True, timeout=60,
                               condition="HEARTBEAT.autopilot != %d" % mavlink.MAV_AUTOPILOT_INVALID)
        if hb is None:
            raise FlightError("no heartbeat from the autopilot")
        self.m.target_system = hb.get_srcSystem()
        self.m.target_component = hb.get_srcComponent() or mavlink.MAV_COMP_ID_AUTOPILOT1
        self.sim_time_ms = 0
        self.armed = False
        self.mode = None
        self.mission_seq = 0
        self.statustext = []  # (sim_time_s, text)
        self.true_alt_m = None  # from SIM_STATE
        # Ask only for the telemetry the runner uses, at a low rate. Rates are in SIMULATED time, so
        # at 120x speed 10 Hz of everything floods this Python client (~6,000 msg/s) and the
        # simulator slows down to wait for it (measured: missions ran at 21x when asked for 120x).
        ts, tc = self.m.target_system, self.m.target_component
        self.m.mav.request_data_stream_send(ts, tc, mavlink.MAV_DATA_STREAM_ALL, 0, 0)
        for stream in (mavlink.MAV_DATA_STREAM_EXTENDED_STATUS,  # MISSION_CURRENT
                       mavlink.MAV_DATA_STREAM_POSITION):        # GLOBAL_POSITION_INT
            self.m.mav.request_data_stream_send(ts, tc, stream, TELEMETRY_HZ, 1)
        # SIM_STATE (simulator truth) is not in the standard streams; ask for it explicitly.
        self.m.mav.command_long_send(ts, tc, mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                     mavlink.MAVLINK_MSG_ID_SIM_STATE, int(1e6 / TELEMETRY_HZ), 0, 0, 0, 0, 0)

    # ---- message pump -------------------------------------------------------------------
    def pump(self, timeout=0.5):
        """Reads one message (or none) and updates the vehicle state."""
        msg = self.m.recv_match(blocking=True, timeout=timeout)
        if msg is None:
            return None
        t = msg.get_type()
        if hasattr(msg, "time_boot_ms"):
            self.sim_time_ms = max(self.sim_time_ms, msg.time_boot_ms)
        if t == "HEARTBEAT" and msg.get_srcSystem() == self.m.target_system and msg.type != mavlink.MAV_TYPE_GCS:
            self.armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.mode = mavutil.mode_string_v10(msg)
        elif t == "MISSION_CURRENT":
            self.mission_seq = msg.seq
        elif t == "STATUSTEXT":
            self.statustext.append((self.sim_time_ms / 1000.0, msg.text))
        elif t == "SIM_STATE":
            # Simulator truth (SITL only): the real altitude, not what the drone believes.
            self.true_alt_m = msg.alt
        return msg

    def wait(self, predicate, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.pump()
            if predicate():
                return
        raise FlightError("timed out waiting for " + what)

    def wait_ready(self, timeout=120):
        """Waits until the estimator is using GPS. Mission storage is not ready before boot ends."""
        self.wait(lambda: any("is using GPS" in txt for _, txt in self.statustext),
                  timeout, "EKF to start using GPS")

    # ---- parameters ---------------------------------------------------------------------
    def set_param(self, name, value, timeout=5, tries=3):
        """Sets a parameter. Returns False if the vehicle does not have it."""
        for _ in range(tries):
            self.m.mav.param_set_send(self.m.target_system, self.m.target_component,
                                      name.encode(), float(value), mavlink.MAV_PARAM_TYPE_REAL32)
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = self.pump()
                if msg is not None and msg.get_type() == "PARAM_VALUE" and msg.param_id == name:
                    if abs(msg.param_value - float(value)) < 1e-3 * max(1.0, abs(float(value))):
                        return True
        return False

    def send_param(self, name, value):
        """Sets a parameter without waiting for the reply, for values re-sent during the flight."""
        self.m.mav.param_set_send(self.m.target_system, self.m.target_component,
                                  name.encode(), float(value), mavlink.MAV_PARAM_TYPE_REAL32)

    def apply_first_supported(self, alternatives):
        """Applies the first parameter set whose parameters all exist. Returns it, or None."""
        for params in alternatives:
            if all(self.set_param(k, v) for k, v in params.items()):
                return params
        return None

    # ---- mission ------------------------------------------------------------------------
    def upload_mission(self, items, timeout=30):
        ts, tc = self.m.target_system, self.m.target_component
        self.m.mav.mission_count_send(ts, tc, len(items), mavlink.MAV_MISSION_TYPE_MISSION)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.pump()
            if msg is None:
                continue
            t = msg.get_type()
            if t in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
                it = items[msg.seq]
                self.m.mav.mission_item_int_send(
                    ts, tc, msg.seq, _FRAMES[it["frame"]], _CMDS[it["cmd"]],
                    0, 1, 0, 0, 0, 0,
                    int(it["lat"] * 1e7), int(it["lon"] * 1e7), float(it["alt"]),
                    mavlink.MAV_MISSION_TYPE_MISSION)
            elif t == "MISSION_ACK":
                if msg.type != mavlink.MAV_MISSION_ACCEPTED:
                    raise FlightError("mission rejected, code %d" % msg.type)
                return
        raise FlightError("mission upload timed out")

    # ---- modes, arming, take-off ------------------------------------------------------------
    def set_mode(self, name, timeout=15):
        mode_id = self.m.mode_mapping()[name]
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.m.set_mode(mode_id)
            end = time.time() + 1.0
            while time.time() < end:
                self.pump(0.2)
                if self.mode == name:
                    return
        raise FlightError("could not switch to " + name)

    def arm(self, timeout=180):
        """Keeps trying to arm until the pre-arm checks (GPS lock, EKF ready) pass."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                         mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
            end = time.time() + 2.0
            while time.time() < end:
                self.pump(0.2)
                if self.armed:
                    return
        raise FlightError("vehicle would not arm; last messages: %s" % self.statustext[-5:])

    def force_disarm(self, timeout=5):
        """Disarms even in flight (MAVLink magic value 21196). Used only to end a finished test."""
        self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                     mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0)
        end = time.time() + timeout
        while time.time() < end and self.armed:
            self.pump(0.2)
        return not self.armed

    def takeoff(self, alt_m, timeout=120):
        self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                     mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, alt_m)
        state = {"alt": 0.0}

        def high_enough():
            msg = self.m.messages.get("GLOBAL_POSITION_INT")
            if msg is not None:
                state["alt"] = msg.relative_alt / 1000.0
            return state["alt"] >= alt_m * 0.9

        self.wait(high_enough, timeout, "take-off to %.0f m" % alt_m)

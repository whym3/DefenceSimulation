"""Controls one simulated PX4 flight over MAVLink. Same interface as flight.Vehicle."""
import struct
import time

from pymavlink import mavutil

from .flight import FlightError, Vehicle, TELEMETRY_HZ, _CMDS

mavlink = mavutil.mavlink
PX4_MAIN_AUTO, PX4_SUB_MISSION = 4, 4   # px4_custom_mode.h


class Px4Vehicle(Vehicle):
    def __init__(self, port, connect_retries=60):
        # PX4 answers on a UDP link to whoever sends to it first, so send heartbeats until it replies.
        self.m = mavutil.mavlink_connection("udpout:127.0.0.1:%d" % port, source_system=255)
        self.sim_time_ms = 0
        self.armed = False
        self.mode = None
        self.mission_seq = 0
        self.statustext = []
        self.true_alt_m = None
        self._last_hb = 0.0
        self._param_types = {}
        deadline = time.time() + connect_retries
        while self.mode is None:
            if time.time() > deadline:
                raise FlightError("no heartbeat from PX4")
            self.pump(0.2)
        self.m.target_system = self.m.messages["HEARTBEAT"].get_srcSystem()
        self.m.target_component = mavlink.MAV_COMP_ID_AUTOPILOT1
        # Simulator truth (true altitude) is not streamed on this link unless asked for.
        self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                     mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                     mavlink.MAVLINK_MSG_ID_HIL_STATE_QUATERNION, int(1e6 / TELEMETRY_HZ), 0, 0, 0, 0, 0)

    def pump(self, timeout=0.5):
        if time.time() - self._last_hb > 0.2:
            self.m.mav.heartbeat_send(mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            self._last_hb = time.time()
        msg = self.m.recv_match(blocking=True, timeout=timeout)
        if msg is None:
            return None
        t = msg.get_type()
        if hasattr(msg, "time_boot_ms"):
            self.sim_time_ms = max(self.sim_time_ms, msg.time_boot_ms)
        if t == "HEARTBEAT" and msg.type != mavlink.MAV_TYPE_GCS:
            self.armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.mode = mavutil.mode_string_v10(msg)
        elif t == "MISSION_CURRENT":
            self.mission_seq = msg.seq
        elif t == "STATUSTEXT":
            self.statustext.append((self.sim_time_ms / 1000.0, msg.text))
        elif t == "HIL_STATE_QUATERNION":
            self.true_alt_m = msg.alt / 1000.0
        return msg

    def wait_ready(self, timeout=120):
        """Nothing to wait for: PX4 refuses to arm until its own checks pass, and start_mission retries."""

    # ---- parameters ---------------------------------------------------------------------
    def _encode(self, name, value):
        """PX4 integer parameters travel as the raw bytes of an int32 inside the float field."""
        if self._param_types.get(name) == mavlink.MAV_PARAM_TYPE_INT32:
            return struct.unpack("<f", struct.pack("<i", int(round(value))))[0], mavlink.MAV_PARAM_TYPE_INT32
        return float(value), mavlink.MAV_PARAM_TYPE_REAL32

    def _await_param(self, name, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.pump(0.2)
            if msg is not None and msg.get_type() == "PARAM_VALUE" and msg.param_id == name:
                return msg
        return None

    def set_param(self, name, value, timeout=2, tries=3):
        """Sets a parameter. Returns False if the vehicle does not have it."""
        if name not in self._param_types:
            self.m.mav.param_request_read_send(self.m.target_system, self.m.target_component, name.encode(), -1)
            msg = self._await_param(name, timeout)
            if msg is None:
                return False
            self._param_types[name] = msg.param_type
        raw, ptype = self._encode(name, value)
        for _ in range(tries):
            self.m.mav.param_set_send(self.m.target_system, self.m.target_component, name.encode(), raw, ptype)
            if self._await_param(name, timeout) is not None:
                return True
        return False

    def send_param(self, name, value):
        raw, ptype = self._encode(name, value)
        self.m.mav.param_set_send(self.m.target_system, self.m.target_component, name.encode(), raw, ptype)

    # ---- mission ------------------------------------------------------------------------
    def upload_mission(self, items, timeout=30):
        """PX4 has no home placeholder at seq 0, so the first item is dropped and every seq is one lower."""
        home, items = items[0], items[1:]
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
                if it["cmd"] == "RTL":   # an item with no position must use the "mission" frame
                    self.m.mav.mission_item_int_send(ts, tc, msg.seq, mavlink.MAV_FRAME_MISSION, _CMDS["RTL"],
                                                     0, 1, 0, 0, 0, 0, 0, 0, 0, mavlink.MAV_MISSION_TYPE_MISSION)
                    continue
                src = home if it["cmd"] == "TAKEOFF" else it   # the take-off item carries no position of its own
                lat, lon = src["lat"], src["lon"]
                self.m.mav.mission_item_int_send(
                    ts, tc, msg.seq, mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, _CMDS[it["cmd"]],
                    0, 1, 0, 0, 0, float("nan"), int(lat * 1e7), int(lon * 1e7), float(it["alt"]),
                    mavlink.MAV_MISSION_TYPE_MISSION)
            elif t == "MISSION_ACK":
                if msg.type != mavlink.MAV_MISSION_ACCEPTED:
                    raise FlightError("mission rejected, code %d" % msg.type)
                return
        raise FlightError("mission upload timed out")

    def start_mission(self, alt_m, timeout=120):
        """The mission's first item is the take-off, so arming in mission mode starts the flight."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.m.mav.command_long_send(self.m.target_system, self.m.target_component, mavlink.MAV_CMD_DO_SET_MODE, 0,
                                         mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, PX4_MAIN_AUTO, PX4_SUB_MISSION, 0, 0, 0, 0)
            self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                         mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
            end = time.time() + 1.0
            while time.time() < end:
                self.pump(0.2)
                if self.armed:
                    return
        raise FlightError("PX4 would not arm; last messages: %s" % self.statustext[-5:])

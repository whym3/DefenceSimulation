"""Starts and stops one PX4 SITL process with its built-in simulator (SIH: no graphics, no second program)."""
import filecmp
import glob
import os
import shutil
import subprocess
import time

from .sitl import Sitl

PX4_DIR = os.path.expanduser(os.environ.get("PX4_DIR", "~/px4"))
PX4_BUILD = os.path.join(PX4_DIR, "build/px4_sitl_sih")
LOGGER_TOPICS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "px4_logger_topics.txt")


class Px4Sitl(Sitl):
    """One PX4 instance. Instance N listens for the ground-station MAVLink link on UDP 18570 + N."""

    def __init__(self, workdir, home, instance=0, speedup=10, model="sihsim_quadx", boot_params=None):
        self.workdir = workdir
        self.home = home  # (lat, lon, alt_m_amsl, heading_deg)
        self.instance = instance
        self.speedup = speedup
        self.model = model
        self.boot_params = boot_params or {}
        self.port = 18570 + instance
        self.proc = None
        self._out = None

    def start(self, timeout=30):
        os.makedirs(self.workdir, exist_ok=True)
        # PX4 reads its list of logged topics from the build's etc folder (the work folder links to it).
        # With SDLOG_PROFILE 0 only that list is logged: 1 MB per flight instead of 120 MB.
        dst = os.path.join(PX4_BUILD, "etc", "logging", "logger_topics.txt")
        if not (os.path.exists(dst) and filecmp.cmp(LOGGER_TOPICS, dst, shallow=False)):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(LOGGER_TOPICS, dst)
        env = dict(os.environ, PX4_SIMULATOR="sihsim", PX4_SIM_MODEL=self.model,
                   PX4_SIM_SPEED_FACTOR=str(self.speedup), PX4_PARAM_SDLOG_PROFILE="0",
                   PX4_HOME_LAT=str(self.home[0]), PX4_HOME_LON=str(self.home[1]), PX4_HOME_ALT=str(self.home[2]))
        for name, value in self.boot_params.items():
            env["PX4_PARAM_" + name] = str(value)
        out_path = os.path.join(self.workdir, "sitl.out")
        self._out = open(out_path, "w")
        self.proc = subprocess.Popen(
            [os.path.join(PX4_BUILD, "bin", "px4"), "-d", "-i", str(self.instance), "-w", self.workdir,
             os.path.join(PX4_BUILD, "etc")],
            env=env, stdout=self._out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("PX4 exited early; see %s" % out_path)
            with open(out_path, "r", errors="replace") as f:
                if "Startup script returned successfully" in f.read():
                    return
            time.sleep(0.2)
        raise TimeoutError("PX4 did not finish starting; see %s" % out_path)

    def dataflash_logs(self):
        """The flight logs (ULog). The largest is last: PX4 opens a small extra log on some restarts."""
        return sorted(glob.glob(os.path.join(self.workdir, "log", "*", "*.ulg")), key=os.path.getsize)

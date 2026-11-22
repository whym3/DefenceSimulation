"""Starts and stops one ArduCopter SITL (software-in-the-loop) simulator process."""
import glob
import hashlib
import os
import subprocess
import time

ARDUPILOT_DIR = os.path.expanduser(os.environ.get("ARDUPILOT_DIR", "~/ardupilot"))
ARDUCOPTER_BIN = os.path.join(ARDUPILOT_DIR, "build/sitl/bin/arducopter")
COPTER_DEFAULTS = os.path.join(ARDUPILOT_DIR, "Tools/autotest/default_params/copter.parm")


def provenance(model="quad", params=None):
    """What was tested: firmware, tool version, frame model and the drone's parameter file."""
    def git(directory, *args):
        try:
            return subprocess.run(("git", "-C", directory) + args, capture_output=True, text=True).stdout.strip() or None
        except OSError:
            return None
    p = dict(model=model, ardupilot=git(ARDUPILOT_DIR, "describe", "--tags", "--match", "Copter-*", "--always", "--dirty"),
             tool_commit=git(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rev-parse", "--short", "HEAD"))
    if params:
        with open(params, "rb") as f:
            p.update(params_file=os.path.basename(params), params_sha256=hashlib.sha256(f.read()).hexdigest())
    return p


class Sitl:
    """One simulator instance. Instance N listens for MAVLink on TCP port 5760 + 10*N."""

    def __init__(self, workdir, home, instance=0, speedup=10, model="quad", extra_defaults=None):
        self.workdir = workdir
        self.home = home  # (lat, lon, alt_m_amsl, heading_deg)
        self.instance = instance
        self.speedup = speedup
        self.model = model
        self.extra_defaults = extra_defaults or []
        self.port = 5760 + 10 * instance
        self.proc = None
        self._out = None

    def start(self, timeout=30):
        os.makedirs(self.workdir, exist_ok=True)
        defaults = ",".join([COPTER_DEFAULTS] + list(self.extra_defaults))
        cmd = [
            ARDUCOPTER_BIN, "-S", "--wipe",
            "--model", self.model,
            "--speedup", str(self.speedup),
            "--defaults", defaults,
            "--home", "%.7f,%.7f,%.1f,%.1f" % tuple(self.home),
            "-I", str(self.instance),
        ]
        self._out = open(os.path.join(self.workdir, "sitl.out"), "w")
        self.proc = subprocess.Popen(cmd, cwd=self.workdir, stdout=self._out, stderr=subprocess.STDOUT)
        # SITL blocks until a client connects to SERIAL0, so don't probe the port (a probe would
        # be taken as the ground-station link). Wait for its "Waiting for connection" line instead.
        out_path = os.path.join(self.workdir, "sitl.out")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("SITL exited early; see %s" % out_path)
            with open(out_path, "r", errors="replace") as f:
                if "aiting for connection" in f.read():
                    return
            time.sleep(0.2)
        raise TimeoutError("SITL did not start listening on port %d; see %s" % (self.port, out_path))

    def wait_log_flushed(self, settle_s=0.5, timeout_s=8.0):
        """Waits until the newest DataFlash log stops growing.

        ArduPilot writes its log from a buffer. At high speedup the last tens of simulated seconds
        are still in that buffer when the drone disarms; stopping SITL at once loses them (seen at
        120x: logs ending with the drone still 10 m up).
        """
        deadline = time.time() + timeout_s
        last_size, stable_since = -1, None
        while time.time() < deadline:
            logs = self.dataflash_logs()
            size = os.path.getsize(logs[-1]) if logs else 0
            if size == last_size:
                stable_since = stable_since or time.time()
                if time.time() - stable_since >= settle_s:
                    return True
            else:
                last_size, stable_since = size, None
            time.sleep(0.1)
        return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._out:
            self._out.close()

    def dataflash_logs(self):
        return sorted(glob.glob(os.path.join(self.workdir, "logs", "*.BIN")))

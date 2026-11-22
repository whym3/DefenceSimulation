#!/usr/bin/env bash
# Clones ArduPilot at a pinned Copter release and builds the SITL (simulator) copter binary.
# Run inside WSL Ubuntu as the normal user (not root).
set -euo pipefail

TAG="${ARDUPILOT_TAG:-Copter-4.7.3}"
SRC="$HOME/ardupilot"
VENV="$HOME/venv-drone"

if [ ! -d "$VENV" ]; then
  python3 -m venv --system-site-packages "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "== pip install =="
pip install --progress-bar off --upgrade pip
# MAVProxy is not needed by the tool, so it is left out to keep setup fast.
pip install --progress-bar off "empy==3.3.4" pexpect future ptyprocess dronecan pymavlink reportlab \
    pyulog openpyxl   # last two: RflyMAD validation tools only
echo "== clone =="

if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 --branch "$TAG" https://github.com/ArduPilot/ardupilot.git "$SRC"
fi
cd "$SRC"
git submodule update --init --recursive --depth 1

./waf configure --board sitl
./waf copter

echo "BUILD_OK $(git describe --tags) -> $SRC/build/sitl/bin/arducopter"

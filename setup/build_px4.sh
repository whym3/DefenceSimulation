#!/usr/bin/env bash
# Clones PX4 at a pinned tag and builds its SITL binary with the built-in SIH simulator.
# Run inside WSL Ubuntu as the normal user. Needs apt packages: cmake ninja-build bc (and build-essential).
# PX4's own Tools/setup/ubuntu.sh is not used: it installs Python packages into the system Python.
set -euo pipefail

TAG="${PX4_TAG:-v1.18.0-rc2}"
SRC="$HOME/px4"
VENV="$HOME/venv-px4"

if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 --branch "$TAG" --recurse-submodules --shallow-submodules \
      https://github.com/PX4/PX4-Autopilot.git "$SRC"
fi
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --progress-bar off --upgrade pip
pip install --progress-bar off -r "$SRC/Tools/setup/requirements.txt"

cd "$SRC"
# px4_sitl_sih (SIH only, no Gazebo) exists from v1.18; older tags build the default SITL target.
if [ -f boards/px4/sitl/sih.px4board ]; then
  make px4_sitl_sih
  BUILD=build/px4_sitl_sih
else
  make px4_sitl_default
  BUILD=build/px4_sitl_default
fi
echo "BUILD_OK $(git describe --tags --always) -> $SRC/$BUILD/bin/px4"

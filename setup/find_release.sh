#!/usr/bin/env bash
# Lists the newest stable ArduCopter release tags and branches.
set -euo pipefail
echo "Tags:"
git ls-remote --tags https://github.com/ArduPilot/ardupilot 'refs/tags/Copter-4*' \
  | grep -v '\^{}' | awk -F/ '{print $3}' | grep -E '^Copter-4\.[0-9]+\.[0-9]+$' | sort -V | tail -5
echo "Branches:"
git ls-remote https://github.com/ArduPilot/ardupilot 'refs/heads/Copter-4*' | awk -F/ '{print $3}' | sort -V | tail -3

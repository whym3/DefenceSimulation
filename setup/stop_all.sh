#!/usr/bin/env bash
# Stops any running batch, test flights and simulators.
pkill -f 'python[^ ]* [^ ]*run_batch\.py' || true
pkill -f 'python[^ ]* [^ ]*run_one\.py' || true
pkill -f 'build/sitl/bin/arducopter' || true
pkill -f 'build/px4_sitl_sih/bin/px4' || true
sleep 2
echo "still running:"
ps -eo pid,args | grep -E 'run_batch\.py|run_one\.py|bin/arducopter|px4_sitl_sih/bin/px4' | grep -v -E 'grep|defunct' || echo "  nothing"

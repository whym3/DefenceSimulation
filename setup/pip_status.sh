#!/usr/bin/env bash
# Shows what the pip install is doing right now (child processes, recent downloads).
pid=$(pgrep -f 'venv-drone/bin/pip install' | head -1)
echo "pip pid: ${pid:-none}"
[ -n "$pid" ] && ps --ppid "$pid" -o etime,args | cut -c1-160
ps -eo etime,args | grep -E 'cc1|gcc|setup.py|build_ext|wheel|meson|cmake' | grep -v grep | cut -c1-160 | head -8
ls -t /tmp 2>/dev/null | head -5

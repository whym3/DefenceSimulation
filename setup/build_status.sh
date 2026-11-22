#!/usr/bin/env bash
# Shows how far the ArduPilot build has got.
echo "log lines: $(wc -l < ~/build.log 2>/dev/null || echo 0)"
tail -n 5 ~/build.log 2>/dev/null
if [ -d ~/ardupilot ]; then echo "source: present"; else echo "source: not cloned yet"; fi
echo "running steps:"
ps -eo etime,args --sort=-etime | grep -E 'pip|git |waf|cc1plus' | grep -v grep | cut -c1-140 | head -5

#!/usr/bin/env python3
"""Inspects one RflyMAD flight case: its TestInfo sheet, the ULog topics and the fault marker.

Usage: rflymad_inspect.py <case_dir>
The dataset is untrusted input: this script only reads it.
"""
import glob
import os
import sys

import openpyxl
from pyulog import ULog

case = sys.argv[1]
print("case:", case)
for x in glob.glob(os.path.join(case, "TestInfo*.xlsx")):
    wb = openpyxl.load_workbook(x, read_only=True, data_only=True)
    for ws in wb.worksheets:
        print("--- sheet", ws.title)
        for row in ws.iter_rows(values_only=True):
            if any(c is not None for c in row):
                print("   ", [c for c in row if c is not None])

ulgs = glob.glob(os.path.join(case, "log_*", "*.ulg")) + glob.glob(os.path.join(case, "*.ulg"))
print("--- ulog files:", ulgs)
if ulgs:
    u = ULog(ulgs[0])
    dur = (u.last_timestamp - u.start_timestamp) / 1e6
    print("duration %.0f s, %d topics" % (dur, len(u.data_list)))
    names = sorted({"%s_%d" % (d.name, d.multi_id) for d in u.data_list})
    print("topics:", ", ".join(names))
    for d in u.data_list:
        if d.name.startswith("rfly_ctrl"):
            ts = d.data["timestamp"]
            print("--- %s: %d samples, fields %s" % (d.name, len(ts), list(d.data.keys())[:20]))
            last = None
            for i in range(len(ts)):
                row = tuple(round(float(d.data[k][i]), 4) for k in d.data if k != "timestamp")
                if row != last:
                    print("   t=%.1f s  %s" % ((ts[i] - u.start_timestamp) / 1e6, row[:12]))
                    last = row

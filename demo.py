#!/usr/bin/env python3
"""One-command demo: flies a small test set and builds the PDF report, in about a minute.

Flies every fault family at every level in Delhi and Ladakh with typical wind (142 flights, one repeat each),
then writes batches/demo-<time>/report.pdf.

Usage (inside WSL Ubuntu):
    python demo.py
    python demo.py --full        # the full matrix instead: 3 conditions x 4 winds x 3 repeats (2,130 flights)
"""
import datetime
import os
import sys

import run_batch

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if "--full" in sys.argv:
        args = ["--out", os.path.join(HERE, "batches", "full-" + stamp)]
    else:
        args = ["--conditions", "delhi", "ladakh", "--winds", "typical", "--repeats", "1",
                "--out", os.path.join(HERE, "batches", "demo-" + stamp)]
    return run_batch.main(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Builds the PDF report for a finished batch (no flying).

Usage (inside WSL Ubuntu):
    python make_report.py batches/<name>            # writes batches/<name>/report.pdf
    python make_report.py batches/<name> -o out.pdf
"""
import argparse
import sys

from dtt import report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("batch")
    p.add_argument("-o", "--out", default=None)
    args = p.parse_args()
    print("report:", report.build(args.batch, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

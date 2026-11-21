#!/usr/bin/env python3
"""Plan step 12: print a sample of DIFFERENT_ENTITY decisions on *unlabelled* hits, a few
per reason code, so a person can read each clear and check it rests on a fact that is
really there.  The practice labels are too few to prove a clear is safe.

    python3 tools/review_clears.py output/dev.jsonl --data dev [--per-code 5]
"""
import argparse
import json
import os
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--data", required=True)
    ap.add_argument("--per-code", type=int, default=5)
    args = ap.parse_args()
    labelled = set()
    path = os.path.join(args.data, "practice_labels.jsonl")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            labelled = {json.loads(line)["hit_id"] for line in f if line.strip()}
    by_code = defaultdict(list)
    with open(args.predictions, encoding="utf-8") as f:
        for row in map(json.loads, f):
            if row["decision"] == "DIFFERENT_ENTITY" and row["hit_id"] not in labelled:
                by_code[row["reason_code"]].append(row)
    for code in sorted(by_code):
        rows = sorted(by_code[code], key=lambda r: r["hit_id"])
        step = max(1, len(rows) // args.per_code)
        print("\n== %s: %d unlabelled clears, showing %d" % (code, len(rows), min(args.per_code, len(rows))))
        for row in rows[::step][:args.per_code]:
            print("- %s (%s) evidence %s\n  %s" % (row["hit_id"], row["customer_record_id"],
                                                  ", ".join(row["evidence"]), row["reason"]))


if __name__ == "__main__":
    main()

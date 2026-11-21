#!/usr/bin/env python3
"""Decide every hit in a data room folder.

    python3 run.py --data dataset --out out/decisions.jsonl
    python3 run.py --data /path/to/unseen            # dev/*.jsonl layout works too
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import Counter

from screening.data import load
from screening.engine import Engine
from screening import text as T


def to_public(r: dict) -> dict:
    return {
        "hit_id": r["hit_id"],
        "alert_id": r["alert_id"],
        "decision": r["decision"],
        "reason_code": r["reason_code"],
        "customer_record_id": r["customer_record_id"],
        "evidence": r["evidence"],
        "explanation": r["explanation"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset")
    ap.add_argument("--out", default="out/decisions.jsonl")
    ap.add_argument("--trace", default="out/trace.json", help="full evidence trail for the UI")
    args = ap.parse_args(argv)

    t0 = time.time()
    ds = load(args.data)
    print(f"loaded {len(ds.alerts)} alerts, {len(ds.hits)} hits, {len(ds.customers)} customers "
          f"in {time.time() - t0:.1f}s", file=sys.stderr)
    eng = Engine(ds)
    print(f"indexed in {time.time() - t0:.1f}s", file=sys.stderr)
    results = eng.run()
    print(f"decided {len(results)} hits in {time.time() - t0:.1f}s", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(to_public(r), ensure_ascii=False) + "\n")
    csv_path = os.path.splitext(args.out)[0] + ".csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hit_id", "alert_id", "decision", "reason_code", "customer_record_id", "evidence", "explanation"])
        for r in results:
            w.writerow([r["hit_id"], r["alert_id"], r["decision"], r["reason_code"],
                        r["customer_record_id"] if r["customer_record_id"] is not None else "",
                        "; ".join(r["evidence"]), r["explanation"]])
    if args.trace:
        from screening.trace import build_trace
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(build_trace(eng, results), f, ensure_ascii=False)
    print(Counter(r["decision"] for r in results), file=sys.stderr)
    print(Counter(r["reason_code"] for r in results), file=sys.stderr)
    print(f"wrote {args.out}, {csv_path}" + (f", {args.trace}" if args.trace else ""), file=sys.stderr)
    return results


if __name__ == "__main__":
    main()

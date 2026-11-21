#!/usr/bin/env python3
"""Decide every hit in a data room folder.

    system/run <data folder> <output file>                 # what the organisers call
    python3 system/run.py dev output/dev.jsonl             # the same
    python3 system/run.py dev output/dev.jsonl --trace out/trace.json --csv   # + analyst console data
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

FIELDS = ["hit_id", "alert_id", "decision", "reason_code", "customer_record_id", "reason", "evidence"]


def to_public(r: dict) -> dict:
    return {
        "hit_id": r["hit_id"],
        "alert_id": r["alert_id"],
        "decision": r["decision"],
        "reason_code": r["reason_code"],
        "customer_record_id": r["customer_record_id"],
        "reason": r["explanation"],
        "evidence": r["evidence"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data", help="data room folder (alerts.jsonl, hits.jsonl, ...)")
    ap.add_argument("out", help="output file, one JSON line per hit")
    ap.add_argument("--trace", help="also write the full evidence trail for the analyst console")
    ap.add_argument("--csv", action="store_true", help="also write a CSV copy next to the output file")
    args = ap.parse_args(argv)

    t0 = time.time()
    ds = load(args.data)
    print(f"loaded {len(ds.alerts)} alerts, {len(ds.hits)} hits, {len(ds.customers)} customers "
          f"in {time.time() - t0:.1f}s", file=sys.stderr)
    eng = Engine(ds)
    results = eng.run()
    print(f"decided {len(results)} hits in {time.time() - t0:.1f}s", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(to_public(r), ensure_ascii=False) + "\n")
    written = [args.out]
    if args.csv:
        csv_path = os.path.splitext(args.out)[0] + ".csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            for r in results:
                p = to_public(r)
                w.writerow([p["hit_id"], p["alert_id"], p["decision"], p["reason_code"],
                            p["customer_record_id"] if p["customer_record_id"] is not None else "",
                            p["reason"], "; ".join(p["evidence"])])
        written.append(csv_path)
    if args.trace:
        from screening.trace import build_trace
        os.makedirs(os.path.dirname(args.trace) or ".", exist_ok=True)
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(build_trace(eng, results), f, ensure_ascii=False)
        written.append(args.trace)
    print(dict(Counter(r["decision"] for r in results)), file=sys.stderr)
    print(f"wrote {', '.join(written)}", file=sys.stderr)
    return results


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prove the run is reproducible, and time it.

Two questions, not one:

  * Does the same input give the same output?  The brief scores five runs on the unseen set
    giving the same decision and reason code every time.
  * Does *equivalent* input give the same output?  The unseen set is a different file with
    different rows in a different order, so any accidental dependence on the order lines
    happen to sit in would show up there and nowhere else.  `--shuffle` writes a folder
    whose every table is reordered and checks each hit decides the same way.

    tools/repeat.py --runs 5
    tools/repeat.py --runs 2 --shuffle
    tools/repeat.py --runs 2 --llm          # include the model, if a key is set
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RUN = os.path.join(ROOT, "system", "run")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def one_run(data_folder, target, use_llm, env):
    command = [RUN, data_folder, target, "--quiet"]
    if not use_llm:
        command.append("--no-llm")
    started = time.time()
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    seconds = time.time() - started
    if result.returncode != 0:
        raise SystemExit("run failed: %s" % result.stderr.strip())
    return read(target), seconds


def shuffled_folder(source, destination, seed=20261121):
    """The same data, every table's rows in a different order."""
    os.makedirs(destination, exist_ok=True)
    rng = random.Random(seed)
    for entry in sorted(os.listdir(source)):
        path = os.path.join(source, entry)
        if not os.path.isfile(path):
            continue
        if not entry.lower().endswith(".jsonl"):
            shutil.copy2(path, os.path.join(destination, entry))
            continue
        with open(path, encoding="utf-8") as fh:
            lines = [line for line in fh if line.strip()]
        rng.shuffle(lines)
        with open(os.path.join(destination, entry), "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    return destination


def compare(rows_a, rows_b, by_hit=False):
    """Differences between two outputs, as a list of human-readable lines."""
    if not by_hit:
        problems = []
        if len(rows_a) != len(rows_b):
            problems.append("different number of lines: %d vs %d" % (len(rows_a), len(rows_b)))
        for index, (left, right) in enumerate(zip(rows_a, rows_b)):
            if left != right:
                problems.append("line %d differs for %s" % (index + 1, left.get("hit_id")))
        return problems
    left = {row["hit_id"]: row for row in rows_a}
    right = {row["hit_id"]: row for row in rows_b}
    problems = []
    for hit_id in sorted(set(left) | set(right)):
        if hit_id not in left or hit_id not in right:
            problems.append("%s is in only one output" % hit_id)
            continue
        if left[hit_id] != right[hit_id]:
            for field in ("decision", "reason_code", "customer_record_id", "reason", "evidence"):
                if left[hit_id].get(field) != right[hit_id].get(field):
                    problems.append(
                        "%s %s: %r vs %r"
                        % (hit_id, field, left[hit_id].get(field), right[hit_id].get(field))
                    )
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="dev")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--unseen-hits", type=int, default=550)
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if not args.llm:
        env.pop("OPENROUTER_API_KEY", None)

    directory = tempfile.mkdtemp(prefix="sponl-repeat-")
    status = 0
    try:
        print("%d runs of %s%s" % (args.runs, args.data, "  with the model" if args.llm else ""))
        baseline, times = None, []
        for index in range(args.runs):
            target = os.path.join(directory, "run%d.jsonl" % index)
            rows, seconds = one_run(args.data, target, args.llm, env)
            times.append(seconds)
            if baseline is None:
                baseline = rows
                print("  run 1: %d lines in %.1fs" % (len(rows), seconds))
                continue
            problems = compare(baseline, rows)
            print("  run %d: %.1fs  %s"
                  % (index + 1, seconds, "identical" if not problems else "DIFFERS"))
            for problem in problems[:10]:
                print("      %s" % problem)
                status = 1

        print()
        print("timing")
        print("  per run: min %.1fs  max %.1fs  mean %.1fs"
              % (min(times), max(times), sum(times) / len(times)))
        if baseline:
            per_hit = sum(times) / len(times) / len(baseline)
            print("  %d hits at %.1f ms each" % (len(baseline), per_hit * 1000))
            print("  extrapolated to %d hits: %.1fs (the brief allows 1800s)"
                  % (args.unseen_hits, per_hit * args.unseen_hits))

        if args.shuffle:
            print()
            print("the same data with every table reordered")
            source = shuffled_folder(args.data, os.path.join(directory, "shuffled"))
            target = os.path.join(directory, "shuffled.jsonl")
            rows, seconds = one_run(source, target, args.llm, env)
            problems = compare(baseline, rows, by_hit=True)
            print("  %d lines in %.1fs  %s"
                  % (len(rows), seconds, "every hit decides the same" if not problems
                     else "%d DIFFERENCES" % len(problems)))
            for problem in problems[:15]:
                print("      %s" % problem)
                status = 1
            same_order = [row["hit_id"] for row in rows] == [row["hit_id"] for row in baseline]
            print("  output follows the hits file's own order: %s" % ("same" if same_order
                                                                      else "reordered, as expected"))
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    return status


if __name__ == "__main__":
    sys.exit(main())

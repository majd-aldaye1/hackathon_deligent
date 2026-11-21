#!/usr/bin/env python3
"""Check the output's format, and score it against the practice labels.

The data room ships no validate.py, so this implements the format rules from the brief and
the published cost matrix.

    tools/score.py output/dev.jsonl --data dev
    tools/score.py output/dev.jsonl --data dev --score dev/practice_labels.jsonl
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import loader, model  # noqa: E402

# Cost of saying X when the truth is Y.  Clearing a real match costs 60; reviewing a false
# positive costs 3.
COST = {
    ("DIFFERENT_ENTITY", "DIFFERENT_ENTITY"): 0,
    ("DIFFERENT_ENTITY", "SAME_ENTITY"): 3,
    ("DIFFERENT_ENTITY", "REVIEW"): 3,
    ("SAME_ENTITY", "DIFFERENT_ENTITY"): 60,
    ("SAME_ENTITY", "SAME_ENTITY"): 0,
    ("SAME_ENTITY", "REVIEW"): 2,
    ("REVIEW", "DIFFERENT_ENTITY"): 60,
    ("REVIEW", "SAME_ENTITY"): 2,
    ("REVIEW", "REVIEW"): 0,
}

REQUIRED = ("hit_id", "alert_id", "decision", "reason_code", "customer_record_id",
            "reason", "evidence")

# A sentence ends at a full stop followed by a space and a capital, or at the end of the
# text.  Written this way so "Md. Saidul Islam" and "U.S. Courts" do not read as two.
SENTENCE_END = re.compile(r"[.!?](?:\s+(?=[A-Z0-9])|\s*$)")


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            line = line.strip()
            if line:
                out.append((number, json.loads(line)))
    return out


def check_format(rows, data):
    """Every rule the brief states about the output."""
    problems = []
    known_ids = set()
    if data is not None:
        known_ids |= set(data.customer_by_id)
        known_ids |= {c["check_id"] for c in data.kyc_checks}
        known_ids |= {n["note_id"] for n in data.notes}
        known_ids |= {r["result_id"] for r in data.search_results}
        known_ids |= {a["account_id"] for a in data.accounts}
        known_ids |= {o["kyc_applicant_id"] for o in data.onboarding}
    seen = set()
    for number, row in rows:
        where = "line %d" % number
        for field in REQUIRED:
            if field not in row:
                problems.append("%s: missing %s" % (where, field))
        if row.get("hit_id") in seen:
            problems.append("%s: duplicate hit_id %s" % (where, row.get("hit_id")))
        seen.add(row.get("hit_id"))
        decision = row.get("decision")
        code = row.get("reason_code")
        if decision not in model.DECISIONS:
            problems.append("%s: decision %r is not one of the three" % (where, decision))
        if code not in model.REASON_CODES:
            problems.append("%s: reason_code %r is not in POLICY's table" % (where, code))
        elif model.REASON_CODES[code] != decision:
            problems.append(
                "%s: reason_code %s does not belong to decision %s" % (where, code, decision)
            )
        record = row.get("customer_record_id")
        if record is not None and record != "AMBIGUOUS" and data is not None:
            if record not in data.customer_by_id:
                problems.append("%s: customer_record_id %s is not a record" % (where, record))
        reason = row.get("reason") or ""
        sentences = len(SENTENCE_END.findall(reason))
        if not 2 <= sentences <= 6:
            problems.append(
                "%s: reason has %d sentences, expected 2 to 4" % (where, sentences)
            )
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            problems.append("%s: evidence is not a list" % where)
        elif known_ids:
            for item in evidence:
                if item not in known_ids:
                    problems.append("%s: evidence %s is not a record in the data" % (where, item))
                if item.startswith("H-"):
                    problems.append("%s: evidence %s is a hit, not a record" % (where, item))
    if data is not None:
        expected = {h["hit_id"] for h in data.hits}
        missing = expected - seen
        extra = seen - expected
        for hit_id in sorted(missing)[:10]:
            problems.append("no line for hit %s" % hit_id)
        for hit_id in sorted(extra)[:10]:
            problems.append("line for unknown hit %s" % hit_id)
    return problems


def score(rows, labels, data=None):
    by_hit = {row.get("hit_id"): row for _n, row in rows}
    total = 0
    unsafe = []
    confusion = collections.Counter()
    code_ok = record_ok = evidence_exact = evidence_overlap = 0
    missing = []
    for label in labels:
        hit_id = label["hit_id"]
        row = by_hit.get(hit_id)
        if row is None:
            missing.append(hit_id)
            continue
        truth = label["decision"]
        said = row.get("decision")
        total += COST[(truth, said)]
        confusion[(truth, said)] += 1
        if said == "DIFFERENT_ENTITY" and truth != "DIFFERENT_ENTITY":
            unsafe.append((hit_id, truth, row.get("reason_code")))
        if row.get("reason_code") in set(label.get("reason_codes", ())):
            code_ok += 1
        accepted = set(label.get("customer_record_ids", ()))
        if row.get("customer_record_id") in accepted:
            record_ok += 1
        want = set(label.get("evidence", ()))
        got = set(row.get("evidence", ()))
        if want == got:
            evidence_exact += 1
        if want & got:
            evidence_overlap += 1
    return {
        "labels": len(labels),
        "missing": missing,
        "cost": total,
        "cost_per_hit": total / float(len(labels)) if labels else 0.0,
        "unsafe_clears": unsafe,
        "confusion": confusion,
        "code_ok": code_ok,
        "record_ok": record_ok,
        "evidence_exact": evidence_exact,
        "evidence_overlap": evidence_overlap,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions")
    parser.add_argument("--data", default="dev", help="the data folder, for the format check")
    parser.add_argument("--score", dest="labels", default=None,
                        help="a practice_labels.jsonl to score against")
    args = parser.parse_args(argv)

    rows = read_jsonl(args.predictions)
    data = loader.load(args.data) if args.data and os.path.isdir(args.data) else None

    print("%d lines in %s" % (len(rows), args.predictions))
    problems = check_format(rows, data)
    if problems:
        print("FORMAT: %d problems" % len(problems))
        for problem in problems[:25]:
            print("   -", problem)
    else:
        print("FORMAT: ok")

    counts = collections.Counter(row.get("decision") for _n, row in rows)
    codes = collections.Counter(row.get("reason_code") for _n, row in rows)
    print("decisions: %s" % {k: counts[k] for k in model.DECISIONS if counts[k]})
    share = {k: "%.1f%%" % (100.0 * counts[k] / len(rows)) for k in model.DECISIONS if counts[k]}
    print("share:     %s" % share)
    print("codes:     %s" % dict(codes.most_common()))

    labels = None
    if args.labels and os.path.isfile(args.labels):
        labels = [row for _n, row in read_jsonl(args.labels)]
    elif data is not None and data.practice_labels:
        labels = data.practice_labels
    if labels:
        result = score(rows, labels, data)
        print()
        print("scored against %d practice labels" % result["labels"])
        print("  cost:            %d  (%.2f per hit)" % (result["cost"], result["cost_per_hit"]))
        print("  UNSAFE CLEARS:   %d" % len(result["unsafe_clears"]))
        for hit_id, truth, code in result["unsafe_clears"]:
            print("      %s truth=%s said=DIFFERENT_ENTITY/%s" % (hit_id, truth, code))
        print("  reason_code accepted: %d/%d" % (result["code_ok"], result["labels"]))
        print("  customer_record_id:   %d/%d" % (result["record_ok"], result["labels"]))
        print("  evidence exact:       %d/%d   overlapping: %d/%d"
              % (result["evidence_exact"], result["labels"],
                 result["evidence_overlap"], result["labels"]))
        print("  truth -> said:")
        for truth in model.DECISIONS:
            row = {said: result["confusion"][(truth, said)] for said in model.DECISIONS
                   if result["confusion"][(truth, said)]}
            if row:
                print("      %-18s %s" % (truth, row))
        if result["missing"]:
            print("  no prediction for: %s" % result["missing"][:10])
        return 1 if (problems or result["unsafe_clears"]) else 0
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Audit every DIFFERENT_ENTITY decision for the kind of weakness that costs 60.

462 of the 819 decisions are clears and only 28 of them are covered by a practice label, so
eyeballing a sample is not a review.  This walks all of them, works out exactly which facts
carried each one, and flags the structural weaknesses worth a human look:

  * a clear resting on a declared date of birth with no verified check behind it
  * a clear whose whole country set, on either side, came from one record
  * a clear where the name agrees, so the decision rests on the other fact alone
  * a clear resting on a date of birth read out of prose or a search result
  * a clear resting on a partially known date

    tools/review_clears.py
    tools/review_clears.py --flag name-agrees --show 10
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import (countries, customer_facts, decide, hit_facts, loader,  # noqa: E402
                   name_variants, persons, resolve, rules)


def weaknesses(sheet, facts, decision, verdict):
    """What, if anything, about this clear deserves a second look."""
    found = []
    code = decision.reason_code

    if code in ("DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"):
        used = sheet.dob_facts()
        if sheet.verified_dob is None:
            found.append("declared-dob")
        if any(f.value.month is None for f in used):
            found.append("partial-customer-dob")
        if facts.dob_origin == hit_facts.FROM_SEARCH:
            found.append("hit-dob-from-search")
        elif facts.dob_origin == hit_facts.FROM_NOTES:
            found.append("hit-dob-from-prose")
        if any(getattr(f, "provisional", False) for f in used + list(facts.dobs)):
            found.append("provisional-dob")

    if code == "LOCATION_MISMATCH":
        customer_sources = {s for f in sheet.country_facts() for s in f.source_ids}
        if len(sheet.country_keys()) == 1:
            found.append("one-customer-country")
        if len(customer_sources) == 1:
            found.append("one-country-source")
        if len(facts.countries) == 1:
            found.append("one-hit-country")
        if sheet.verified_country is None:
            found.append("no-document-country")

    if code == "DECEASED":
        if facts.death is not None and facts.death.value.month is None:
            found.append("partial-death-date")

    if code == "NAME_MISMATCH_VERIFIED":
        if verdict.context.get("name_agrees"):
            found.append("record-name-agrees")

    if code != "NAME_MISMATCH_VERIFIED" and verdict.context.get("name_agrees"):
        found.append("name-agrees")
    if verdict.context.get("dob_agrees") and code != "DOB_MISMATCH":
        found.append("dob-agrees")
    if len(decision.evidence) == 1:
        found.append("one-record-cited")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="dev")
    parser.add_argument("--flag", default=None, help="show the hits carrying this flag")
    parser.add_argument("--code", default=None, help="only this reason code")
    parser.add_argument("--show", type=int, default=6)
    args = parser.parse_args(argv)

    data = loader.load(args.data)
    variants = (
        name_variants.from_raw(data.name_variants_raw) if data.name_variants_raw else None
    )
    index = persons.Persons(data)
    engine = decide.Engine(data, index, variants)
    labelled = {label["hit_id"] for label in data.practice_labels}

    by_code = collections.Counter()
    flags = collections.Counter()
    rows = []
    for hit in data.hits:
        decision = engine.decide(hit)
        if decision.decision != "DIFFERENT_ENTITY":
            continue
        by_code[decision.reason_code] += 1
        screened = engine.screened(hit["alert_id"])
        resolution = engine.resolution(hit["alert_id"])
        facts = hit_facts.gather(data, hit, variants)
        sheet = engine.sheet(resolution.persons[0])
        verdict = rules.evaluate(sheet, facts, screened, variants)
        found = weaknesses(sheet, facts, decision, verdict)
        for flag in found:
            flags[flag] += 1
        rows.append((hit, decision, sheet, facts, found, hit["hit_id"] in labelled))

    print("%d clears, %d of them covered by a practice label"
          % (len(rows), sum(1 for r in rows if r[5])))
    print()
    print("by reason code")
    for code, count in by_code.most_common():
        print("  %-26s %4d" % (code, count))
    print()
    print("structural weaknesses (a hit may carry several)")
    for flag, count in flags.most_common():
        print("  %-26s %4d" % (flag, count))
    clean = sum(1 for r in rows if not r[4])
    print("  %-26s %4d" % ("(nothing flagged)", clean))

    if args.flag or args.code:
        print()
        chosen = [
            r for r in rows
            if (not args.flag or args.flag in r[4])
            and (not args.code or r[1].reason_code == args.code)
        ]
        print("%d clears match; showing %d" % (len(chosen), min(len(chosen), args.show)))
        for hit, decision, sheet, facts, found, is_labelled in chosen[:args.show]:
            print("-" * 76)
            print("%s  %s%s" % (hit["hit_id"], decision.reason_code,
                                "  [labelled]" if is_labelled else ""))
            print("  hit      %-34r %s" % (hit["name"], ", ".join(facts.countries) or "no country"))
            print("  hit dob  %-34s from %s" % (
                [d.iso() for d in facts.dob_values()], facts.dob_origin))
            print("  customer %-34s %s" % (
                ", ".join(sheet.record_ids), countries.display(sheet.country_keys())))
            print("  verified %-34r dob %s" % (
                sheet.verified_name.value if sheet.verified_name else None,
                sheet.verified_dob.value.iso() if sheet.verified_dob else None))
            print("  flags    %s" % ", ".join(found))
            print("  evidence %s" % decision.evidence)
            print("  reason   %s" % decision.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())

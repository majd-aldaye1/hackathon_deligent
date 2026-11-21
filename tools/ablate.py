#!/usr/bin/env python3
"""Re-run every hit with one source of facts switched off, and report what changes.

The unseen set words its free text differently, so the question that matters is not "does
the extractor work on dev" but "what happens to the decision when it does not fire".  A
decision that moves to REVIEW is a loss of 3; one that moves to DIFFERENT_ENTITY is the
60-cost mistake, so those are listed hit by hit.

    tools/ablate.py --data dev
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import decide, hit_facts, loader, name_variants, notes_regex, search_anchor  # noqa: E402


def decide_all(data, variants):
    return {d.hit_id: d for d in decide.build(data, variants).decide_all()}


ABLATIONS = {
    "no places-lived from notes": [
        (notes_regex, "places_lived", lambda note: []),
    ],
    "no identity checks written up in notes": [
        (notes_regex, "parse_kyc_note", lambda note: None),
    ],
    "no dates of birth from hit profile notes": [
        (hit_facts, "birth_dates_from_notes", lambda notes: []),
    ],
    "no dates of birth from search results": [
        (search_anchor, "matching_results", lambda *a, **k: []),
    ],
    "no free text at all (fields only)": [
        (notes_regex, "places_lived", lambda note: []),
        (notes_regex, "parse_kyc_note", lambda note: None),
        (hit_facts, "birth_dates_from_notes", lambda notes: []),
        (search_anchor, "matching_results", lambda *a, **k: []),
    ],
}


def run_with(data, variants, patches):
    saved = [(module, name, getattr(module, name)) for module, name, _new in patches]
    try:
        for module, name, new in patches:
            setattr(module, name, new)
        return decide_all(data, variants)
    finally:
        for module, name, original in saved:
            setattr(module, name, original)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="dev")
    parser.add_argument("--show", type=int, default=8, help="how many dangerous flips to list")
    args = parser.parse_args(argv)

    data = loader.load(args.data)
    variants = (
        name_variants.from_raw(data.name_variants_raw) if data.name_variants_raw else None
    )
    base = decide_all(data, variants)
    print("baseline: %s" % dict(collections.Counter(d.decision for d in base.values())))
    print()

    worst = 0
    for title, patches in sorted(ABLATIONS.items()):
        other = run_with(data, variants, patches)
        moves = collections.Counter()
        dangerous = []
        for hit_id, before in sorted(base.items()):
            after = other[hit_id]
            if before.decision == after.decision:
                continue
            moves[(before.decision, after.decision)] += 1
            if after.decision == "DIFFERENT_ENTITY":
                dangerous.append((hit_id, before.decision, after.reason_code))
        print("%s" % title)
        print("   decisions that change: %d" % sum(moves.values()))
        for (before, after), count in sorted(moves.items()):
            flag = "  <-- would become a clear" if after == "DIFFERENT_ENTITY" else ""
            print("      %-18s -> %-18s %4d%s" % (before, after, count, flag))
        print("   NEW CLEARS (each one a possible 60-cost mistake): %d" % len(dangerous))
        for hit_id, before, code in dangerous[:args.show]:
            print("      %s  was %s, would clear on %s" % (hit_id, before, code))
        worst = max(worst, len(dangerous))
        print()
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())

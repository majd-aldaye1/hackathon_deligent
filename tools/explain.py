#!/usr/bin/env python3
"""Show everything behind one hit's decision: both fact sheets and which rules fired.

    tools/explain.py H-13E1CF
    tools/explain.py H-13E1CF --data dev
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import (countries, customer_facts, decide, hit_facts, kyc, loader,  # noqa: E402
                    name_variants, notes_regex, persons, resolve, rules)


def line(label, value):
    print("  %-22s %s" % (label, value))


def show_facts(fact_list):
    return ", ".join(
        "%s%s" % (_render(f.value), ("[" + ",".join(f.source_ids) + "]") if f.source_ids else "")
        for f in fact_list
    ) or "-"


def _render(value):
    return value.iso() if hasattr(value, "iso") else str(value)


def explain(data, hit_id, variants=None):
    hit = data.hit_by_id.get(hit_id)
    if hit is None:
        print("no hit %s" % hit_id)
        return 1
    alert = data.alert_by_id[hit["alert_id"]]
    screened = resolve.Screened(alert)
    index = persons.Persons(data)
    resolution = resolve.resolve_customer(data, index, screened, variants)
    facts = hit_facts.gather(data, hit, variants)

    print("=" * 78)
    print("HIT %s   alert %s" % (hit_id, alert["alert_id"]))
    print("-" * 78)
    print("SCREENED")
    line("name", repr(screened.name))
    line("entity type", screened.entity_type)
    line("date of birth", screened.dob)
    line("country / city", "%s / %r" % (screened.country, screened.city))
    line("link", ", ".join("%s = %r" % link for link in screened.links) or resolve.NO_LINK)
    line("screened at", screened.screened_at)

    print("-" * 78)
    print("HIT FACTS")
    line("names", " | ".join(facts.names))
    line("entity type", facts.entity_type)
    line("countries", ", ".join(facts.countries) or "-")
    line("dates of birth", "%s  (from %s)" % (show_facts(facts.dobs), facts.dob_origin))
    line("listing phrase", repr(facts.listing_phrase))
    line("earliest report", facts.earliest_report.value.iso() if facts.earliest_report else "-")
    line("date of death", facts.death.value.iso() if facts.death else "-")
    if hit.get("profile_notes"):
        paragraph = hit_facts.first_paragraph(hit["profile_notes"])
        line("first paragraph", (paragraph[:150] + ("..." if len(paragraph) > 150 else "")))

    print("-" * 78)
    print("CUSTOMER: resolved by %s -> %d person(s)" % (resolution.how, len(resolution.persons)))
    if not resolution.found:
        line("result", "no customer record fits the alert")

    for person in resolution.persons:
        sheet = customer_facts.gather(data, person, variants)
        print("  person %s" % ", ".join(person))
        for record_id in person:
            record = data.customer_by_id[record_id]
            print("    %s  %-28r dob=%-18s nat=%-14s res=%-14s city=%s"
                  % (record_id, record.get("full_name"), record.get("dob"),
                     record.get("nationality"), record.get("residence_country"),
                     record.get("city")))
            for check in kyc.checks(data, record_id):
                print("        %s %-9s %-26r %-14s %s %s"
                      % (check["check_id"], check["result"], check.get("verified_name"),
                         check.get("verified_dob"), check.get("document_country"),
                         check.get("checked_at")))
        for note_id in sheet.note_ids:
            note = [n for n in data.notes if n["note_id"] == note_id][0]
            kind = note["channel"]
            extra = ""
            if kind == notes_regex.KYC_CHANNEL:
                parsed = notes_regex.parse_kyc_note(note)
                if parsed:
                    extra = " -> name=%r dob=%s country=%s approved=%s" % (
                        parsed.verified_name,
                        parsed.verified_dob.iso() if parsed.verified_dob else None,
                        parsed.document_country, parsed.approved,
                    )
            else:
                found = notes_regex.places_lived(note)
                if found:
                    extra = " -> lived in %s" % ", ".join(found)
            print("        %s [%s] %s%s" % (note_id, kind, note["text"][:90], extra))
        line("verified name", show_facts([sheet.verified_name] if sheet.verified_name else []))
        line("verified usable", sheet.verified_name_usable())
        line("names compared", " | ".join(sheet.names()))
        line("dates of birth", show_facts(sheet.dob_facts()))
        line("countries", show_facts(sheet.country_facts()))

        print("    RULES")
        for rule in rules.CONTRADICTIONS:
            finding = rule(sheet, facts, screened, variants)
            mark = "FIRES" if finding else "  -  "
            print("      %-5s %s" % (mark, rule.__name__))
        verdict = rules.evaluate(sheet, facts, screened, variants)
        print("    VERDICT %s / %s  codes=%s evidence=%s"
              % (verdict.decision, verdict.code, verdict.codes(), verdict.sources()))

    print("-" * 78)
    engine = decide.Engine(data, index, variants)
    decision = engine.decide(hit)
    print("DECISION  %s / %s   customer_record_id=%s"
          % (decision.decision, decision.reason_code, decision.customer_record_id))
    print("EVIDENCE  %s" % decision.evidence)
    print("REASON    %s" % decision.reason)
    label = [l for l in data.practice_labels if l["hit_id"] == hit_id]
    if label:
        want = label[0]
        print("-" * 78)
        print("LABEL     %s / %s  record=%s" % (
            want["decision"], want["reason_codes"], want["customer_record_ids"]))
        print("EVIDENCE  %s" % want["evidence"])
        print("REASON    %s" % want["reference_reason"])
        print("PATH      %s" % " ".join(want["path"]))
    print("=" * 78)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hit_ids", nargs="+")
    parser.add_argument("--data", default="dev")
    args = parser.parse_args(argv)
    data = loader.load(args.data)
    variants = (
        name_variants.from_raw(data.name_variants_raw) if data.name_variants_raw else None
    )
    status = 0
    for hit_id in args.hit_ids:
        status |= explain(data, hit_id, variants)
    return status


if __name__ == "__main__":
    sys.exit(main())

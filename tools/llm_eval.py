#!/usr/bin/env python3
"""Measure the language-model fallback on text the patterns cannot read.

The development folder gives the fallback nothing to do: every note and profile in it is
read by a regular expression.  Its whole purpose is the unseen set, which words the same
facts differently, so the only honest way to measure it is on reworded text.

Every case below is first checked against the deterministic path.  A case the patterns
already read is not a test of the fallback and is reported as such.

    tools/llm_eval.py                       # the default model
    tools/llm_eval.py --models a,b          # compare two
    tools/llm_eval.py --twice               # also check the answers are stable
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import countries, hit_facts, llm, notes_regex  # noqa: E402

# (text, expected) — expected is a sorted list of ISO dates, or [] for "say nothing".
BIRTH_CASES = [
    ("Court papers filed in the spring of 1999 describe the defendant, by then 24 years "
     "of age, as the ringleader.", ["1974", "1975"]),
    ("A man of 52 at the time, Oladele Afolabi came before the tribunal in October 2011.",
     ["1958", "1959"]),
    ("Birth was registered in Lagos in the year 1961 according to the civil registry.",
     ["1961"]),
    ("His fifty-third birthday had passed by the time of the April 2008 hearing.", []),
    ("On June 14, 2024, the United States Office of Foreign Assets Control added Tor "
     "Fredrik Vejdeland to its Specially Designated Nationals List.", []),
    ("Associated with Sanctioned Entity: DAD, KARIM - Entity ID: 13938136, "
     "PK-National Counter Terrorism Authority-Proscribed Persons.", []),
    ("According to the urdupoint.com; October 11, 2025: In October 2025, police recovered "
     "stolen goods worth PKR 11,000,000, including PKR 3,100,000 in cash.", []),
    ("The subject, whose date of birth the registry records as 7 Feb 1970, was charged.",
     ["1970-02-07"]),
]

# (text, expected country keys)
PLACE_CASES = [
    ("The customer confirmed that between 2010 and 2014 their household and their "
     "employment were both situated in the Czech Republic.", ["Czech Republic"]),
    ("Caller explained they had spent the years 2016 to 2019 making a life for themselves "
     "in Aotearoa New Zealand.", ["New Zealand"]),
    ("Between 2008 and 2012 the account holder's permanent address and place of work were "
     "in the Republic of Korea.", ["South Korea"]),
    ("Customer asked why a transfer to Nigeria was delayed. Explained the cut-off times.",
     []),
    ("Customer reported a lost card. Card frozen and a replacement ordered to the address "
     "on file.", []),
    ("The passport the customer presented was issued by Ireland.", []),
]

# (text, expected name / iso dob / country / approved)
CHECK_CASES = [
    ("Verification outcome: PASS. Document: passport (Ireland). Holder: SIOBHAN MURPHY. "
     "Birth: 3rd of February 1981. Reviewed 2025-02-01.",
     ("SIOBHAN MURPHY", "1981-02-03", "Ireland", True)),
    ("Identity file closed on 2024-07-02. The Spanish national identity card tendered by "
     "ALEJANDRO NUNEZ, whose birth is recorded as the twelfth of May 1966, was accepted.",
     ("ALEJANDRO NUNEZ", "1966-05-12", "Spain", True)),
    ("Document review 2025-03-03: the driving licence offered by DECLAN BYRNE could not be "
     "authenticated and the file was returned. Stated birth 1988-04-19, issuer Ireland.",
     (None, None, None, False)),
    ("The Persona check for GRACE TURNER was successful on 2024-05-22; document provided: "
     "driving licence (United Kingdom), 23 June 1991.",
     ("GRACE TURNER", "1991-06-23", "United Kingdom", True)),
]


def regex_birth(text):
    return sorted(d.iso() for d in hit_facts.birth_dates_from_notes(text))


def regex_places(text):
    return sorted(notes_regex.places_lived({"channel": "email", "text": text}))


def regex_check(text):
    parsed = notes_regex.parse_kyc_note(
        {"note_id": "NOTE-X", "created_at": "2025-01-01", "channel": "kyc", "text": text}
    )
    if parsed is None:
        return (None, None, None, None)
    return (
        parsed.verified_name,
        parsed.verified_dob.iso() if parsed.verified_dob else None,
        parsed.document_country,
        parsed.approved,
    )


def show_gap():
    """Which cases the deterministic path already handles, and which it cannot."""
    print("how the deterministic path does on these cases")
    gaps = {"birth": 0, "places": 0, "check": 0}
    for text, want in BIRTH_CASES:
        got = regex_birth(text)
        if got != sorted(want):
            gaps["birth"] += 1
        print("  birth  regex=%-22s want=%-22s %s" % (got, sorted(want),
                                                      "gap" if got != sorted(want) else "ok"))
    for text, want in PLACE_CASES:
        got = regex_places(text)
        if got == sorted(want):
            note = "ok"
        elif got and not want:
            # The scan is deliberately permissive: a spurious country *blocks* a clear,
            # which is the cheap mistake.  The fallback is never asked about these,
            # because it is only consulted when the scan finds nothing.
            note = "over-extracts (blocks a clear, the safe direction)"
        else:
            gaps["places"] += 1
            note = "gap"
        print("  place  regex=%-22s want=%-22s %s" % (got, sorted(want), note))
    for text, want in CHECK_CASES:
        got = regex_check(text)
        if want[0] is None:
            matched = got[3] is False  # a refusal: only the verdict matters
        else:
            matched = got[1] == want[1] and got[3] is True
        if not matched:
            gaps["check"] += 1
        print("  check  regex=%-46s %s" % (str(got)[:46], "gap" if not matched else "ok"))
    print("  gaps the fallback has to close: %s" % gaps)
    print()
    return gaps


def score_model(model, key, twice=False):
    client = llm.Client(key=key, model=model)
    extractor = llm.Extractor(client)
    started = time.time()
    right = total = 0
    problems = []

    for text, want in BIRTH_CASES:
        total += 1
        found = extractor.hit_birth(text)
        got = sorted(d.iso() for d in found.dates) if found else []
        if got == sorted(want):
            right += 1
        else:
            problems.append("birth: wanted %s, got %s  <<%s>>" % (sorted(want), got, text[:60]))

    for text, want in PLACE_CASES:
        total += 1
        got = sorted(p.country for p in extractor.note_places(text))
        if got == sorted(want):
            right += 1
        else:
            problems.append("place: wanted %s, got %s  <<%s>>" % (sorted(want), got, text[:60]))

    for text, want in CHECK_CASES:
        total += 1
        found = extractor.note_check(text)
        if want[0] is None:
            got_ok = found is None or not found.is_approved
            name_ok = dob_ok = country_ok = True
        else:
            got_ok = found is not None and found.is_approved
            name_ok = bool(found) and _same_name(found.name, want[0])
            dob_ok = bool(found) and found.dob is not None and found.dob.iso() == want[1]
            country_ok = bool(found) and found.country == countries.key(want[2])
        if got_ok and name_ok and dob_ok and country_ok:
            right += 1
        else:
            problems.append(
                "check: wanted %s, got %s  <<%s>>"
                % (want,
                   (found.name, found.dob and found.dob.iso(), found.country, found.approved)
                   if found else None,
                   text[:60])
            )

    stable = None
    if twice:
        second = llm.Extractor(llm.Client(key=key, model=model))
        stable = True
        for text, _want in BIRTH_CASES:
            a = extractor.hit_birth(text)
            b = second.hit_birth(text)
            if [d.iso() for d in (a.dates if a else [])] != [d.iso() for d in (b.dates if b else [])]:
                stable = False
        for text, _want in PLACE_CASES:
            if sorted(p.country for p in extractor.note_places(text)) != sorted(
                p.country for p in second.note_places(text)
            ):
                stable = False

    return {
        "model": model,
        "right": right,
        "total": total,
        "seconds": time.time() - started,
        "usage": client.usage.summary(),
        "problems": problems,
        "stable": stable,
    }


def _same_name(got, want):
    from system import norm

    return bool(got) and set(norm.words(got)) == set(norm.words(want))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="openai/gpt-4o-mini,openai/gpt-oss-20b")
    parser.add_argument("--twice", action="store_true")
    args = parser.parse_args(argv)

    show_gap()
    key = llm.api_key() or llm.key_from_dotenv()
    if not key:
        print("no OPENROUTER_API_KEY: nothing to measure, the system runs regex-only")
        return 0

    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        result = score_model(model, key, args.twice)
        print("%s" % result["model"])
        print("   right: %d/%d   wall clock %.1fs   %s"
              % (result["right"], result["total"], result["seconds"], result["usage"]))
        if result["stable"] is not None:
            print("   same answers on a second pass: %s" % result["stable"])
        for problem in result["problems"]:
            print("     - %s" % problem)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

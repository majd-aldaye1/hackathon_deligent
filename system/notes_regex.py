"""Reading the two facts that hide in free-text support notes.

POLICY.md principle 4: an approved identity check may be "recorded by the KYC provider or
only in a note by the onboarding team".  Principle 6: the countries tied to a customer
include "places the notes say they lived".

Both are extracted field by field rather than template by template, because the unseen set
words these notes differently.  Every extraction returns the verbatim span it came from,
so step 10's LLM fallback can be held to the same standard and a caller can cite the text.
"""

import re

from . import countries, dates, norm

KYC_CHANNEL = "kyc"

MONTH = "|".join(dates.MONTH_NAMES)

# A date in any of the shapes the providers write.  Kept loose on purpose: `dates.parse`
# is the authority on what is really a date.
DATE = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{1,2}\s+(?:%s)\s+\d{4}"
    r"|(?:%s)\s+\d{1,2},\s*\d{4})" % (MONTH, MONTH)
)

# A bare year, accepted only when a cue marks it as a date of birth.
YEAR = r"(?:1[89]\d{2}|20\d{2})"
DATE_OR_YEAR = r"(?:%s|%s)" % (DATE, YEAR)

# Words that mark a date as the date of the check, not a date of birth.
_CHECK_DATE_MARKER = re.compile(
    r"\b(?:on|as\s+of|valid\s+as\s+of|conducted\s+on|performed\s+on|reviewed\s+on"
    r"|carried\s+out\s+on|completed\s+on|effective)\s*$",
    re.I,
)

# Words that mark a nearby date as a date of birth.
_DOB_CUE = re.compile(
    r"\b(?:dates?\s+of\s+birth|d\.?\s?o\.?\s?b\.?|born|birth\s*date|birthday|birth)\b",
    re.I,
)

_ANY_DATE = re.compile(DATE_OR_YEAR, re.I)

# A date in brackets straight after the subject's name is their date of birth in these
# notes, whether or not a cue says so.
_DOB_BRACKETED = re.compile(r"\(\s*(?:dob\s*:?\s*)?(" + DATE + r")\s*\)", re.I)

# How far from a cue a date may sit and still be the date of birth it refers to.
_CUE_WINDOW = 30
_CUE_WINDOW_YEAR_ONLY = 20

# A run of two or more capitalised-throughout words is how these notes write the subject's
# name.  Label words that are also upper case must not be mistaken for it.
_NOT_A_NAME = frozenset(
    [
        "DOB", "D.O.B", "DOB:", "ID", "KYC", "NAME", "N/A", "NA", "PASSPORT", "OK",
        "AND", "THE", "FOR", "VIA", "ON", "FROM", "UK", "US", "USA", "EU", "AKA",
        "SSN", "TIN", "PEP", "SOE", "CEO", "LLC", "LTD", "GMBH", "SA", "SE", "BV",
    ]
)
_TOKEN = re.compile(r"\S+")
_STRIP = " \t.,;:()[]{}\"'’"

# Stemmed, because the unseen set will conjugate these differently: "confirms" as well as
# "confirmed", "vetted" as well as "verified".
_APPROVED_CUES = re.compile(
    r"\b(verif\w*|validat\w*|confirm\w*|clear(?:s|ed|ing)?|pass(?:es|ed|ing)?"
    r"|approv\w*|success\w*|complet\w*|match(?:es|ed|ing)?|vett\w*|vetted"
    r"|accept\w*|authenticat\w*|establish\w*|scan)\b",
    re.I,
)
# A refusal outranks an approval: "verification failed" is not an approval.
_REFUSED_CUES = re.compile(
    r"\b(reject\w*|refus\w*|declin\w*|fail\w*|unsuccessful|invalid\w*|expir\w*"
    r"|laps\w*|inconclusive|mismatch\w*|discrepan\w*|forged|fraudulent"
    r"|could\s+not|unable\s+to|was\s+not\s+\w+|did\s+not\s+\w+|does\s+not\s+\w+"
    r"|no\s+match|not\s+verified|pending|referred)\b",
    re.I,
)


class Extracted(object):
    """A value, and the verbatim span of text it was read from."""

    __slots__ = ("value", "quote")

    def __init__(self, value, quote):
        self.value = value
        self.quote = quote

    def __repr__(self):
        return "Extracted(%r, %r)" % (self.value, self.quote)


def date_of_birth(text):
    """The date of birth a note states, never the date the check was run.

    These notes carry two dates and put them in either order, so direction is no guide:
    "whose 1986-12-10 date of birth was confirmed on 2025-03-10" and "lists 06/01/1998 as
    her DOB, is valid as of 2024-08-15" both place the check date on the far side of the
    cue.  The date **nearest** a birth cue wins, and a date introduced by "on" or "as of"
    is never eligible.
    """
    if not text:
        return None
    cues = [match.span() for match in _DOB_CUE.finditer(text)]
    best = None
    for match in _ANY_DATE.finditer(text):
        before = text[max(0, match.start() - 24):match.start()]
        # "on" marks the date of the check — unless a birth cue introduced it, as in
        # "who was born on 27/06/1969" or "born in Bangladesh on 13/07/1983".
        if _CHECK_DATE_MARKER.search(before) and not _DOB_CUE.search(before):
            continue
        parsed = dates.parse(match.group(0))
        if parsed is None:
            continue
        if not cues:
            continue
        distance = min(
            min(abs(match.start() - end), abs(start - match.end()))
            for start, end in cues
        )
        window = _CUE_WINDOW if parsed.month else _CUE_WINDOW_YEAR_ONLY
        if distance > window:
            continue
        # nearest wins; a full date beats a bare year at the same distance
        rank = (distance, 0 if parsed.month else 1, match.start())
        if best is None or rank < best[0]:
            best = (rank, parsed, match.group(0))
    if best is not None:
        return Extracted(best[1], best[2])
    # No cue, but a date in brackets after the name is a date of birth in these notes.
    bracketed = _DOB_BRACKETED.search(text)
    if bracketed:
        parsed = dates.parse(bracketed.group(1))
        if parsed is not None:
            return Extracted(parsed, bracketed.group(0).strip())
    return None


def _is_name_word(token):
    """A word written entirely in capitals, which is how these notes set the subject's name.

    Tested character by character rather than with [A-Z], so "FERNÁNDEZ" and "PAWEŁ"
    count.  Label words that are also upper case, and runs of digits, do not.
    """
    word = token.strip(_STRIP)
    if not word or word.upper() in _NOT_A_NAME:
        return False
    letters = [c for c in word if c.isalpha()]
    if len(letters) < 2:
        return False
    return all(c.isupper() for c in letters)


def subject_name(text):
    """The name the note says the document belongs to.

    The longest run of capitalised-throughout words wins.  A run of one word is accepted
    too: records like "N/a Gilbert" and "Sani 0000 0000" really do have a one-part name,
    and principle 8 already refuses to decide such a customer on name.
    """
    if not text:
        return None
    runs = []
    current = []
    for match in _TOKEN.finditer(text):
        if _is_name_word(match.group(0)):
            current.append(match)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    best = None
    for run in runs:
        words = [m.group(0).strip(_STRIP) for m in run]
        candidate = " ".join(words)
        if len(words) == 1 and len([c for c in candidate if c.isalpha()]) < 3:
            continue
        # The quote is the span as written, which may carry punctuation the value drops:
        # "MD. SAIDUL ISLAM" in the note, "MD SAIDUL ISLAM" as the name.
        quote = text[run[0].start():run[-1].end()]
        rank = (len(words), len(candidate))
        if best is None or rank > best[0]:
            best = (rank, Extracted(candidate, quote))
    return best[1] if best else None


def document_country(text):
    """The country that issued the document, when the note names exactly one."""
    if not text:
        return None
    found = countries.mentioned_in(text)
    if len(found) != 1:
        return None
    return Extracted(found[0], _country_quote(text, found[0]))


def _country_quote(text, key):
    """A short verbatim span around the country name, for citation."""
    for name in sorted(set([key] + [key.lower()]), key=len, reverse=True):
        index = norm.fold(text).find(norm.fold(name))
        if index >= 0:
            return text[max(0, index - 20):index + len(name) + 10].strip()
    return text[:60].strip()


def approval(text):
    """True when the note records a check that passed, False when it records one that did
    not, None when it says nothing either way.

    A refusal cue outranks an approval cue: "verification failed" is not an approval.
    """
    if not text:
        return None
    if _REFUSED_CUES.search(text):
        return False
    if _APPROVED_CUES.search(text):
        return True
    return None


class NoteCheck(object):
    """An identity check recorded only in a note."""

    __slots__ = ("note_id", "checked_at", "verified_name", "verified_dob",
                 "document_country", "approved", "quotes")

    def __init__(self, note_id, checked_at, verified_name=None, verified_dob=None,
                 document_country=None, approved=None, quotes=None):
        self.note_id = note_id
        self.checked_at = checked_at
        self.verified_name = verified_name
        self.verified_dob = verified_dob
        self.document_country = document_country
        self.approved = approved
        self.quotes = dict(quotes or {})

    @property
    def is_approved(self):
        return self.approved is True

    def __repr__(self):
        return "NoteCheck(%s, %r, %s, %s)" % (
            self.note_id, self.verified_name, self.verified_dob, self.document_country
        )


def parse_kyc_note(note):
    """An identity check written up in a note, or None when the note is not one.

    Only `channel == "kyc"` notes are read this way: a support note that happens to
    mention a passport is not a record of a check.
    """
    if note.get("channel", "") != KYC_CHANNEL:
        return None
    text = note.get("text", "")
    approved = approval(text)
    if approved is None:
        return None
    name = subject_name(text)
    dob = date_of_birth(text)
    country = document_country(text)
    if name is None and dob is None and country is None:
        return None
    quotes = {}
    for key, found in (("verified_name", name), ("verified_dob", dob),
                       ("document_country", country)):
        if found is not None:
            quotes[key] = found.quote
    return NoteCheck(
        note_id=note.get("note_id", ""),
        checked_at=dates.parse(note.get("created_at")),
        verified_name=name.value if name else None,
        verified_dob=dob.value if dob else None,
        document_country=country.value if country else None,
        approved=approved,
        quotes=quotes,
    )


def places_lived(note):
    """Countries a non-KYC note says the customer lived in.

    POLICY principle 6 counts "places the notes say they lived" among the customer's
    countries.  Across the whole development set every non-KYC note that names a country
    is such a statement, and none names two, so naming a country is the signal.
    """
    if note.get("channel", "") == KYC_CHANNEL:
        return []
    return countries.mentioned_in(note.get("text", ""))

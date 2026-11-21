"""The hit's facts, gathered wherever they are.

POLICY.md principle 5: "A hit's date of birth may be its `dobs` field, a sentence in the
first paragraph of its profile notes ..., or, when neither gives one, web search results
for its name. ... The countries tied to a hit are its `countries`, `nationality`,
`citizenship`, `addresses` (the last part of each) and `place_of_birth`; "International"
and "Europe" are not countries.  Dated reports are exactly the English lines in the profile
notes of the form "According to …; September 10, 2025: …"; other wordings do not count.
... For companies, only the `dobs` field is an incorporation date."

The hit itself is the subject of the decision, never evidence for it, so facts read from
the hit carry no source ids.  Facts read from a search result carry that result's id,
which is why the practice labels cite `SR-…` and never `H-…`.
"""

import re

from . import countries, dates, names, search_anchor
from .facts import Fact, merge

# Where a date of birth came from, which the reason text has to say.
FROM_FIELD = "field"
FROM_NOTES = "notes"
FROM_SEARCH = "search"

MONTH = "|".join(dates.MONTH_NAMES)

# POLICY.md principle 5: "exactly the English lines in the profile notes of the form
# "According to …; September 10, 2025: …"".  The colon after the date is part of that form
# (decision log D22): 13 lines put a semicolon there instead and are not dated reports.
DATED_REPORT = re.compile(
    r"^\s*According to .*?;\s*(%s)\s+(\d{1,2}),\s*(\d{4})\s*:" % MONTH
)

# An outright statement of birth in the first paragraph.
_BORN_ON = re.compile(
    r"\bborn\s+(?:on|in)\s+("
    r"\d{1,2}\s+(?:%s)\s+\d{4}"
    r"|(?:%s)\s+\d{1,2},\s*\d{4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|1[89]\d{2}|20\d{2})" % (MONTH, MONTH),
    re.I,
)

# A one-to-three digit number that is not part of a longer one.  Without the lookarounds,
# "PKR 11,000,000" reads as an age of 100 — and an invented date of birth could clear a
# hit that really is the customer.
_AGE_NUM = r"(?<!\d)(?<![\d][,.\-/])(\d{1,3})(?!\d)(?![,.\-/]\d)"

# An age stated against a date.  Deliberately a closed list of phrasings: a bare number in
# a paragraph of prose is far more likely to be a quantity or a sum of money than an age.
_AGE_CUES = [
    re.compile(r"\baged\s+" + _AGE_NUM, re.I),
    re.compile(r"\bage\s+of\s+" + _AGE_NUM, re.I),
    re.compile(r"\bage\s*:\s*" + _AGE_NUM, re.I),
    re.compile(_AGE_NUM + r"[-\s]years?[-\s]old\b", re.I),
    re.compile(r"\ba\s+" + _AGE_NUM + r"[-\s]year[-\s]old\b", re.I),
    re.compile(r"\b(?:he|she|they)\s+was\s+" + _AGE_NUM, re.I),
    re.compile(r"\bthey\s+were\s+" + _AGE_NUM, re.I),
    re.compile(r"\bthen\s+" + _AGE_NUM, re.I),
    re.compile(r"\bwas\s+" + _AGE_NUM + r"\s+when\b", re.I),
    re.compile(r"\bat\s+(?:the\s+age\s+of\s+)?" + _AGE_NUM + r"\s+when\b", re.I),
    re.compile(r"\bwho\s+at\s+" + _AGE_NUM, re.I),
    re.compile(r"\bat\s+which\s+point\s+(?:he|she|they)\s+was\s+" + _AGE_NUM, re.I),
    re.compile(_AGE_NUM + r"\s+years?\s+of\s+age\b", re.I),
    re.compile(r"\bat\s+age\s+" + _AGE_NUM, re.I),
    re.compile(r"\breached\s+" + _AGE_NUM, re.I),
    re.compile(r",\s*(?:a\s+)?" + _AGE_NUM + r"\s*,", re.I),
]

# A first paragraph that talks about a birth or an age, whether or not we could pin a date
# to it.  Used only to tell "this hit states no date of birth" from "this hit states one we
# could not read" — the second must not be treated as the first.
_BIRTH_TALK = re.compile(r"\b(born|birth|birthday|aged?|years?\s+old|year-old)\b", re.I)

_MONTH_YEAR = re.compile(r"\b(%s)\s+(\d{4})\b" % MONTH, re.I)
_BARE_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

# "International" and "Europe" are excluded by system/countries.py.
_COUNTRY_FIELDS = ("countries", "nationality", "citizenship")


def first_paragraph(text):
    """The first paragraph of the profile notes, which is where a birth sentence sits."""
    if not text:
        return ""
    return (text or "").split("\n\n")[0].strip()


def dated_reports(profile_notes):
    """Every strictly formed dated report, as dates, earliest first."""
    found = []
    for line in (profile_notes or "").splitlines():
        match = DATED_REPORT.match(line)
        if not match:
            continue
        parsed = dates.parse("%s %s, %s" % (match.group(1), match.group(2), match.group(3)))
        if parsed is not None:
            found.append(parsed)
    return sorted(found)


def earliest_dated_report(profile_notes):
    found = dated_reports(profile_notes)
    return found[0] if found else None


def _is_dated_report(paragraph):
    return bool(DATED_REPORT.match(paragraph.splitlines()[0])) if paragraph else False


def _ages_in(text):
    """Every distinct age the paragraph states, through the closed list of phrasings."""
    found = set()
    for pattern in _AGE_CUES:
        for match in pattern.finditer(text):
            value = int(match.group(1))
            if 0 < value < 120:
                found.add(value)
    return sorted(found)


def _single_year(text):
    years = {int(m.group(2)) for m in _MONTH_YEAR.finditer(text)}
    if len(years) == 1:
        return years.pop()
    years = {int(y) for y in _BARE_YEAR.findall(text)}
    if len(years) == 1:
        return years.pop()
    return None


def birth_dates_from_notes(profile_notes):
    """The date of birth the first paragraph states, if it states one unambiguously.

    An outright "was born in 1952" is taken as given.  Otherwise an age against a date
    gives the two years POLICY allows — but only when the paragraph states exactly one age
    and exactly one year, so that a provider's dated report, which carries many dates and
    many numbers, yields nothing.
    """
    paragraph = first_paragraph(profile_notes)
    if not paragraph:
        return []
    born = _BORN_ON.search(paragraph)
    if born:
        parsed = dates.parse(born.group(1))
        if parsed is not None:
            return [parsed]
    # A dated report is the provider's own prose about an event, not a sentence about the
    # subject's age.  POLICY gives it its own job (the earliest one bounds how young the
    # customer could have been), so it never supplies a date of birth.
    if _is_dated_report(paragraph):
        return []
    ages = _ages_in(paragraph)
    if len(ages) != 1:
        return []
    year = _single_year(paragraph)
    if year is None:
        return []
    age = ages[0]
    return [dates.Date(y) for y in sorted({year - age, year - age - 1})]


def states_a_birth(profile_notes):
    """True when the first paragraph talks about a birth or an age."""
    paragraph = first_paragraph(profile_notes)
    if not paragraph or _is_dated_report(paragraph):
        return False
    return bool(_BIRTH_TALK.search(paragraph))


def country_keys(hit):
    """Every country tied to the hit, in POLICY principle 5's order."""
    keys = []
    for field in _COUNTRY_FIELDS:
        for value in hit.get(field, ()) or ():
            key = countries.key_from_place(value)
            if key and key not in keys:
                keys.append(key)
    for value in hit.get("addresses", ()) or ():
        key = countries.key_from_place(value)
        if key and key not in keys:
            keys.append(key)
    key = countries.key_from_place(hit.get("place_of_birth", ""))
    if key and key not in keys:
        keys.append(key)
    return keys


def hit_names(hit):
    """Every name and alias the hit offers, the listed name first.

    "Aliases count as names, nicknames included."  `best_matching_name` and the split
    first/middle/last fields are the same name written differently, and more candidate
    names can only make agreement easier — which makes a name-based clear harder, the safe
    direction against the costly mistake.
    """
    out = []
    candidates = [hit.get("name", ""), hit.get("best_matching_name", "")]
    parts = [hit.get(f, "") for f in ("first_name", "middle_name", "last_name")]
    joined = " ".join(p for p in parts if p)
    if joined:
        candidates.append(joined)
    candidates.extend(hit.get("aliases", ()) or ())
    for candidate in candidates:
        candidate = (candidate or "").strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out


class HitFacts(object):
    """What the watchlist profile says."""

    def __init__(self, hit_id, alert_id, entity_type, names_, country_keys_, dobs,
                 dob_origin, death, earliest_report, listing_phrase, result_ids=(),
                 dob_unreadable=False):
        self.hit_id = hit_id
        self.alert_id = alert_id
        self.entity_type = entity_type
        self.names = list(names_)
        self.countries = list(country_keys_)
        # Fact values are dates; source ids are search-result ids, or empty when the hit
        # itself supplied them.
        self.dobs = list(dobs)
        self.dob_origin = dob_origin
        self.death = death
        self.earliest_report = earliest_report
        self.listing_phrase = listing_phrase
        self.result_ids = tuple(result_ids)
        # The profile talks about a birth or an age but we could not read a date out of it.
        # Not a fact, only a reason not to treat the silence as "this hit has no date".
        self.dob_unreadable = bool(dob_unreadable) and not dobs

    @property
    def is_company(self):
        return self.entity_type == "Company"

    def dob_values(self):
        return [f.value for f in self.dobs]

    def dob_list(self):
        """The hit's dates of birth as the agreement sentence lists them."""
        values = self.dob_values()
        if not values:
            return ""
        if self.dob_origin == FROM_FIELD:
            return _join([v.iso() for v in values])
        return _join([str(y) for y in sorted({v.year for v in values})])

    def dob_description(self):
        """How the reason text should introduce the hit's dates of birth."""
        values = self.dob_values()
        if not values:
            return ""
        if self.dob_origin == FROM_FIELD and len(values) == 1:
            return "listed date of birth is %s" % values[0].iso()
        if self.dob_origin == FROM_FIELD:
            return "listed dates of birth are %s" % _join([v.iso() for v in values])
        years = sorted({v.year for v in values})
        where = "profile notes" if self.dob_origin == FROM_NOTES else "search results"
        if len(years) == 1:
            return "%s put its birth year at %d" % (where, years[0])
        return "%s put its birth year at %s" % (where, _join([str(y) for y in years]))

    def __repr__(self):
        return "HitFacts(%s, %r, dobs=%s from %s)" % (
            self.hit_id, self.names[:1], [v.iso() for v in self.dob_values()], self.dob_origin
        )


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return "%s or %s" % (", ".join(items[:-1]), items[-1])


def gather(data, hit, variants=None):
    """Build the fact sheet for one hit."""
    keys = country_keys(hit)
    phrase = search_anchor.listing_phrase(
        hit.get("primary_category", ""), hit.get("categories", ())
    )
    is_company = hit.get("entity_type", "") == "Company"

    # POLICY principle 5's priority: the field, then the notes, then search results.
    dobs, origin, result_ids = [], None, ()
    field_dates = dates.parse_many(hit.get("dobs", ()))
    if field_dates:
        dobs = [Fact(d) for d in field_dates]
        origin = FROM_FIELD
    elif not is_company:
        # "For companies, only the `dobs` field is an incorporation date."
        from_notes = birth_dates_from_notes(hit.get("profile_notes", ""))
        if from_notes:
            dobs = [Fact(d) for d in from_notes]
            origin = FROM_NOTES
        else:
            results = search_anchor.matching_results(
                data, names.query_keys(hit.get("name", "")), phrase, keys
            )
            found = []
            for result in results:
                for year in search_anchor.birth_years(result.get("snippet", "")):
                    found.append(Fact(dates.Date(year), (result.get("result_id", ""),)))
            if found:
                dobs = merge(found)
                origin = FROM_SEARCH
                result_ids = tuple(sorted({r for f in dobs for r in f.source_ids}))

    death = None
    parsed_death = dates.parse(hit.get("deceased_date", ""))
    if parsed_death is not None:
        death = Fact(parsed_death)

    report = earliest_dated_report(hit.get("profile_notes", ""))

    return HitFacts(
        hit_id=hit.get("hit_id", ""),
        alert_id=hit.get("alert_id", ""),
        entity_type=hit.get("entity_type", ""),
        names_=hit_names(hit),
        country_keys_=keys,
        dobs=dobs,
        dob_origin=origin,
        death=death,
        earliest_report=Fact(report) if report is not None else None,
        listing_phrase=phrase,
        result_ids=result_ids,
        dob_unreadable=(not is_company) and states_a_birth(hit.get("profile_notes", "")),
    )

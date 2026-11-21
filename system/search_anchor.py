"""Deciding which web search results are about the hit, and what they say about its age.

POLICY.md principle 5: "Most search results are about other people with the same name: a
result is about the hit only if it describes the same kind of listing in a country tied to
the hit.  The kind of listing follows the hit's primary category (or its first category) ...
This form and the listing phrases above are worded the same in the unseen set."

So the test is a plain string match for one phrase plus one of the hit's countries, and
the age a result gives is read with a regex.  No model is involved.
"""

import re

from . import countries, dates

# POLICY.md principle 5, verbatim.
LISTING_PHRASES = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_PHRASE = "named on a watchlist"
ALL_PHRASES = sorted(set(LISTING_PHRASES.values()) | {OTHER_PHRASE})


def listing_phrase(primary_category, categories):
    """The phrase a result must carry to be about this hit.

    "The kind of listing follows the hit's primary category (or its first category)";
    "any other category" gets the watchlist phrase.
    """
    category = (primary_category or "").strip()
    if not category:
        for candidate in categories or ():
            if candidate.strip():
                category = candidate.strip()
                break
    return LISTING_PHRASES.get(category.lower(), OTHER_PHRASE)


MONTH = "|".join(dates.MONTH_NAMES)
_MONTH_YEAR = re.compile(r"\b(%s)\s+(\d{4})\b" % MONTH, re.I)
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
# A standalone one-to-three digit number: the age.  The lookarounds reject anything that
# is part of a longer number — "250,000", "1,310", "2019-03", "45/60" — while still
# accepting the age in "Elena Johansson, 51, as the subject of enforcement action".
_AGE = re.compile(r"(?<!\d)(?<![\d][,.\-/])(\d{1,3})(?!\d)(?![,.\-/]\d)")


def is_about(result, phrase, country_keys):
    """True when the result carries the hit's listing phrase and one of its countries."""
    if not phrase or not country_keys:
        return False
    text = "%s %s" % (result.get("title", ""), result.get("snippet", ""))
    if phrase not in text:
        return False
    return bool(countries.mentioned_in(text, keys=set(country_keys)))


def matching_results(data, query_keys, phrase, country_keys):
    """Every search result that is about this hit, ordered by result id."""
    seen, found = set(), []
    for key in query_keys or ():
        for result in data.search_by_query.get(key.lower(), ()):
            result_id = result.get("result_id", "")
            if result_id in seen:
                continue
            seen.add(result_id)
            if is_about(result, phrase, country_keys):
                found.append(result)
    return sorted(found, key=lambda r: r.get("result_id", ""))


def birth_years(text):
    """The two birth years an "aged N in <month> <year>" sentence allows.

    POLICY.md principle 5: "an age at a date gives two possible birth years: someone aged
    45 in March 2019 was born in 1973 or 1974".  Returns [] unless the text gives exactly
    one age and exactly one year, so an ambiguous sentence yields nothing rather than a
    guess — an invented date of birth could clear a hit that is the customer.
    """
    if not text:
        return []
    ages = _AGE.findall(text)
    if len(ages) != 1:
        return []
    age = int(ages[0])
    if not 0 < age < 120:
        return []
    years = {int(m.group(2)) for m in _MONTH_YEAR.finditer(text)}
    if len(years) != 1:
        years = {int(y) for y in _YEAR.findall(text)}
        if len(years) != 1:
            return []
    year = years.pop()
    return sorted({year - age, year - age - 1})

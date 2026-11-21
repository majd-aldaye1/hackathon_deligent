"""Partial-aware dates.

The provider and the bank write dates in seven different shapes and often give only part
of one.  A missing part is unknown, never a mismatch (POLICY.md principles 6 and 7), so a
date is a year with an optional month and an optional day, and every comparison looks only
at the parts both sides give.
"""

import re

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_NUMBER = {}
for _i, _name in enumerate(MONTH_NAMES, start=1):
    MONTH_NUMBER[_name.lower()] = _i
    MONTH_NUMBER[_name.lower()[:3]] = _i
MONTH_NUMBER["sept"] = 9

MONTH_PATTERN = "|".join(MONTH_NAMES)


class Date(object):
    """A date known to the year, and maybe to the month and day."""

    __slots__ = ("year", "month", "day", "text")

    def __init__(self, year, month=None, day=None, text=None):
        self.year = int(year)
        self.month = int(month) if month else None
        self.day = int(day) if day else None
        self.text = text if text is not None else self.iso()

    def iso(self):
        if self.month and self.day:
            return "%04d-%02d-%02d" % (self.year, self.month, self.day)
        if self.month:
            return "%04d-%02d" % (self.year, self.month)
        return "%04d" % self.year

    def key(self):
        return (self.year, self.month or 0, self.day or 0)

    def __eq__(self, other):
        return isinstance(other, Date) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __lt__(self, other):
        return self.key() < other.key()

    def __repr__(self):
        return "Date(%s)" % self.iso()


_PATTERNS = [
    # (regex, (year group, month group, day group)); month groups may be names
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), (3, 2, 1)),  # day first
    (re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$"), (3, 2, 1)),  # day first
    (re.compile(r"^(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$"), (3, 2, 1)),
    (re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})$"), (3, 1, 2)),
    (re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})\s+(\d{4})$"), (3, 1, 2)),
    (re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$"), (2, 1, None)),
    (re.compile(r"^(\d{4})-(\d{1,2})$"), (1, 2, None)),
    (re.compile(r"^(\d{1,2})/(\d{4})$"), (2, 1, None)),
    (re.compile(r"^(\d{4})$"), (1, None, None)),
]


def _month_value(raw):
    if raw is None:
        return None
    raw = raw.strip().strip(".").lower()
    if raw.isdigit():
        value = int(raw)
        return value if 1 <= value <= 12 else None
    return MONTH_NUMBER.get(raw)


def parse(text):
    """One date string -> Date, or None when it is not a date we recognise."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    raw = re.sub(r"\s+", " ", raw)
    for pattern, (yi, mi, di) in _PATTERNS:
        m = pattern.match(raw)
        if not m:
            continue
        year = int(m.group(yi))
        if not 1000 <= year <= 2999:
            return None
        month = _month_value(m.group(mi)) if mi else None
        if mi and month is None:
            continue  # e.g. "Foo 1990" is not a date
        day = int(m.group(di)) if di else None
        if day is not None and not 1 <= day <= 31:
            return None
        return Date(year, month, day, text=raw)
    return None


def parse_many(values):
    """Parse a list of date strings, keeping only what parses, in input order."""
    out = []
    for value in values or ():
        date = parse(value)
        if date is not None and date not in out:
            out.append(date)
    return out


def is_complete(date):
    return date is not None and date.month is not None and date.day is not None


# ------------------------------------------------------------------ comparisons


def equal_where_both_known(left, right):
    """Equal in every part both sides give (POLICY principle 2's "date of birth equal to
    the screened one in every part both give")."""
    if left is None or right is None:
        return False
    if left.year != right.year:
        return False
    if left.month and right.month and left.month != right.month:
        return False
    if left.day and right.day and left.day != right.day:
        return False
    return True


def agrees(customer, hit):
    """POLICY principle 7: the customer's birth year is one of the hit's possible birth
    years and every part both give is equal; a birth year alone can agree with a full date.
    """
    return equal_where_both_known(customer, hit)


def contradicts(customer, hit):
    """POLICY principle 6, "Date of birth": the customer's birth year is more than 1 year
    outside the hit's, or both give a month in the same year and the months (or days) differ.
    """
    if customer is None or hit is None:
        return False
    if abs(customer.year - hit.year) > 1:
        return True
    if customer.year != hit.year:
        return False  # one year apart is neither agreement nor contradiction
    if customer.month and hit.month:
        if customer.month != hit.month:
            return True
        if customer.day and hit.day and customer.day != hit.day:
            return True
    return False


def any_agrees(customer, hit_dates):
    return any(agrees(customer, h) for h in hit_dates or ())


def all_contradict(customer, hit_dates):
    """"every birth date the hit gives is contradicted ... One agreeing date is enough to
    prevent this." """
    hit_dates = list(hit_dates or ())
    if customer is None or not hit_dates:
        return False
    return all(contradicts(customer, h) for h in hit_dates)


def before(date, other):
    """True when `date` is before `other`, comparing only the parts both give.

    Used for the date of death against the screening date, so an unknown month or day
    must not invent an ordering: "2022-03" is before "2026-11-05" but not before
    "2022-03-20".
    """
    if date is None or other is None:
        return False
    if date.year != other.year:
        return date.year < other.year
    if date.month is None or other.month is None:
        return False
    if date.month != other.month:
        return date.month < other.month
    if date.day is None or other.day is None:
        return False
    return date.day < other.day


def years_between(earlier, later):
    """Whole years from `earlier` to `later`, counting only what is known.

    Returns the largest age the person could have had, so "younger than 16" is only
    reported when they certainly were.
    """
    if earlier is None or later is None:
        return None
    age = later.year - earlier.year
    if earlier.month and later.month:
        if later.month < earlier.month:
            age -= 1
        elif later.month == earlier.month and earlier.day and later.day and later.day < earlier.day:
            age -= 1
    return age


def max_age_at(birth, when):
    """The oldest the person could be at `when`, given an incompletely known birth date."""
    if birth is None or when is None:
        return None
    upper = Date(birth.year, birth.month or 1, birth.day or 1)
    return years_between(upper, when)

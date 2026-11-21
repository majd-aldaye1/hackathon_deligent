"""Find the customer behind an alert.

POLICY.md principle 2: "Follow whatever link the alert carries.  A link can lead to more
than one person; the screened details then pick between them, as in a search without a
link.  Without a link, find the records that fit what was screened ... Never use another
customer's records."

This module turns an alert into a set of customer records.  Step 4 adds the search for
alerts that carry no link, and the merging of records into persons.
"""

from . import countries, dates, names, norm

ACCOUNT_REF = "account_ref"
LOGIN_HANDLE = "login_handle"
EMAIL = "email"
NO_LINK = "none"

# Criterion names, in the order POLICY.md lists them.
NAME = "name"
DOB = "dob"
COUNTRY = "country"
CITY = "city"
ENTITY_TYPE = "entity_type"
CRITERIA = (NAME, DOB, COUNTRY, CITY, ENTITY_TYPE)


class Screened(object):
    """The customer as screened: what the alert says about them."""

    __slots__ = ("alert_id", "screened_at", "name", "entity_type", "dob", "country",
                 "city", "city_pieces", "link_kind", "link_value")

    def __init__(self, alert):
        self.alert_id = alert.get("alert_id", "")
        self.screened_at = dates.parse(alert.get("screened_at"))
        self.name = alert.get("customer_name", "")
        self.entity_type = alert.get("entity_type", "")
        self.dob = dates.parse(alert.get("dob"))
        self.country = countries.key(alert.get("country"))
        self.city = alert.get("city", "")
        self.city_pieces = _city_pieces(self.city)
        self.link_kind, self.link_value = _link(alert)

    @property
    def is_company(self):
        return self.entity_type == "Company"

    def __repr__(self):
        return "Screened(%s, %r)" % (self.alert_id, self.name)


def _link(alert):
    for kind in (ACCOUNT_REF, LOGIN_HANDLE, EMAIL):
        value = alert.get(kind, "")
        if value:
            return kind, value
    return NO_LINK, ""


def _city_pieces(city):
    """The screened city, which is not always one city.

    The data holds "Savannah, GA", "Cherry Hill, NJ / Wilmington, DE" and "United
    Kingdom" in this field, so it is read as a set of alternatives and a record matches
    when any of them appears in its city or address.  Pieces shorter than three letters
    are dropped: a two-letter state code would match inside unrelated words.
    """
    out = []
    for piece in norm.fold(city).replace("/", ",").split(","):
        piece = piece.strip()
        if len(piece) >= 3 and piece not in out:
            out.append(piece)
    return out


def customer_names(customer):
    """The names a customer record offers for comparison (POLICY principle 2: "a full,
    preferred or login name")."""
    return [
        customer.get("full_name", ""),
        customer.get("preferred_name", ""),
        customer.get("login_name", ""),
    ]


def customer_country_keys(customer):
    """The countries declared on one customer record: residence and nationality."""
    keys = []
    for field in ("residence_country", "nationality"):
        key = countries.key(customer.get(field, ""))
        if key and key not in keys:
            keys.append(key)
    return keys


def check_fit(screened, customer, variants=None):
    """How one customer record fits what was screened.

    Returns {criterion: True | False | None}, where None means the alert did not screen
    on it.  A criterion the alert is silent about can neither support nor rule out a
    record, so it stays None rather than becoming a match.
    """
    result = {}

    if screened.name:
        agree, _, _ = names.any_agree(
            [screened.name], customer_names(customer), screened.is_company, variants
        )
        result[NAME] = agree
    else:
        result[NAME] = None

    if screened.dob is not None:
        declared = dates.parse(customer.get("dob"))
        result[DOB] = dates.equal_where_both_known(screened.dob, declared) if declared else False
    else:
        result[DOB] = None

    if screened.country:
        result[COUNTRY] = screened.country in customer_country_keys(customer)
    else:
        result[COUNTRY] = None

    if screened.city_pieces:
        haystack = norm.fold(customer.get("city", "")) + " | " + norm.fold(customer.get("address", ""))
        result[CITY] = any(piece in haystack for piece in screened.city_pieces)
    else:
        result[CITY] = None

    if screened.entity_type:
        result[ENTITY_TYPE] = customer.get("entity_type", "") == screened.entity_type
    else:
        result[ENTITY_TYPE] = None

    return result


def fits(screened, customer, variants=None):
    """True when the record fits every detail the alert actually screened on."""
    checks = check_fit(screened, customer, variants)
    return all(value is not False for value in checks.values())


def fit_score(screened, customer, variants=None):
    """How many screened details the record matches.  Used only to break a tie between
    records that all fit, so the choice is stable."""
    checks = check_fit(screened, customer, variants)
    return sum(1 for value in checks.values() if value is True)


# ------------------------------------------------------------------ following the link


def linked_record_ids(data, screened):
    """The customer records the alert's link leads to, in a stable order.

    account_ref -> Accounts.account_id -> customer_id (52 accounts have two: joint
    holders).  login_handle -> Accounts.login_handle -> customer_id.  email ->
    Customers.email.
    """
    ids = []
    if screened.link_kind == ACCOUNT_REF:
        for account in data.accounts_by_id.get(screened.link_value, ()):
            if account.get("customer_id") and account["customer_id"] not in ids:
                ids.append(account["customer_id"])
    elif screened.link_kind == LOGIN_HANDLE:
        for account in data.accounts_by_login.get(screened.link_value, ()):
            if account.get("customer_id") and account["customer_id"] not in ids:
                ids.append(account["customer_id"])
    elif screened.link_kind == EMAIL:
        for customer in data.customers_by_email.get(screened.link_value.lower(), ()):
            if customer["record_id"] not in ids:
                ids.append(customer["record_id"])
    return sorted(id_ for id_ in ids if id_ in data.customer_by_id)


def choose_among(screened, customers, variants=None):
    """Pick between records the link leads to, using the screened details.

    POLICY principle 2: "A link can lead to more than one person; the screened details
    then pick between them."  With one record there is nothing to pick, so the link is
    taken as it stands.  With several, only those that fit survive; if several still fit,
    all of them are kept and the caller decides what that means.
    """
    if len(customers) <= 1:
        return list(customers)
    fitting = [c for c in customers if fits(screened, c, variants)]
    if not fitting:
        # Nothing fits: the link is still the best evidence we have, so keep them all
        # rather than inventing a choice.
        return list(customers)
    if len(fitting) == 1:
        return fitting
    best = max(fit_score(screened, c, variants) for c in fitting)
    return [c for c in fitting if fit_score(screened, c, variants) == best]


def seed_records(data, screened, variants=None):
    """The records the alert points at, before any merging into persons.

    Returns (records, how), where `how` says which path found them.
    """
    if screened.link_kind == NO_LINK:
        return [], NO_LINK
    ids = linked_record_ids(data, screened)
    customers = [data.customer_by_id[i] for i in ids]
    chosen = choose_among(screened, customers, variants)
    return chosen, screened.link_kind

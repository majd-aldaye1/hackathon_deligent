"""The rules engine: POLICY.md principles 6, 7 and 8, as pure functions.

    6. **Clear only on a contradiction.** A hit is a different entity only when a fact
       contradicts it ...
    7. **Confirm only on agreement.** ... Confirm a person when name and date of birth
       agree and nothing contradicts them; a company when name and country agree and
       nothing contradicts them.  Otherwise, `REVIEW`.

Each rule is a function of the two fact sheets and returns a `Finding` or None.  A Finding
names the facts it used, so `evidence` is their sources and nothing else — POLICY principle
9: "Cite what decided the hit, not everything you looked at."

Nothing here reads the data folder, and nothing here is random: the same fact sheets always
give the same verdict.
"""

from . import countries, dates, names
from .facts import sources
from .model import CODE_ORDER, REASON_CODES

MINIMUM_AGE = 16  # POLICY principle 6: "the customer was younger than 16"


def _sure(facts):
    """The facts a clear may rest on: everything a regular expression read.

    Decision log D28: a fact a language model recovered is `provisional`.  It still counts
    in the set a contradiction quantifies over — so it can stop a clear — but no clear may
    be carried by one, because a clear that is wrong costs 60 and a model is not
    reproducible the way a pattern is.
    """
    return [f for f in facts if not getattr(f, "provisional", False)]


class Finding(object):
    """One rule that fired, with the facts behind it."""

    __slots__ = ("code", "facts", "detail")

    def __init__(self, code, facts=(), **detail):
        self.code = code
        self.facts = tuple(f for f in facts if f is not None)
        self.detail = detail

    @property
    def decision(self):
        return REASON_CODES[self.code]

    def sources(self):
        return sources(*self.facts)

    def __repr__(self):
        return "Finding(%s, %r)" % (self.code, self.sources())


# ------------------------------------------------------------------ shared comparisons


def names_agree(customer, hit, variants=None):
    """Does any name of the customer agree with any name or alias of the hit?

    Returns (agree, customer_name_fact).  The customer's name fact is returned so the
    reason can cite where the name came from; the hit is never evidence.
    """
    if not customer.usable_for_name_decision():
        return False, None
    for fact in customer.name_facts():
        for hit_name in hit.names:
            if names.agree(fact.value, hit_name, hit.is_company or customer.is_company, variants):
                return True, fact
    return False, None


def dobs_agree(customer, hit):
    """POLICY principle 7, with the facts that agreed."""
    for customer_fact in customer.dob_facts():
        for hit_fact in hit.dobs:
            if dates.agrees(customer_fact.value, hit_fact.value):
                return True, customer_fact, hit_fact
    return False, None, None


def shared_countries(customer, hit):
    """The countries both sides are tied to, with the customer facts that supplied them."""
    hit_keys = set(hit.countries)
    matching = [f for f in customer.country_facts() if f.value in hit_keys]
    return matching


def countries_disjoint(customer, hit):
    """"every country tied to the customer ... differs from every country tied to the hit".

    False whenever either side has no country at all: an unknown country is unknown, not a
    difference.
    """
    customer_keys = set(customer.country_keys())
    hit_keys = set(hit.countries)
    if not customer_keys or not hit_keys:
        return False
    return not (customer_keys & hit_keys)


# ------------------------------------------------------------------------ contradictions


def entity_type_mismatch(customer, hit, screened, variants=None):
    """"**Type:** one is a person and the other a company." """
    if not customer.entity_type or not hit.entity_type:
        return None
    if customer.entity_type == hit.entity_type:
        return None
    return Finding(
        "ENTITY_TYPE_MISMATCH",
        facts=_record_facts(customer),
        customer_type=customer.entity_type,
        hit_type=hit.entity_type,
    )


def deceased(customer, hit, screened, variants=None):
    """"the profile gives a date of death before the customer was screened" """
    if hit.death is None or screened.screened_at is None:
        return None
    if not dates.before(hit.death.value, screened.screened_at):
        return None
    return Finding(
        "DECEASED",
        facts=_record_facts(customer),
        death=hit.death.value,
        screened_at=screened.screened_at,
    )


def temporal_impossibility(customer, hit, screened, variants=None):
    """"the customer was younger than 16 at the earliest dated report, or a company was
    incorporated after it" """
    if hit.earliest_report is None:
        return None
    report = hit.earliest_report.value
    customer_dobs = customer.dob_facts()
    if not customer_dobs:
        return None
    if not _sure(customer_dobs):
        return None  # only a model-read date of birth: it may block, not clear
    if customer.is_company:
        # A company cannot act before it exists.
        for fact in customer_dobs:
            if not _strictly_after(fact.value, report):
                return None
        chosen = _sure(customer_dobs)[0]
        return Finding(
            "TEMPORAL_IMPOSSIBILITY",
            facts=(chosen,),
            incorporated=chosen.value,
            incorporated_sources=chosen.source_ids,
            report=report,
            is_company=True,
        )
    # Every date of birth the customer has must make them too young.
    worst = None
    for fact in customer_dobs:
        age = dates.max_age_at(fact.value, report)
        if age is None or age >= MINIMUM_AGE:
            return None
        if worst is None or age > worst[0]:
            worst = (age, fact)
    if worst is None:
        return None
    age, fact = worst
    if getattr(fact, "provisional", False):
        sure = [f for f in _sure(customer_dobs) if dates.max_age_at(f.value, report) is not None]
        if not sure:
            return None
        fact = max(sure, key=lambda f: dates.max_age_at(f.value, report))
        age = dates.max_age_at(fact.value, report)
    return Finding(
        "TEMPORAL_IMPOSSIBILITY",
        facts=(fact,),
        born=fact.value,
        born_sources=fact.source_ids,
        age=age,
        report=report,
        is_company=False,
    )


def _strictly_after(incorporation, report):
    """True when the company certainly did not exist at the report."""
    if incorporation is None or report is None:
        return False
    if incorporation.year != report.year:
        return incorporation.year > report.year
    # Same year: only a known month can settle it, and only if it is later.
    if incorporation.month is None or report.month is None:
        return False
    if incorporation.month != report.month:
        return incorporation.month > report.month
    if incorporation.day is None or report.day is None:
        return False
    return incorporation.day > report.day


def dob_mismatch(customer, hit, screened, variants=None):
    """"every birth date the hit gives is contradicted ... One agreeing date is enough to
    prevent this." """
    hit_dobs = [f.value for f in hit.dobs]
    customer_dobs = customer.dob_facts()
    if not hit_dobs or not customer_dobs:
        return None
    if not _sure(customer_dobs) or not _sure(hit.dobs):
        # The clear would rest on a model's reading of free text on one side or the other.
        return None
    if getattr(customer, "verified_dob_may_be_missing", False):
        # An approved identity check exists but we could not read a date of birth out of
        # it.  "Verified beats declared", so a declared date must not clear the hit when
        # the verified one it would be overruled by is simply unread.
        return None
    for fact in customer_dobs:
        if not dates.all_contradict(fact.value, hit_dobs):
            return None
    chosen = _sure(customer_dobs)[0]
    return Finding(
        "DOB_MISMATCH",
        facts=(chosen,) + tuple(hit.dobs),
        customer_dob=chosen.value,
        customer_dob_sources=chosen.source_ids,
        hit_description=hit.dob_description(),
    )


def location_mismatch(customer, hit, screened, variants=None):
    """"Every country tied to the customer differs from every country tied to the hit." """
    if not countries_disjoint(customer, hit):
        return None
    if getattr(customer, "countries_may_be_incomplete", False):
        # A note says where the customer lived and we could not place it, so "every
        # country tied to the customer" is not a set we actually have.
        return None
    if not _sure(customer.country_facts()):
        return None  # every country we have is a model's reading
    if getattr(hit, "dob_unreadable", False) and names_agree(customer, hit, variants)[0]:
        # POLICY's location rule has an exception for a hit "whose name and date of birth
        # agree".  The hit's profile talks about a birth we could not read, so whether the
        # exception applies is unknown — and an unknown is not a difference.
        return None
    return Finding(
        "LOCATION_MISMATCH",
        facts=tuple(customer.country_facts()),
        customer_countries=customer.country_keys(),
        hit_countries=list(hit.countries),
    )


def name_mismatch_verified(customer, hit, screened, variants=None):
    """"the customer's verified legal name agrees with none of the hit's names or aliases
    ..., even if the name on their record does." """
    if not customer.verified_name_usable():
        return None
    verified = customer.verified_name
    if getattr(verified, "provisional", False):
        return None  # a model-read legal name may block a clear, not carry one
    for hit_name in hit.names:
        if names.agree(verified.value, hit_name, hit.is_company or customer.is_company, variants):
            return None
    return Finding(
        "NAME_MISMATCH_VERIFIED",
        facts=(verified,),
        verified_name=verified.value,
        verified_sources=verified.source_ids,
        hit_name=hit.names[0] if hit.names else "",
    )


CONTRADICTIONS = (
    entity_type_mismatch,
    deceased,
    temporal_impossibility,
    dob_mismatch,
    location_mismatch,
    name_mismatch_verified,
)


# ---------------------------------------------------------------------------- agreement


def agreement(customer, hit, screened, variants=None):
    """POLICY principle 7.  Returns a list of findings, which may be empty."""
    name_ok, name_fact = names_agree(customer, hit, variants)
    if not name_ok:
        return []
    matching = shared_countries(customer, hit)
    if customer.is_company or hit.is_company:
        # "a company when name and country agree"
        if not matching:
            return []
        return [
            Finding(
                "NAME_LOCATION_MATCH",
                facts=tuple(matching),
                countries=[f.value for f in matching],
                hit_name=hit.names[0] if hit.names else "",
            )
        ]
    dob_ok, customer_dob, hit_dob = dobs_agree(customer, hit)
    if not dob_ok:
        return []
    found = []
    if matching:
        found.append(
            Finding(
                "NAME_DOB_LOCATION_MATCH",
                facts=(customer_dob, hit_dob) + tuple(matching),
                customer_dob=customer_dob.value,
                customer_dob_sources=customer_dob.source_ids,
                hit_description=hit.dob_description(),
                hit_dob_list=hit.dob_list(),
                countries=[f.value for f in matching],
                hit_name=hit.names[0] if hit.names else "",
            )
        )
    found.append(
        Finding(
            "NAME_DOB_MATCH",
            facts=(customer_dob, hit_dob) + tuple(matching),
            customer_dob=customer_dob.value,
            customer_dob_sources=customer_dob.source_ids,
            hit_description=hit.dob_description(),
            hit_dob_list=hit.dob_list(),
            countries=[f.value for f in matching],
            hit_name=hit.names[0] if hit.names else "",
        )
    )
    return found


# ------------------------------------------------------------------------- the verdict


class Verdict(object):
    """What one person's facts say about one hit."""

    __slots__ = ("decision", "code", "findings", "review_detail", "context")

    def __init__(self, decision, code, findings=(), review_detail=None, context=None):
        self.decision = decision
        self.code = code
        self.findings = list(findings)
        self.review_detail = review_detail or {}
        # What the other comparisons said, so a reason can be honest about what is missing.
        self.context = context or {}

    def sources(self):
        out = set()
        for finding in self.findings:
            out |= set(finding.sources())
        return sorted(out)

    def codes(self):
        return [f.code for f in self.findings]

    def __repr__(self):
        return "Verdict(%s, %s, %r)" % (self.decision, self.code, self.codes())


def _order(findings):
    return sorted(findings, key=lambda f: CODE_ORDER.index(f.code))


def _record_facts(customer):
    """The person's own records as facts, for a rule whose customer side is the record."""
    from .facts import Fact

    return tuple(Fact(record_id, (record_id,)) for record_id in customer.record_ids)


def evaluate(customer, hit, screened, variants=None):
    """Decide one hit against one person.  Pure: no I/O, no randomness."""
    found = []
    for rule in CONTRADICTIONS:
        finding = rule(customer, hit, screened, variants)
        if finding is not None:
            found.append(finding)
    found = _order(found)

    name_ok, name_fact = names_agree(customer, hit, variants)
    dob_ok, customer_dob, hit_dob = dobs_agree(customer, hit)
    context = _context(customer, hit, name_ok, dob_ok)

    # POLICY principle 6, Location: "A country difference does not clear a hit whose name
    # and date of birth agree: that hit is `REVIEW`."
    if name_ok and dob_ok:
        location_only = [f for f in found if f.code == "LOCATION_MISMATCH"]
        if location_only and len(found) == len(location_only):
            matching = shared_countries(customer, hit)
            return Verdict(
                "REVIEW",
                "INSUFFICIENT_DATA",
                findings=[_as_finding(customer_dob, hit_dob, name_fact)],
                review_detail={
                    "reason": "location_exception",
                    "customer_dob": customer_dob.value,
                    "customer_dob_sources": customer_dob.source_ids,
                    "hit_description": hit.dob_description(),
                    "hit_dob_list": hit.dob_list(),
                    "hit_name": hit.names[0] if hit.names else "",
                    "customer_countries": customer.country_keys(),
                    "hit_countries": list(hit.countries),
                    "countries": [f.value for f in matching],
                },
            )
        found = [f for f in found if f.code != "LOCATION_MISMATCH"] or found

    if found:
        return Verdict(found[0].decision, found[0].code, findings=found, context=context)

    confirmations = _order(agreement(customer, hit, screened, variants))
    if confirmations:
        return Verdict(
            confirmations[0].decision, confirmations[0].code,
            findings=confirmations, context=context,
        )

    return Verdict(
        "REVIEW",
        "INSUFFICIENT_DATA",
        findings=_review_findings(customer, hit, name_ok, name_fact),
        review_detail=_review_detail(customer, hit, name_ok, name_fact, dob_ok),
        context=context,
    )


def dobs_contradict(customer, hit):
    """Every date the customer has against every date the hit gives."""
    customer_dobs = customer.dob_facts()
    hit_dobs = [f.value for f in hit.dobs]
    if not customer_dobs or not hit_dobs:
        return False
    return all(dates.all_contradict(f.value, hit_dobs) for f in customer_dobs)


def _context(customer, hit, name_ok, dob_ok):
    """The state of the comparisons a contradiction did not rest on."""
    if not hit.dobs:
        gap = "hit_has_none"
    elif not customer.dob_facts():
        gap = "customer_has_none"
    elif dob_ok:
        gap = None
    elif dobs_contradict(customer, hit):
        gap = "contradict"
    else:
        gap = "neither"
    return {
        "name_agrees": name_ok,
        "name_usable": customer.usable_for_name_decision(),
        "hit_name": hit.names[0] if hit.names else "",
        "dob_agrees": dob_ok,
        "dob_gap": gap,
        "shared_countries": [f.value for f in shared_countries(customer, hit)],
    }


def _as_finding(customer_dob, hit_dob, name_fact):
    return Finding("INSUFFICIENT_DATA", facts=(customer_dob, hit_dob, name_fact))


def _review_findings(customer, hit, name_ok, name_fact):
    """What a review cites: whatever actually lined up, and nothing else."""
    facts = []
    matching = shared_countries(customer, hit)
    facts.extend(matching)
    if name_ok and name_fact is not None and not matching:
        facts.append(name_fact)
    if not facts:
        facts.extend(_record_facts(customer)[:1])
    return [Finding("INSUFFICIENT_DATA", facts=facts)]


def _review_detail(customer, hit, name_ok, name_fact, dob_ok):
    matching = shared_countries(customer, hit)
    detail = {
        "reason": "insufficient",
        "name_agrees": name_ok,
        "hit_name": hit.names[0] if hit.names else "",
        "countries": [f.value for f in matching],
        "customer_countries": customer.country_keys(),
        "hit_countries": list(hit.countries),
        "name_usable": customer.usable_for_name_decision(),
    }
    if not hit.dobs:
        detail["dob_gap"] = "hit_has_none"
    elif not customer.dob_facts():
        detail["dob_gap"] = "customer_has_none"
    elif not dob_ok:
        detail["dob_gap"] = "neither"
    else:
        detail["dob_gap"] = None
    if customer.dob_facts():
        first = customer.dob_facts()[0]
        detail["customer_dob"] = first.value
        detail["customer_dob_sources"] = first.source_ids
    if detail["dob_gap"] is None and not dob_ok:
        detail["dob_gap"] = "neither"
    if dobs_contradict(customer, hit):
        detail["dob_gap"] = "contradict"
    # Why a disagreement did not clear the hit: the verified date could not be read.
    detail["verified_dob_unreadable"] = bool(
        getattr(customer, "verified_dob_may_be_missing", False)
    )
    detail["hit_description"] = hit.dob_description()
    detail["hit_dob_list"] = hit.dob_list()
    return detail

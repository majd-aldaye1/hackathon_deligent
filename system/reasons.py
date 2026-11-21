"""The reason text, written from the structured facts.

Every sentence is a template filled with this hit's own values and the record ids the fact
came from, so the text can never drift from the decision it explains and costs nothing to
produce.  The wording follows the reference reasons in the practice labels.
"""

from . import countries

PERSON = "person"
COMPANY = "company"

_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


def _join(items, word="or"):
    items = [str(i) for i in items if str(i)]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return "%s %s %s" % (", ".join(items[:-1]), word, items[-1])


def _cite(source_ids):
    return " (%s)" % ", ".join(source_ids) if source_ids else ""


def _kind(entity_type):
    return COMPANY if entity_type == "Company" else PERSON


# --------------------------------------------------------------------------- sentences


def _entity_type_mismatch(detail):
    return "The customer is a %s but the hit is a %s." % (
        _kind(detail.get("customer_type")),
        _kind(detail.get("hit_type")),
    )


def _deceased(detail):
    return (
        "The hit's profile gives a date of death of %s, before the customer was screened on %s."
        % (detail["death"].iso(), detail["screened_at"].iso())
    )


def _temporal_impossibility(detail):
    if detail.get("is_company"):
        return (
            "The customer was incorporated on %s%s, after the hit's profile reports activity "
            "on %s." % (
                detail["incorporated"].iso(),
                _cite(detail.get("incorporated_sources", ())),
                detail["report"].iso(),
            )
        )
    born = detail["born"]
    where = "in %d" % born.year if born.month is None else "on %s" % born.iso()
    return (
        "The customer was born %s%s, so they were at most %d when the hit's profile reports "
        "activity on %s." % (
            where, _cite(detail.get("born_sources", ())), detail["age"], detail["report"].iso()
        )
    )


def _dob_mismatch(detail):
    return "The customer's date of birth is %s%s but the hit's %s." % (
        detail["customer_dob"].iso(),
        _cite(detail.get("customer_dob_sources", ())),
        detail["hit_description"],
    )


def _location_mismatch(detail):
    return "The customer is linked only to %s but the hit is linked only to %s." % (
        countries.display(detail["customer_countries"]),
        countries.display(detail["hit_countries"]),
    )


def _name_mismatch_verified(detail):
    return "The customer's verified name is %s%s, which does not match the hit's name %s." % (
        detail["verified_name"],
        _cite(detail.get("verified_sources", ())),
        detail["hit_name"],
    )


def _dob_agrees(detail):
    return "The customer's date of birth %s%s agrees with the hit's %s." % (
        detail["customer_dob"].iso(),
        _cite(detail.get("customer_dob_sources", ())),
        detail.get("hit_dob_list") or "listed date",
    )


def _country_agrees(detail):
    return "Both the customer and the hit are linked to %s." % countries.display(
        detail.get("countries", ())
    )


def _name_agrees(detail):
    return "The customer's name agrees with the hit's name %s." % detail.get("hit_name", "")


SENTENCES = {
    "ENTITY_TYPE_MISMATCH": _entity_type_mismatch,
    "DECEASED": _deceased,
    "TEMPORAL_IMPOSSIBILITY": _temporal_impossibility,
    "DOB_MISMATCH": _dob_mismatch,
    "LOCATION_MISMATCH": _location_mismatch,
    "NAME_MISMATCH_VERIFIED": _name_mismatch_verified,
}


def _agreement_sentences(code, detail):
    out = []
    if code in ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"):
        out.append(_dob_agrees(detail))
    if detail.get("countries"):
        out.append(_country_agrees(detail))
    out.append(_name_agrees(detail))
    return out


# ------------------------------------------------------------------------- the reasons


_DOB_STATE = {
    "hit_has_none": "the hit gives no date of birth to compare",
    "customer_has_none": "the customer's records give no date of birth to compare",
    "neither": "their dates of birth neither agree nor contradict each other",
    None: "their dates of birth agree",
}


def _closing(context, settled_by, code=None):
    """What else was compared, and what it did not settle.

    The brief asks a reason to be honest about what is missing, and a clear deserves to say
    which comparisons did *not* carry it.
    """
    if not context:
        return ""
    if code == "NAME_MISMATCH_VERIFIED" and context.get("name_agrees"):
        # POLICY principle 6: the verified legal name clears the hit "even if the name on
        # their record does" agree.  Saying so plainly avoids reading as a contradiction.
        return (
            "The name on the customer's own record does agree with the hit's, but the "
            "verified legal name outranks it."
        )
    if context.get("name_agrees"):
        name = "the customer's name agrees with the hit's name %s" % context.get("hit_name", "")
    elif not context.get("name_usable"):
        name = "the customer's records give fewer than two real name parts to compare"
    else:
        name = "the customer's name does not agree with the hit's name %s" % context.get(
            "hit_name", ""
        )
    dob = _DOB_STATE.get(context.get("dob_gap"), "their dates of birth agree")
    return "Otherwise %s and %s, so %s is what settles it." % (name, dob, settled_by)


_SETTLED_BY = {
    "ENTITY_TYPE_MISMATCH": "the difference in entity type",
    "DECEASED": "the date of death",
    "TEMPORAL_IMPOSSIBILITY": "the timing",
    "DOB_MISMATCH": "the date of birth",
    "LOCATION_MISMATCH": "the country difference",
    "NAME_MISMATCH_VERIFIED": "the verified legal name",
}


def for_contradiction(findings, hit, context=None):
    """2–4 sentences: one per rule that fired, in POLICY's own order, then what is missing."""
    out = []
    for finding in findings[:3]:
        writer = SENTENCES.get(finding.code)
        if writer is not None:
            out.append(writer(finding.detail))
    if not out:
        out.append("The customer's records contradict the hit.")
    if len(out) == 1 and findings:
        settled_by = _SETTLED_BY.get(findings[0].code, "that contradiction")
        closing = _closing(context, settled_by, findings[0].code)
        if closing:
            out.append(closing)
    return " ".join(out)


def for_agreement(code, detail):
    return " ".join(_agreement_sentences(code, detail))


_DOB_GAP = {
    "hit_has_none": "the date of birth cannot be compared with it",
    "customer_has_none": "the customer's records give no date of birth to compare",
    "neither": "the dates of birth neither agree nor contradict each other",
}


def for_review(detail):
    """A review has to say what lined up, what did not, and what is missing."""
    out = []
    if detail.get("reason") == "location_exception":
        out.append(_dob_agrees(detail))
        out.append(_name_agrees(detail))
        out.append(
            "The customer is linked only to %s and the hit only to %s, but a country "
            "difference does not clear a hit whose name and date of birth agree, so the hit "
            "is left for a person." % (
                countries.display(detail.get("customer_countries", ())),
                countries.display(detail.get("hit_countries", ())),
            )
        )
        return " ".join(out)

    if detail.get("countries"):
        out.append(_country_agrees(detail))
    if detail.get("name_agrees"):
        out.append(_name_agrees(detail))
    elif not detail.get("name_usable"):
        out.append(
            "The customer's records give fewer than two real name parts, so the hit can be "
            "neither confirmed nor cleared on name."
        )
    else:
        out.append(
            "The customer's name does not agree with the hit's name %s, but no verified legal "
            "name settles it." % detail.get("hit_name", "")
        )
    gap = _DOB_GAP.get(detail.get("dob_gap"))
    if gap:
        out.append(
            "Nothing in the customer's records contradicts the hit, and %s, so the hit can be "
            "neither cleared nor confirmed." % gap
        )
    else:
        out.append(
            "Nothing in the customer's records contradicts the hit and not enough agrees to "
            "confirm it, so the hit can be neither cleared nor confirmed."
        )
    return " ".join(out)


def for_no_customer(screened, hit):
    """Nothing to compare the hit with."""
    detail = []
    if screened.dob is not None:
        detail.append("date of birth %s" % screened.dob.iso())
    if screened.country:
        detail.append("country %s" % screened.country)
    if screened.city:
        detail.append("city %s" % screened.city)
    tail = (", " + _join(detail, "and")) if detail else ""
    return (
        "No customer record in the system of record fits the screened name %s%s, so there is "
        "no customer to compare the hit %s with. Nothing contradicts the hit and nothing "
        "confirms it, so it is left for a person."
        % (screened.name or "that was screened", tail, hit.names[0] if hit.names else hit.hit_id)
    )


def for_ambiguous(verdicts, hit, persons=()):
    """More than one person fits and they disagree."""
    count = _WORDS.get(len(verdicts), str(len(verdicts)))
    groups = [", ".join(person) for person in persons]
    who = (" (%s)" % _join(groups, "and")) if groups else ""
    # Distinct answers only: six people giving three the same verdict should read as two
    # answers, not six.
    pairs = []
    for verdict in verdicts:
        pair = "%s on %s" % (verdict.decision, verdict.code)
        if pair not in pairs:
            pairs.append(pair)
    answers = _join(sorted(pairs), "and")
    return (
        "%s people in the system of record fit the alert%s. They lead to different answers: "
        "%s. The records as they stand cannot settle which of them the hit is, so it is left "
        "for a person." % (count, who, answers)
    )


def with_ambiguity_note(text, count):
    """Add the honest caveat when several people fit but agree.

    POLICY principle 3 says to give the shared answer, and `customer_record_id` is
    `AMBIGUOUS` either way, so the reader should be told why.
    """
    word = _WORDS.get(count, str(count))
    both = "both" if count == 2 else "all of them"
    return "%s %s people in the system of record fit the alert, and %s lead to this answer." % (
        text, word, both
    )

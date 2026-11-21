"""The customer's full picture, with every fact's source.

POLICY.md principle 2: the customer's "full picture is spread over the bank's systems".
Principle 3: "All their facts count."  Principle 4: "The most recent *approved* identity
check of the person is the most reliable source for their legal name, date of birth and
document country, whether it is recorded by the KYC provider or only in a note by the
onboarding team."  Principle 6: the customer's countries are "residence and nationality on
all their records, the approved identity document, and places the notes say they lived".

Everything here is read from the resolved person's own records only — never another
customer's.
"""

from . import countries, dates, kyc, names, notes_regex
from .facts import Fact, merge


class VerifiedIdentity(object):
    """One approved identity check, from the provider or from an onboarding note."""

    __slots__ = ("source_id", "checked_at", "name", "dob", "document_country", "quote",
                 "provisional")

    def __init__(self, source_id, checked_at, name=None, dob=None, document_country=None,
                 quote=None, provisional=False):
        self.source_id = source_id
        self.checked_at = checked_at
        self.name = name or None
        self.dob = dob
        self.document_country = document_country
        self.quote = quote
        # True when a language model, not a pattern, read this check out of a note.
        self.provisional = bool(provisional)

    def recency(self):
        return (self.checked_at.key() if self.checked_at else (0, 0, 0), self.source_id)

    def __repr__(self):
        return "VerifiedIdentity(%s, %r, %s, %s)" % (
            self.source_id, self.name, self.dob, self.document_country
        )


class CustomerFacts(object):
    """What the bank knows about one person."""

    def __init__(self, record_ids, entity_type, declared_names, declared_dobs,
                 country_facts, approved, note_ids=(), unreadable_places=(),
                 unreadable_checks=()):
        self.record_ids = tuple(record_ids)
        self.entity_type = entity_type
        self.declared_names = list(declared_names)
        self.declared_dobs = list(declared_dobs)
        self.countries = list(country_facts)
        # every approved check of the person, most recent first
        self.approved = list(approved)
        self.note_ids = tuple(note_ids)
        # Sources that were there but could not be read.  They do not add facts; they stop
        # the absence of a fact from being mistaken for a contradiction.
        self.unreadable_places = tuple(unreadable_places)
        self.unreadable_checks = tuple(unreadable_checks)

    # -- identity

    @property
    def is_company(self):
        return self.entity_type == "Company"

    @property
    def verified(self):
        return self.approved[0] if self.approved else None

    def _first_approved_with(self, attribute):
        """The most recent approved check that states this field.

        POLICY names one check as the source, but 1 850 provider checks carry no date of
        birth and a handful of note-recorded ones carry no country, so a field the newest
        check is silent about falls back to the newest approved check that states it.  The
        fact is still a verified one.
        """
        for check in self.approved:
            if getattr(check, attribute, None):
                return check
        return None

    @property
    def verified_name(self):
        """The verified legal name, which "outranks the name on the customer record"."""
        check = self._first_approved_with("name")
        if not check:
            return None
        return Fact(check.name, (check.source_id,), check.provisional)

    @property
    def verified_dob(self):
        check = self._first_approved_with("dob")
        if not check:
            return None
        return Fact(check.dob, (check.source_id,), check.provisional)

    @property
    def verified_country(self):
        check = self._first_approved_with("document_country")
        if not check:
            return None
        return Fact(check.document_country, (check.source_id,), check.provisional)

    # -- what the rules compare

    def name_facts(self):
        """Every name of the person, the verified legal name first."""
        out = []
        verified = self.verified_name
        if verified is not None:
            out.append(verified)
        out.extend(self.declared_names)
        return _dedupe_names(out)

    def names(self):
        return [f.value for f in self.name_facts()]

    def dob_facts(self):
        """The dates of birth to compare against the hit.

        "Verified beats declared": with a verified date of birth that is the only one
        considered, so a stale record cannot contradict the hit on its own.  Without one,
        every date the person's records declare counts, and a contradiction needs all of
        them (decision log D7).
        """
        verified = self.verified_dob
        if verified is not None:
            return [verified]
        return merge(self.declared_dobs)

    @property
    def countries_may_be_incomplete(self):
        """A note says where they lived and we could not tell where.

        POLICY principle 6 counts "places the notes say they lived" among the customer's
        countries, so one unread note means the set is not the whole set — and
        `LOCATION_MISMATCH` needs *every* customer country to differ.
        """
        return bool(self.unreadable_places)

    @property
    def verified_dob_may_be_missing(self):
        """There is an identity check for this person, but no verified date of birth.

        Either an approved check gave none, or a note recording one could not be read at
        all.  "Verified beats declared", so falling back to a declared date that the
        unread verified one would have overruled must not clear a hit — that is exactly
        how a customer whose record is out of date gets wrongly cleared.
        """
        if self.verified_dob is not None:
            return False
        return bool(self.approved) or bool(self.unreadable_checks)

    def country_facts(self):
        return merge(self.countries)

    def country_keys(self):
        return [f.value for f in self.country_facts()]

    def usable_for_name_decision(self):
        return names.usable_for_name_decision(self.names(), self.is_company)

    def verified_name_usable(self):
        """A verified legal name can only clear a hit if it has two real parts
        (principle 8), unless the customer is a company."""
        verified = self.verified_name
        if verified is None:
            return False
        return names.usable_for_name_decision([verified.value], self.is_company)

    def __repr__(self):
        return "CustomerFacts(%s, %s)" % (", ".join(self.record_ids), self.entity_type)


def _dedupe_names(facts):
    """Keep the first fact for each distinct name, preserving order."""
    out = []
    seen = set()
    for fact in facts:
        if not fact or not fact.value:
            continue
        key = fact.value.strip().lower()
        if key in seen:
            index = [i for i, f in enumerate(out) if f.value.strip().lower() == key][0]
            out[index] = out[index].with_sources(fact.source_ids)
            continue
        seen.add(key)
        out.append(fact)
    return out


def gather(data, record_ids, variants=None, extractor=None):
    """Build the fact sheet for one person, given every record they own.

    `extractor` is the optional language-model fallback.  It is asked only about a note
    the patterns could not read, and whatever it returns is marked provisional.
    """
    record_ids = tuple(sorted(record_ids))
    records = [data.customer_by_id[r] for r in record_ids if r in data.customer_by_id]
    if not records:
        return CustomerFacts(record_ids, "", [], [], [], [])

    entity_type = records[0].get("entity_type", "")
    for record in records:
        if record.get("entity_type"):
            entity_type = record["entity_type"]
            break

    declared_names, declared_dobs, country_facts = [], [], []
    for record in records:
        record_id = record["record_id"]
        for field in ("full_name", "preferred_name", "login_name"):
            value = record.get(field, "")
            if value:
                declared_names.append(Fact(value, (record_id,)))
        declared = dates.parse(record.get("dob"))
        if declared is not None:
            declared_dobs.append(Fact(declared, (record_id,)))
        for field in ("residence_country", "nationality"):
            key = countries.key(record.get(field, ""))
            if key:
                country_facts.append(Fact(key, (record_id,)))

    # Approved identity checks: the KYC provider's, and any written up in a note.
    approved = []
    for record_id in record_ids:
        for check in kyc.approved_checks(data, record_id):
            approved.append(
                VerifiedIdentity(
                    source_id=check.get("check_id", ""),
                    checked_at=dates.parse(check.get("checked_at")),
                    name=check.get("verified_name", ""),
                    dob=dates.parse(check.get("verified_dob")),
                    document_country=countries.key(check.get("document_country", "")),
                )
            )

    note_ids, unreadable_places, unreadable_checks = [], [], []
    for note in _person_notes(data, records):
        note_ids.append(note["note_id"])
        if note.get("channel", "") == notes_regex.KYC_CHANNEL:
            parsed = notes_regex.parse_kyc_note(note)
            if parsed is not None and parsed.is_approved:
                approved.append(
                    VerifiedIdentity(
                        source_id=parsed.note_id,
                        checked_at=parsed.checked_at,
                        name=parsed.verified_name,
                        dob=parsed.verified_dob,
                        document_country=parsed.document_country,
                        quote=parsed.quotes,
                    )
                )
            unread = parsed is None or (parsed.is_approved and not parsed.verified_dob)
            if unread and extractor is not None:
                recovered = _ask_about_check(extractor, note)
                if recovered is not None:
                    approved.append(recovered)
                    unread = not recovered.dob
            if unread:
                unreadable_checks.append(note["note_id"])
            continue
        found = notes_regex.places_lived(note)
        for key in found:
            country_facts.append(Fact(key, (note["note_id"],)))
        if not found and notes_regex.looks_like_residence(note):
            recovered = _ask_about_places(extractor, note)
            for key in recovered:
                country_facts.append(Fact(key, (note["note_id"],), True))
            if not recovered:
                unreadable_places.append(note["note_id"])

    approved.sort(key=lambda c: c.recency(), reverse=True)

    # The approved document's country counts among the customer's countries.
    for check in approved:
        if check.document_country:
            country_facts.append(Fact(check.document_country, (check.source_id,)))

    return CustomerFacts(
        record_ids=record_ids,
        entity_type=entity_type,
        declared_names=_dedupe_names(declared_names),
        declared_dobs=declared_dobs,
        country_facts=country_facts,
        approved=approved,
        note_ids=sorted(note_ids),
        unreadable_places=sorted(unreadable_places),
        unreadable_checks=sorted(unreadable_checks),
    )


def _ask_about_check(extractor, note):
    """Let the model read an identity check the patterns could not."""
    try:
        found = extractor.note_check(note.get("text", ""))
    except Exception:
        return None
    if found is None or not found.is_approved:
        return None
    return VerifiedIdentity(
        source_id=note["note_id"],
        checked_at=dates.parse(note.get("created_at")),
        name=found.name,
        dob=found.dob,
        document_country=found.country,
        quote=found.quotes,
        provisional=True,
    )


def _ask_about_places(extractor, note):
    """Let the model read a residence statement the patterns could not."""
    if extractor is None:
        return []
    try:
        return [place.country for place in extractor.note_places(note.get("text", ""))]
    except Exception:
        return []


def _person_notes(data, records):
    """The person's own support notes, found through the emails on their records."""
    out, seen = [], set()
    for record in records:
        email = record.get("email", "").lower()
        for note in data.notes_by_email.get(email, ()):
            if note["note_id"] not in seen:
                seen.add(note["note_id"])
                out.append(note)
    return sorted(out, key=lambda n: n["note_id"])

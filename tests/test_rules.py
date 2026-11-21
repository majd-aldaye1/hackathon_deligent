"""Step 7: the rules engine, built from fact sheets rather than from the data folder.

POLICY.md principle 6 lists the five contradictions; principle 7 the two confirmations.
Each case below is a fabricated pair of fact sheets, so a rule is tested on its own terms
and not through whatever the development set happens to contain.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import dates, rules  # noqa: E402
from system.customer_facts import CustomerFacts, VerifiedIdentity  # noqa: E402
from system.facts import Fact  # noqa: E402
from system.hit_facts import FROM_FIELD, FROM_NOTES, HitFacts  # noqa: E402


def customer(record_ids=("CUS-1",), entity_type="Individual", names=("Ada Lovelace",),
             declared_dob=None, countries=(), verified_name=None, verified_dob=None,
             verified_country=None, verified_source="KYC-1"):
    approved = []
    if verified_name or verified_dob or verified_country:
        approved.append(
            VerifiedIdentity(
                source_id=verified_source,
                checked_at=dates.parse("2024-01-01"),
                name=verified_name,
                dob=dates.parse(verified_dob) if verified_dob else None,
                document_country=verified_country,
            )
        )
    return CustomerFacts(
        record_ids=record_ids,
        entity_type=entity_type,
        declared_names=[Fact(n, (record_ids[0],)) for n in names],
        declared_dobs=[Fact(dates.parse(declared_dob), (record_ids[0],))] if declared_dob else [],
        country_facts=[Fact(c, (record_ids[0],)) for c in countries],
        approved=approved,
    )


def hit(names=("Lovelace, Ada",), entity_type="Individual", dobs=(),
        dob_origin=FROM_FIELD, countries=(), death=None, report=None, result_ids=()):
    parsed = [Fact(dates.parse(d), result_ids) for d in dobs]
    return HitFacts(
        hit_id="H-1",
        alert_id="A-1",
        entity_type=entity_type,
        names_=list(names),
        country_keys_=list(countries),
        dobs=parsed,
        dob_origin=dob_origin if parsed else None,
        death=Fact(dates.parse(death)) if death else None,
        earliest_report=Fact(dates.parse(report)) if report else None,
        listing_phrase="a politically exposed person",
        result_ids=result_ids,
    )


def screened(screened_at="2026-11-06"):
    class _S(object):
        pass

    s = _S()
    s.alert_id = "A-1"
    s.screened_at = dates.parse(screened_at)
    s.name = "Ada Lovelace"
    s.entity_type = "Individual"
    s.dob = None
    s.country = None
    s.city = ""
    return s


def verdict(cust, h, scr=None):
    return rules.evaluate(cust, h, scr or screened())


class TestEntityTypeMismatch(unittest.TestCase):
    def test_a_person_against_a_company(self):
        result = verdict(customer(entity_type="Individual"), hit(entity_type="Company"))
        self.assertEqual(result.decision, "DIFFERENT_ENTITY")
        self.assertEqual(result.code, "ENTITY_TYPE_MISMATCH")

    def test_the_same_type_does_not_fire(self):
        self.assertIsNone(
            rules.entity_type_mismatch(customer(), hit(), screened())
        )

    def test_an_unknown_type_is_not_a_mismatch(self):
        self.assertIsNone(
            rules.entity_type_mismatch(customer(entity_type=""), hit(), screened())
        )


class TestDeceased(unittest.TestCase):
    def test_a_death_before_the_screening(self):
        result = verdict(customer(), hit(death="2021-08-02"), screened("2026-11-06"))
        self.assertEqual(result.code, "DECEASED")

    def test_a_partial_death_date_still_clears_when_the_year_is_earlier(self):
        result = verdict(customer(), hit(death="2022-03"), screened("2026-11-06"))
        self.assertEqual(result.code, "DECEASED")

    def test_a_death_after_the_screening_does_not_clear(self):
        self.assertIsNone(
            rules.deceased(customer(), hit(death="2027-01-01"), screened("2026-11-06"))
        )

    def test_no_death_date_cannot_clear(self):
        # A profile marked deceased without a date gives no death fact at all.
        self.assertIsNone(rules.deceased(customer(), hit(), screened()))

    def test_a_partial_death_date_inside_the_screening_month_cannot_be_ordered(self):
        self.assertIsNone(
            rules.deceased(customer(), hit(death="2026-11"), screened("2026-11-06"))
        )


class TestTemporalImpossibility(unittest.TestCase):
    def test_a_customer_too_young_at_the_earliest_report(self):
        result = verdict(
            customer(verified_dob="2007-08-21", verified_name="Ada Lovelace"),
            hit(report="2020-01-08"),
        )
        self.assertEqual(result.code, "TEMPORAL_IMPOSSIBILITY")
        self.assertEqual(result.findings[0].detail["age"], 12)

    def test_a_year_only_birth_date_uses_the_oldest_they_could_be(self):
        result = verdict(customer(verified_dob="2007"), hit(report="2020-01-08"))
        self.assertEqual(result.findings[0].detail["age"], 13)

    def test_exactly_sixteen_does_not_clear(self):
        self.assertIsNone(
            rules.temporal_impossibility(
                customer(verified_dob="2004-01-01"), hit(report="2020-01-08"), screened()
            )
        )

    def test_no_dated_report_cannot_clear(self):
        self.assertIsNone(
            rules.temporal_impossibility(customer(verified_dob="2007"), hit(), screened())
        )

    def test_no_customer_date_of_birth_cannot_clear(self):
        self.assertIsNone(
            rules.temporal_impossibility(customer(), hit(report="2020-01-08"), screened())
        )

    def test_every_declared_date_must_make_them_too_young(self):
        # One record says 2007, another says 1980: the hit is not cleared on timing.
        facts = CustomerFacts(
            record_ids=("CUS-1", "CUS-2"),
            entity_type="Individual",
            declared_names=[Fact("Ada Lovelace", ("CUS-1",))],
            declared_dobs=[Fact(dates.parse("2007-01-01"), ("CUS-1",)),
                           Fact(dates.parse("1980-01-01"), ("CUS-2",))],
            country_facts=[],
            approved=[],
        )
        self.assertIsNone(
            rules.temporal_impossibility(facts, hit(report="2020-01-08"), screened())
        )

    def test_a_company_incorporated_after_the_report(self):
        result = verdict(
            customer(entity_type="Company", names=("Pescanova SA",),
                     verified_dob="2022-05-21", verified_name="Pescanova SA"),
            hit(entity_type="Company", names=("Pescanova SA",), report="2020-01-08"),
        )
        self.assertEqual(result.code, "TEMPORAL_IMPOSSIBILITY")
        self.assertTrue(result.findings[0].detail["is_company"])

    def test_a_company_incorporated_before_the_report_does_not_clear(self):
        self.assertIsNone(
            rules.temporal_impossibility(
                customer(entity_type="Company", verified_dob="2001-03-20"),
                hit(entity_type="Company", report="2020-01-08"),
                screened(),
            )
        )

    def test_a_company_incorporated_the_same_year_cannot_be_ordered_without_months(self):
        self.assertIsNone(
            rules.temporal_impossibility(
                customer(entity_type="Company", verified_dob="2020"),
                hit(entity_type="Company", report="2020-01-08"),
                screened(),
            )
        )


class TestDobMismatch(unittest.TestCase):
    def test_a_year_more_than_one_out(self):
        result = verdict(
            customer(verified_dob="1979-11-08"),
            hit(dobs=["1976", "1977"], dob_origin=FROM_NOTES),
        )
        self.assertEqual(result.code, "DOB_MISMATCH")

    def test_one_agreeing_date_prevents_it(self):
        self.assertIsNone(
            rules.dob_mismatch(
                customer(verified_dob="1968-03-05"), hit(dobs=["1950", "1968"]), screened()
            )
        )

    def test_a_year_exactly_one_out_does_not_contradict(self):
        self.assertIsNone(
            rules.dob_mismatch(customer(verified_dob="1968"), hit(dobs=["1967"]), screened())
        )

    def test_a_different_month_in_the_same_year_contradicts(self):
        result = rules.dob_mismatch(
            customer(verified_dob="1965-03-28"), hit(dobs=["1965-09-10"]), screened()
        )
        self.assertIsNotNone(result)

    def test_no_hit_date_cannot_clear(self):
        self.assertIsNone(
            rules.dob_mismatch(customer(verified_dob="1979-11-08"), hit(), screened())
        )

    def test_no_customer_date_cannot_clear(self):
        self.assertIsNone(rules.dob_mismatch(customer(), hit(dobs=["1976"]), screened()))

    def test_every_declared_date_must_contradict(self):
        facts = CustomerFacts(
            record_ids=("CUS-1", "CUS-2"),
            entity_type="Individual",
            declared_names=[Fact("Ada Lovelace", ("CUS-1",))],
            declared_dobs=[Fact(dates.parse("1979-11-08"), ("CUS-1",)),
                           Fact(dates.parse("1976-05-01"), ("CUS-2",))],
            country_facts=[],
            approved=[],
        )
        self.assertIsNone(rules.dob_mismatch(facts, hit(dobs=["1976"]), screened()))

    def test_a_search_derived_date_is_cited(self):
        result = rules.dob_mismatch(
            customer(verified_dob="2002-05-13"),
            hit(dobs=["1972", "1973"], dob_origin="search", result_ids=("SR-1",)),
            screened(),
        )
        self.assertIn("SR-1", result.sources())
        self.assertIn("KYC-1", result.sources())


class TestLocationMismatch(unittest.TestCase):
    def test_every_country_differs(self):
        result = verdict(
            customer(countries=("Netherlands",)), hit(countries=("United States",))
        )
        self.assertEqual(result.code, "LOCATION_MISMATCH")

    def test_one_shared_country_prevents_it(self):
        self.assertIsNone(
            rules.location_mismatch(
                customer(countries=("Netherlands", "United States")),
                hit(countries=("United States",)),
                screened(),
            )
        )

    def test_a_customer_with_no_country_is_not_a_difference(self):
        self.assertIsNone(
            rules.location_mismatch(customer(), hit(countries=("Spain",)), screened())
        )

    def test_a_hit_with_no_country_is_not_a_difference(self):
        self.assertIsNone(
            rules.location_mismatch(customer(countries=("Spain",)), hit(), screened())
        )

    def test_the_evidence_is_every_record_that_supplied_a_country(self):
        facts = CustomerFacts(
            record_ids=("CUS-1", "CUS-2"),
            entity_type="Individual",
            declared_names=[Fact("Ada Lovelace", ("CUS-1",))],
            declared_dobs=[],
            country_facts=[Fact("Ghana", ("CUS-1",)), Fact("Netherlands", ("NOTE-9",))],
            approved=[],
        )
        result = rules.location_mismatch(facts, hit(countries=("United States",)), screened())
        self.assertEqual(result.sources(), ["CUS-1", "NOTE-9"])


class TestLocationException(unittest.TestCase):
    """"A country difference does not clear a hit whose name and date of birth agree:
    that hit is `REVIEW`." """

    def test_name_and_dob_agreeing_turns_the_clear_into_a_review(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", verified_dob="1815-12-10",
                     countries=("Netherlands",)),
            hit(names=("Lovelace, Ada",), dobs=["1815-12-10"], countries=("United States",)),
        )
        self.assertEqual(result.decision, "REVIEW")
        self.assertEqual(result.code, "INSUFFICIENT_DATA")
        self.assertEqual(result.review_detail["reason"], "location_exception")

    def test_it_does_not_save_a_hit_that_also_mismatches_on_name(self):
        result = verdict(
            customer(verified_name="Grace Hopper", verified_dob="1815-12-10",
                     countries=("Netherlands",)),
            hit(names=("Lovelace, Ada",), dobs=["1815-12-10"], countries=("United States",)),
        )
        self.assertEqual(result.decision, "DIFFERENT_ENTITY")

    def test_it_does_not_save_a_hit_that_is_deceased(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", verified_dob="1815-12-10",
                     countries=("Netherlands",)),
            hit(names=("Lovelace, Ada",), dobs=["1815-12-10"],
                countries=("United States",), death="2020-01-01"),
        )
        self.assertEqual(result.decision, "DIFFERENT_ENTITY")
        self.assertEqual(result.code, "DECEASED")


class TestNameMismatchVerified(unittest.TestCase):
    def test_a_verified_name_that_agrees_with_nothing(self):
        result = verdict(
            customer(names=("Ridwan Azeez",), verified_name="CHINEDU AZEEZ"),
            hit(names=("Ridwan, Azeez",)),
        )
        self.assertEqual(result.code, "NAME_MISMATCH_VERIFIED")
        self.assertEqual(result.findings[0].sources(), ["KYC-1"])

    def test_it_fires_even_when_the_record_name_agrees(self):
        # "even if the name on their record does"
        result = rules.name_mismatch_verified(
            customer(names=("Ridwan Azeez",), verified_name="CHINEDU AZEEZ"),
            hit(names=("Ridwan, Azeez",)),
            screened(),
        )
        self.assertIsNotNone(result)

    def test_a_verified_name_that_agrees_does_not_fire(self):
        self.assertIsNone(
            rules.name_mismatch_verified(
                customer(verified_name="Augusta Ada Lovelace"),
                hit(names=("Lovelace, Ada",)),
                screened(),
            )
        )

    def test_an_alias_is_enough_to_prevent_it(self):
        self.assertIsNone(
            rules.name_mismatch_verified(
                customer(verified_name="Grace Brewster Hopper"),
                hit(names=("Lovelace, Ada", "Grace Hopper (AKA)")),
                screened(),
            )
        )

    def test_without_a_verified_name_it_cannot_fire(self):
        self.assertIsNone(
            rules.name_mismatch_verified(
                customer(names=("Grace Hopper",)), hit(names=("Lovelace, Ada",)), screened()
            )
        )

    def test_a_verified_name_with_one_real_part_cannot_clear_a_person(self):
        self.assertIsNone(
            rules.name_mismatch_verified(
                customer(verified_name="GILBERT"), hit(names=("Lovelace, Ada",)), screened()
            )
        )


class TestAgreement(unittest.TestCase):
    def test_name_and_dob_and_country(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", verified_dob="1968-03-05",
                     countries=("Spain",)),
            hit(names=("Lovelace, Ada",), dobs=["1967", "1968"], dob_origin=FROM_NOTES,
                countries=("Spain",)),
        )
        self.assertEqual(result.decision, "SAME_ENTITY")
        self.assertEqual(result.code, "NAME_DOB_LOCATION_MATCH")
        self.assertIn("NAME_DOB_MATCH", result.codes())

    def test_name_and_dob_without_a_shared_country(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", verified_dob="1968-03-05"),
            hit(names=("Lovelace, Ada",), dobs=["1968"]),
        )
        self.assertEqual(result.code, "NAME_DOB_MATCH")

    def test_a_name_alone_is_not_enough_to_confirm_a_person(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", countries=("Spain",)),
            hit(names=("Lovelace, Ada",), countries=("Spain",)),
        )
        self.assertEqual(result.decision, "REVIEW")

    def test_a_company_is_confirmed_on_name_and_country(self):
        result = verdict(
            customer(entity_type="Company", names=("Pescanova, Sociedad Anonima",),
                     verified_name="Pescanova SA", countries=("Spain",)),
            hit(entity_type="Company", names=("Pescanova, Inc",), countries=("Spain",)),
        )
        self.assertEqual(result.decision, "SAME_ENTITY")
        self.assertEqual(result.code, "NAME_LOCATION_MATCH")

    def test_a_company_without_a_shared_country_is_a_review(self):
        result = verdict(
            customer(entity_type="Company", names=("Pescanova SA",),
                     verified_name="Pescanova SA"),
            hit(entity_type="Company", names=("Pescanova, Inc",)),
        )
        self.assertEqual(result.decision, "REVIEW")

    def test_name_location_match_is_companies_only(self):
        result = verdict(
            customer(verified_name="Ada Lovelace", countries=("Spain",)),
            hit(names=("Lovelace, Ada",), countries=("Spain",)),
        )
        self.assertNotIn("NAME_LOCATION_MATCH", result.codes())

    def test_a_customer_with_fewer_than_two_real_name_parts_is_never_confirmed(self):
        result = verdict(
            customer(names=("Pawel N/a N/a",), verified_name="PAWEL", verified_dob="1968-03-05"),
            hit(names=("Pawel Smith",), dobs=["1968"]),
        )
        self.assertEqual(result.decision, "REVIEW")


class TestCodeOrderAndEvidence(unittest.TestCase):
    def test_several_contradictions_report_the_first_in_the_fixed_order(self):
        result = verdict(
            customer(verified_name="Grace Hopper", verified_dob="2007-08-21",
                     countries=("Singapore",)),
            hit(names=("Lovelace, Ada",), dobs=["1950"], countries=("Pakistan",),
                report="2020-01-08"),
        )
        self.assertEqual(result.code, "TEMPORAL_IMPOSSIBILITY")
        self.assertEqual(
            result.codes(),
            ["TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
             "NAME_MISMATCH_VERIFIED"],
        )

    def test_the_evidence_is_the_union_of_what_fired(self):
        result = verdict(
            customer(record_ids=("CUS-1",), verified_name="Grace Hopper",
                     verified_dob="2007-08-21", countries=("Singapore",)),
            hit(names=("Lovelace, Ada",), countries=("Pakistan",), report="2020-01-08"),
        )
        self.assertEqual(result.sources(), ["CUS-1", "KYC-1"])

    def test_nothing_at_all_is_a_review(self):
        result = verdict(customer(names=("Grace Hopper",)), hit(names=("Lovelace, Ada",)))
        self.assertEqual(result.decision, "REVIEW")
        self.assertEqual(result.code, "INSUFFICIENT_DATA")

    def test_evaluating_twice_gives_the_same_verdict(self):
        cust = customer(verified_name="Ada Lovelace", verified_dob="1968-03-05",
                        countries=("Spain",))
        h = hit(names=("Lovelace, Ada",), dobs=["1968"], countries=("Spain",))
        first, second = verdict(cust, h), verdict(cust, h)
        self.assertEqual((first.decision, first.code, first.sources()),
                         (second.decision, second.code, second.sources()))


if __name__ == "__main__":
    unittest.main(verbosity=2)

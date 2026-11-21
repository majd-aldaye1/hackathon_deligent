"""Step 9: the guards that stop a failed extraction from becoming a clear.

POLICY.md's contradictions all quantify over *every* fact of a kind — "every country tied
to the customer", "every birth date the hit gives".  So a fact we failed to read is not an
absent fact: the set we are quantifying over is simply not the set.  Each guard below makes
that explicit, and `tools/ablate.py` is the measurement that justified it.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import customer_facts as cf  # noqa: E402
from system import dates, hit_facts, notes_regex, rules  # noqa: E402
from tests.test_rules import customer, hit, screened  # noqa: E402


class TestResidenceCue(unittest.TestCase):
    """Telling "names no country" from "names a country we could not place"."""

    def test_a_residence_statement_is_recognised_even_without_a_country(self):
        note = {"channel": "email",
                "text": "The client lived and worked in Freedonia from 2010 to 2016."}
        self.assertEqual(notes_regex.places_lived(note), [])
        self.assertTrue(notes_regex.looks_like_residence(note))

    def test_a_generic_support_note_is_not_a_residence_statement(self):
        note = {"channel": "app", "text": "Customer reported a lost card. Card frozen."}
        self.assertFalse(notes_regex.looks_like_residence(note))

    def test_a_kyc_note_is_never_a_residence_statement(self):
        note = {"channel": "kyc", "text": "Verified the passport, the holder resides abroad."}
        self.assertFalse(notes_regex.looks_like_residence(note))


class TestCountriesMayBeIncomplete(unittest.TestCase):
    """Guard A: a place we could not read means the country set is not the whole set."""

    def _folder(self, note_text):
        return fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada Lovelace", residence_country="Australia",
                                        nationality="Australian")],
            accounts=[fixture.account("ACC-A", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            notes=[fixture.note("NOTE-1", "cus-a@example.test", note_text)],
        )

    def test_an_unreadable_place_marks_the_set_incomplete(self):
        with self._folder("The client lived and worked in Freedonia from 2010 to 2016.") as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertTrue(facts.countries_may_be_incomplete)
            self.assertEqual(facts.unreadable_places, ("NOTE-1",))

    def test_a_readable_place_does_not(self):
        with self._folder("The client lived and worked in Portugal from 2010 to 2016.") as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertFalse(facts.countries_may_be_incomplete)
            self.assertIn("Portugal", facts.country_keys())

    def test_a_generic_note_does_not(self):
        with self._folder("Customer reported a lost card.") as data:
            self.assertFalse(cf.gather(data, ["CUS-A"]).countries_may_be_incomplete)

    def test_an_incomplete_country_set_cannot_clear_on_location(self):
        with self._folder("The client lived and worked in Freedonia from 2010 to 2016.") as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIsNone(
                rules.location_mismatch(facts, hit(countries=("United States",)), screened())
            )

    def test_a_complete_country_set_still_clears(self):
        with self._folder("Customer reported a lost card.") as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIsNotNone(
                rules.location_mismatch(facts, hit(countries=("United States",)), screened())
            )


class TestVerifiedDobMayBeMissing(unittest.TestCase):
    """Guard B: a declared date must not clear when the verified one is unread."""

    def _folder(self, note_text, with_provider_check=False):
        tables = {
            "customers": [fixture.customer("CUS-A", "Ada Lovelace", dob="1979-11-08")],
            "accounts": [fixture.account("ACC-A", "CUS-A")],
            "onboarding": [fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            "notes": [fixture.note("NOTE-1", "cus-a@example.test", note_text, channel="kyc")],
        }
        if with_provider_check:
            tables["kyc_checks"] = [
                fixture.check("KYC-1", "APP-A", verified_dob="1979-11-08",
                              verified_name="Ada Lovelace")
            ]
        return fixture.Folder(**tables)

    def test_an_unreadable_identity_note_blocks_a_date_of_birth_clear(self):
        # A note filed as an identity check that our patterns cannot read at all.
        with self._folder("Paperwork for the holder was placed on file.") as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertTrue(facts.verified_dob_may_be_missing)
            self.assertIsNone(
                rules.dob_mismatch(facts, hit(dobs=["1976"]), screened())
            )

    def test_a_readable_identity_note_allows_it(self):
        text = ("Onfido verified the passport for ADA LOVELACE, born 1979-11-08, "
                "from United Kingdom on 2024-01-01.")
        with self._folder(text) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertFalse(facts.verified_dob_may_be_missing)
            self.assertIsNotNone(rules.dob_mismatch(facts, hit(dobs=["1976"]), screened()))

    def test_an_approved_check_without_a_date_blocks_it(self):
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada Lovelace", dob="1979-11-08")],
            accounts=[fixture.account("ACC-A", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            kyc_checks=[fixture.check("KYC-1", "APP-A", verified_name="Ada Lovelace",
                                      verified_dob=None)],
        ) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertTrue(facts.verified_dob_may_be_missing)
            self.assertIsNone(rules.dob_mismatch(facts, hit(dobs=["1976"]), screened()))

    def test_a_customer_with_no_identity_check_at_all_may_still_clear(self):
        # Decision log D7: a declared date may clear when nothing verified exists to read.
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada Lovelace", dob="1979-11-08")],
        ) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertFalse(facts.verified_dob_may_be_missing)
            self.assertIsNotNone(rules.dob_mismatch(facts, hit(dobs=["1976"]), screened()))

    def test_the_review_reason_says_why_the_disagreement_was_not_relied_on(self):
        from system import reasons

        with self._folder("Paperwork for the holder was placed on file.") as data:
            facts = cf.gather(data, ["CUS-A"])
            result = rules.evaluate(facts, hit(dobs=["1976"]), screened())
            self.assertEqual(result.decision, "REVIEW")
            text = reasons.for_review(result.review_detail)
            self.assertIn("could not be read", text)


class TestHitDobUnreadable(unittest.TestCase):
    """Guard C: the location exception cannot be applied to a date we could not read."""

    def test_a_birth_sentence_we_cannot_parse_marks_the_date_unreadable(self):
        notes = "Pere Punti was charged at some point in his life."
        self.assertTrue(hit_facts.states_a_birth("He was born at some point."))
        self.assertFalse(hit_facts.states_a_birth(notes))

    def test_a_dated_report_is_not_a_birth_sentence(self):
        notes = "According to a source; June 28, 2018: he was born in a hospital."
        self.assertFalse(hit_facts.states_a_birth(notes))

    def test_an_unreadable_hit_date_blocks_a_location_clear_when_the_name_agrees(self):
        unreadable = hit(countries=("Vietnam",))
        unreadable.dob_unreadable = True
        self.assertIsNone(
            rules.location_mismatch(
                customer(names=("Ada Lovelace",), countries=("United States",)),
                unreadable,
                screened(),
            )
        )

    def test_it_does_not_block_when_the_name_disagrees(self):
        # The exception could never have applied, so there is nothing unknown.
        unreadable = hit(names=("Grace Hopper",), countries=("Vietnam",))
        unreadable.dob_unreadable = True
        self.assertIsNotNone(
            rules.location_mismatch(
                customer(names=("Ada Lovelace",), countries=("United States",)),
                unreadable,
                screened(),
            )
        )

    def test_a_hit_that_simply_states_no_date_still_clears(self):
        self.assertIsNotNone(
            rules.location_mismatch(
                customer(names=("Ada Lovelace",), countries=("United States",)),
                hit(countries=("Vietnam",)),
                screened(),
            )
        )


class TestTheAgeCuesTheGuardFound(unittest.TestCase):
    """Guard C pointed at two phrasings the cue list was missing."""

    def test_years_of_age(self):
        text = "Pere Punti reached 37 years of age by November 1981, the time he was charged."
        self.assertEqual(
            [d.iso() for d in hit_facts.birth_dates_from_notes(text)], ["1943", "1944"]
        )

    def test_at_age(self):
        text = "Adam Tomasz Drozd, at age 31, had charges filed against him in December 2005."
        self.assertEqual(
            [d.iso() for d in hit_facts.birth_dates_from_notes(text)], ["1973", "1974"]
        )

    def test_thousands_are_still_not_ages(self):
        text = "In March 2019 the police seized 250,000 in cash at age 0."
        self.assertEqual(hit_facts.birth_dates_from_notes(text), [])


class TestContradictionState(unittest.TestCase):
    def test_dobs_contradict_is_reported_separately_from_not_agreeing(self):
        cust = customer(verified_dob="1979-11-08")
        self.assertTrue(rules.dobs_contradict(cust, hit(dobs=["1950"])))
        # One year apart: neither agrees nor contradicts.
        self.assertFalse(rules.dobs_contradict(customer(verified_dob="1968"), hit(dobs=["1967"])))

    def test_a_clear_on_the_date_does_not_also_describe_the_dates_as_unsettled(self):
        from system import reasons

        result = rules.evaluate(
            customer(verified_dob="1995-12-17", names=("Adam Drozd",)),
            hit(names=("Drozd, Adam Tomasz",), dobs=["1973", "1974"],
                dob_origin=hit_facts.FROM_NOTES),
            screened(),
        )
        text = reasons.for_contradiction(result.findings, None, result.context)
        self.assertEqual(result.code, "DOB_MISMATCH")
        self.assertNotIn("neither agree nor contradict", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

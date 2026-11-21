"""Step 5: the customer's full picture, with every fact's source.

POLICY.md principle 4: "Verified beats declared ... Rejected or expired checks are not
evidence."  Principle 6: the customer's countries are "residence and nationality on all
their records, the approved identity document, and places the notes say they lived".
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import customer_facts as cf  # noqa: E402
from system import loader, persons  # noqa: E402
from system.facts import Fact, merge, sources  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


class TestFact(unittest.TestCase):
    def test_sources_are_sorted_and_deduplicated(self):
        self.assertEqual(Fact("x", ("B", "A", "A", "")).source_ids, ("A", "B"))

    def test_a_single_source_may_be_a_string(self):
        self.assertEqual(Fact("x", "A").source_ids, ("A",))

    def test_merge_collapses_equal_values_and_keeps_every_source(self):
        merged = merge([Fact("Spain", "CUS-1"), Fact("Spain", "NOTE-1"), Fact("Italy", "CUS-2")])
        self.assertEqual([(f.value, f.source_ids) for f in merged],
                         [("Italy", ("CUS-2",)), ("Spain", ("CUS-1", "NOTE-1"))])

    def test_sources_flattens_groups(self):
        self.assertEqual(sources([Fact("a", "A"), Fact("b", "B")], Fact("c", "C")),
                         ["A", "B", "C"])

    def test_a_none_value_is_dropped_by_merge(self):
        self.assertEqual(merge([Fact(None, "A"), Fact("x", "B")]), [Fact("x", "B")])


def folder_with(check=None, note=None, customers=None, extra_customers=()):
    customers = customers or [
        fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10",
                         residence_country="GB", nationality="British")
    ]
    kwargs = {
        "customers": list(customers) + list(extra_customers),
        "accounts": [fixture.account("ACC-A", "CUS-A")],
        "onboarding": [fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
    }
    if check is not None:
        kwargs["kyc_checks"] = check if isinstance(check, list) else [check]
    if note is not None:
        kwargs["notes"] = note if isinstance(note, list) else [note]
    return fixture.Folder(**kwargs)


class TestVerifiedBeatsDeclared(unittest.TestCase):
    def test_the_approved_check_supplies_the_legal_name_and_dob(self):
        with folder_with(fixture.check("KYC-1", "APP-A", verified_name="Augusta Ada Byron",
                                       verified_dob="1815-12-10",
                                       document_country="United Kingdom")) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual(facts.verified_name.value, "Augusta Ada Byron")
            self.assertEqual(facts.verified_name.source_ids, ("KYC-1",))
            self.assertEqual(facts.verified_dob.value.iso(), "1815-12-10")

    def test_a_rejected_check_is_not_evidence(self):
        with folder_with(fixture.check("KYC-1", "APP-A", "rejected",
                                       verified_name="Wrong Name")) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIsNone(facts.verified_name)
            self.assertFalse(facts.verified_name_usable())

    def test_an_expired_check_is_not_evidence(self):
        with folder_with(fixture.check("KYC-1", "APP-A", "expired",
                                       verified_name="Old Name")) as data:
            self.assertIsNone(cf.gather(data, ["CUS-A"]).verified_name)

    def test_the_most_recent_approved_check_wins(self):
        with folder_with([
            fixture.check("KYC-1", "APP-A", verified_name="Older Name", checked_at="2020-01-01"),
            fixture.check("KYC-2", "APP-A", verified_name="Newer Name", checked_at="2024-06-01"),
        ]) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual(facts.verified_name.value, "Newer Name")
            self.assertEqual(facts.verified_name.source_ids, ("KYC-2",))

    def test_a_field_the_newest_check_omits_falls_back_to_an_older_approved_one(self):
        with folder_with([
            fixture.check("KYC-1", "APP-A", verified_name="Ada Byron",
                          verified_dob="1815-12-10", checked_at="2020-01-01"),
            fixture.check("KYC-2", "APP-A", verified_name="Ada Byron",
                          verified_dob=None, checked_at="2024-06-01"),
        ]) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual(facts.verified_name.source_ids, ("KYC-2",))
            self.assertEqual(facts.verified_dob.value.iso(), "1815-12-10")
            self.assertEqual(facts.verified_dob.source_ids, ("KYC-1",))

    def test_a_check_written_up_in_a_note_counts(self):
        note = fixture.note("NOTE-1", "cus-a@example.test",
                            "Onfido verified the passport for AUGUSTA ADA BYRON "
                            "(DOB 10/12/1815) from United Kingdom on 2024-01-01.",
                            channel="kyc", created_at="2024-01-01")
        with folder_with(note=note) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual(facts.verified_name.value, "AUGUSTA ADA BYRON")
            self.assertEqual(facts.verified_name.source_ids, ("NOTE-1",))
            self.assertEqual(facts.verified_dob.value.iso(), "1815-12-10")

    def test_a_provider_check_and_a_note_are_ranked_by_date(self):
        note = fixture.note("NOTE-1", "cus-a@example.test",
                            "Onfido verified the passport for GRACE BREWSTER HOPPER "
                            "(DOB 10/12/1815) from United Kingdom on 2025-01-01.",
                            channel="kyc", created_at="2025-01-01")
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", verified_name="Check Name",
                                verified_dob="1815-12-10", checked_at="2020-01-01"),
            note=note,
        ) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual(facts.verified_name.value, "GRACE BREWSTER HOPPER")

    def test_a_refused_note_check_is_not_evidence(self):
        note = fixture.note("NOTE-1", "cus-a@example.test",
                            "Onfido could not verify the passport for AUGUSTA ADA BYRON "
                            "(DOB 10/12/1815) from United Kingdom.",
                            channel="kyc")
        with folder_with(note=note) as data:
            self.assertIsNone(cf.gather(data, ["CUS-A"]).verified_name)


class TestDatesOfBirth(unittest.TestCase):
    def test_a_verified_dob_is_the_only_one_considered(self):
        with folder_with(fixture.check("KYC-1", "APP-A", verified_dob="1820-01-01")) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertEqual([f.value.iso() for f in facts.dob_facts()], ["1820-01-01"])

    def test_without_a_verified_dob_every_declared_one_counts(self):
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", "rejected"),
            customers=[
                fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10", phone="+44 1"),
                fixture.customer("CUS-B", "Ada Lovelace", dob="1815-12-10", phone="+44 1"),
            ],
        ) as data:
            facts = cf.gather(data, ["CUS-A", "CUS-B"])
            self.assertEqual([f.value.iso() for f in facts.dob_facts()], ["1815-12-10"])
            self.assertEqual(facts.dob_facts()[0].source_ids, ("CUS-A", "CUS-B"))

    def test_records_that_declare_different_dobs_give_several_facts(self):
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", "rejected"),
            customers=[
                fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10"),
                fixture.customer("CUS-B", "Ada Lovelace", dob="1816-01-01"),
            ],
        ) as data:
            facts = cf.gather(data, ["CUS-A", "CUS-B"])
            self.assertEqual([f.value.iso() for f in facts.dob_facts()],
                             ["1815-12-10", "1816-01-01"])


class TestCountries(unittest.TestCase):
    def test_residence_and_nationality_on_every_record(self):
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", "rejected"),
            customers=[
                fixture.customer("CUS-A", "Ada", residence_country="GB", nationality="British"),
                fixture.customer("CUS-B", "Ada", residence_country="Ireland", nationality="Irish"),
            ],
        ) as data:
            facts = cf.gather(data, ["CUS-A", "CUS-B"])
            self.assertEqual(facts.country_keys(), ["Ireland", "United Kingdom"])

    def test_the_approved_document_country_counts(self):
        with folder_with(fixture.check("KYC-1", "APP-A", document_country="Nigeria")) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIn("Nigeria", facts.country_keys())
            nigeria = [f for f in facts.country_facts() if f.value == "Nigeria"][0]
            self.assertEqual(nigeria.source_ids, ("KYC-1",))

    def test_a_rejected_documents_country_does_not_count(self):
        with folder_with(fixture.check("KYC-1", "APP-A", "rejected",
                                       document_country="Nigeria")) as data:
            self.assertNotIn("Nigeria", cf.gather(data, ["CUS-A"]).country_keys())

    def test_places_the_notes_say_they_lived_count(self):
        note = fixture.note("NOTE-1", "cus-a@example.test",
                            "The client maintained a job and home in Portugal between 2010 and 2011.")
        with folder_with(note=note) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIn("Portugal", facts.country_keys())
            portugal = [f for f in facts.country_facts() if f.value == "Portugal"][0]
            self.assertEqual(portugal.source_ids, ("NOTE-1",))

    def test_a_generic_support_note_adds_no_country(self):
        note = fixture.note("NOTE-1", "cus-a@example.test", "Customer reported a lost card.")
        with folder_with(note=note) as data:
            self.assertEqual(cf.gather(data, ["CUS-A"]).country_keys(), ["United Kingdom"])

    def test_one_country_from_several_sources_keeps_them_all(self):
        note = fixture.note("NOTE-1", "cus-a@example.test",
                            "The client lived and worked in the United Kingdom from 2010 to 2016.")
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", document_country="United Kingdom"),
            note=note,
        ) as data:
            facts = cf.gather(data, ["CUS-A"])
            uk = [f for f in facts.country_facts() if f.value == "United Kingdom"][0]
            self.assertEqual(uk.source_ids, ("CUS-A", "KYC-1", "NOTE-1"))


class TestIsolation(unittest.TestCase):
    """POLICY principle 2: "Never use another customer's records." """

    def test_another_customers_notes_and_checks_are_not_read(self):
        other = fixture.customer("CUS-OTHER", "Someone Else", residence_country="Japan")
        note = [
            fixture.note("NOTE-1", "cus-other@example.test",
                         "The client lived and worked in Japan from 2010 to 2016."),
        ]
        with folder_with(note=note, extra_customers=[other]) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertNotIn("Japan", facts.country_keys())
            self.assertEqual(facts.note_ids, ())


class TestNamesAndUsability(unittest.TestCase):
    def test_the_verified_name_comes_first(self):
        with folder_with(fixture.check("KYC-1", "APP-A", verified_name="Augusta Ada Byron")) as data:
            self.assertEqual(cf.gather(data, ["CUS-A"]).names()[0], "Augusta Ada Byron")

    def test_a_one_part_verified_name_cannot_clear_an_individual(self):
        with folder_with(fixture.check("KYC-1", "APP-A", verified_name="GILBERT")) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertIsNotNone(facts.verified_name)
            self.assertFalse(facts.verified_name_usable())

    def test_a_one_part_verified_name_can_clear_a_company(self):
        with folder_with(
            check=fixture.check("KYC-1", "APP-A", verified_name="Pescanova"),
            customers=[fixture.customer("CUS-A", "Pescanova SA", entity_type="Company")],
        ) as data:
            facts = cf.gather(data, ["CUS-A"])
            self.assertTrue(facts.is_company)
            self.assertTrue(facts.verified_name_usable())

    def test_an_unknown_record_gives_an_empty_sheet(self):
        with folder_with() as data:
            facts = cf.gather(data, ["CUS-NOPE"])
            self.assertEqual(facts.names(), [])
            self.assertEqual(facts.country_keys(), [])


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.persons = persons.Persons(cls.data)
        cls.cache = {}

    def sheet(self, record_id):
        person = self.persons.person_of(record_id)
        if person not in self.cache:
            self.cache[person] = cf.gather(self.data, person)
        return self.cache[person]

    def test_the_verified_facts_the_practice_labels_name(self):
        expected = {
            "CUS-377745": ("ELVIRA VELASCO MORILLO", "1968-03-05", "NOTE-14E25A"),
            "CUS-323991": ("MARKUS GERHARD MUELLER", "1964-05-01", "NOTE-ADDA81"),
            "CUS-227265": ("SAMUEL DIAZ", "1988-10-03", "NOTE-302C97"),
            "CUS-171566": ("TASLIMA RAHIM ISLAM", "1994-05-04", "NOTE-CB3D0D"),
            "CUS-804632": ("MICHAEL EARL TILLEY", "1979-11-08", "NOTE-8548C1"),
            "CUS-270502": ("ALEKSANDAR RASKOVIC", "1979-04-17", "NOTE-CA9BBC"),
            "CUS-962814": ("Emran Ali", "1994-11-01", "KYC-038F14"),
            "CUS-648181": ("Tomasz Matteo Drozd", "1995-12-17", "KYC-DE8245"),
            "CUS-149132": ("CHINEDU AZEEZ", None, "KYC-20EE17"),
            "CUS-485845": ("SARAH JOHNSON", None, "KYC-2EA887"),
            "CUS-921880": ("Jonathan Reyes Whitfield", None, "KYC-F112AA"),
        }
        for record_id, (name, dob, source) in sorted(expected.items()):
            facts = self.sheet(record_id)
            self.assertEqual(facts.verified_name.value, name, record_id)
            self.assertEqual(facts.verified_name.source_ids, (source,), record_id)
            if dob is not None:
                self.assertEqual(facts.verified_dob.value.iso(), dob, record_id)
                self.assertEqual(facts.verified_dob.source_ids, (source,), record_id)

    def test_the_countries_the_practice_labels_name(self):
        expected = {
            "CUS-364225": ["Singapore", "United States"],
            "CUS-976714": ["Netherlands"],
            "CUS-048448": ["Bangladesh", "United Kingdom"],
            "CUS-921880": ["Peru", "United States"],
            "CUS-562751": ["Ghana", "Netherlands"],
            "CUS-028455": ["Netherlands", "United States"],
            "CUS-674104": ["United States"],
            "CUS-812010": ["United States"],
            "CUS-459031": ["Australia", "United States"],
            "CUS-629156": ["Denmark", "United Kingdom"],
            "CUS-007742": ["Nigeria", "United Kingdom"],
        }
        for record_id, keys in sorted(expected.items()):
            self.assertEqual(self.sheet(record_id).country_keys(), keys, record_id)

    def test_every_person_behind_an_alert_has_a_verified_name_and_dob(self):
        from system import resolve

        sheets = {}
        for alert in self.data.alerts:
            resolution = resolve.resolve_customer(
                self.data, self.persons, resolve.Screened(alert)
            )
            for person in resolution.persons:
                sheets.setdefault(person, cf.gather(self.data, person))
        self.assertEqual(len(sheets), 461)
        self.assertEqual(sum(1 for f in sheets.values() if f.verified_name), 461)
        self.assertEqual(sum(1 for f in sheets.values() if f.verified_dob), 461)
        self.assertEqual(sum(1 for f in sheets.values() if f.verified_name_usable()), 440)
        self.assertEqual(sum(1 for f in sheets.values() if not f.country_facts()), 0)
        from_notes = sum(
            1 for f in sheets.values() if f.verified_name.source_ids[0].startswith("NOTE-")
        )
        self.assertEqual(from_notes, 162)

    def test_gathering_is_deterministic(self):
        for record_id in ["CUS-377745", "CUS-171566", "CUS-485845"]:
            person = self.persons.person_of(record_id)
            first = cf.gather(self.data, person)
            second = cf.gather(self.data, person)
            self.assertEqual([(f.value, f.source_ids) for f in first.country_facts()],
                             [(f.value, f.source_ids) for f in second.country_facts()])
            self.assertEqual(first.names(), second.names())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Step 4: grouping records into persons, and the KYC chain they share.

POLICY.md principle 3: "Records that share a phone number and the same full date of birth
belong to the same person, and so do records whose approved identity checks carry the same
document number; a record linked to one of them in either way belongs to that person too.
... Sharing a phone or an address alone does not: family members often do."
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import kyc, loader, persons  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


class TestPhoneAndDateOfBirth(unittest.TestCase):
    def test_same_phone_and_same_full_dob_merge(self):
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada Lovelace", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-B", "Ada Lovelace", phone="+44 1", dob="10 December 1815"),
        ]) as data:
            p = persons.Persons(data)
            self.assertEqual(p.person_of("CUS-A"), ("CUS-A", "CUS-B"))

    def test_same_phone_and_different_dob_do_not_merge(self):
        # The family-member trap.
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada Lovelace", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-B", "Byron Lovelace", phone="+44 1", dob="1840-05-12"),
        ]) as data:
            p = persons.Persons(data)
            self.assertEqual(p.person_of("CUS-A"), ("CUS-A",))
            self.assertEqual(p.person_of("CUS-B"), ("CUS-B",))

    def test_same_phone_with_an_incomplete_dob_does_not_merge(self):
        # "the same *full* date of birth"
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada Lovelace", phone="+44 1", dob="1815"),
            fixture.customer("CUS-B", "Ada Lovelace", phone="+44 1", dob="1815"),
        ]) as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))

    def test_same_dob_without_a_shared_phone_does_not_merge(self):
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada Lovelace", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-B", "Ada Lovelace", phone="+44 2", dob="1815-12-10"),
        ]) as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))

    def test_a_shared_address_alone_does_not_merge(self):
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada Lovelace", address="1 Main St", dob="1815-12-10"),
            fixture.customer("CUS-B", "Byron Lovelace", address="1 Main St", dob="1815-12-10"),
        ]) as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))


class TestDocumentNumber(unittest.TestCase):
    def _folder(self, result_a="approved", result_b="approved", number_b="P1"):
        return fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada"), fixture.customer("CUS-B", "Ada")],
            accounts=[fixture.account("ACC-A", "CUS-A"), fixture.account("ACC-B", "CUS-B")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A"),
                        fixture.onboarding("ACC-B", "CUS-B", "APP-B")],
            kyc_checks=[fixture.check("KYC-A", "APP-A", result_a, document_number="P1"),
                        fixture.check("KYC-B", "APP-B", result_b, document_number=number_b)],
        )

    def test_the_same_document_number_on_approved_checks_merges(self):
        with self._folder() as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A", "CUS-B"))

    def test_a_rejected_check_is_not_evidence(self):
        with self._folder(result_b="rejected") as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))

    def test_an_expired_check_is_not_evidence(self):
        with self._folder(result_b="expired") as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))

    def test_different_document_numbers_do_not_merge(self):
        with self._folder(number_b="P2") as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-A"), ("CUS-A",))


class TestTransitivity(unittest.TestCase):
    def test_a_record_linked_to_one_of_them_belongs_to_the_person_too(self):
        # A and B share a phone and date of birth; B and C share a document number.
        with fixture.Folder(
            customers=[
                fixture.customer("CUS-A", "Ada", phone="+44 1", dob="1815-12-10"),
                fixture.customer("CUS-B", "Ada", phone="+44 1", dob="1815-12-10"),
                fixture.customer("CUS-C", "Ada", phone="+44 9", dob="1815-12-10"),
            ],
            accounts=[fixture.account("ACC-B", "CUS-B"), fixture.account("ACC-C", "CUS-C")],
            onboarding=[fixture.onboarding("ACC-B", "CUS-B", "APP-B"),
                        fixture.onboarding("ACC-C", "CUS-C", "APP-C")],
            kyc_checks=[fixture.check("KYC-B", "APP-B", document_number="P1"),
                        fixture.check("KYC-C", "APP-C", document_number="P1")],
        ) as data:
            p = persons.Persons(data)
            self.assertEqual(p.person_of("CUS-A"), ("CUS-A", "CUS-B", "CUS-C"))
            self.assertEqual(p.person_of("CUS-C"), ("CUS-A", "CUS-B", "CUS-C"))


class TestRepresentativeAndGrouping(unittest.TestCase):
    def test_the_representative_is_the_lowest_record_id(self):
        with fixture.Folder(customers=[
            fixture.customer("CUS-Z", "Ada", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-A", "Ada", phone="+44 1", dob="1815-12-10"),
        ]) as data:
            p = persons.Persons(data)
            self.assertEqual(p.representative("CUS-Z"), "CUS-A")
            self.assertEqual(p.representative("CUS-A"), "CUS-A")

    def test_persons_of_returns_distinct_persons_in_a_stable_order(self):
        with fixture.Folder(customers=[
            fixture.customer("CUS-A", "Ada", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-B", "Ada", phone="+44 1", dob="1815-12-10"),
            fixture.customer("CUS-C", "Grace"),
        ]) as data:
            p = persons.Persons(data)
            self.assertEqual(
                p.persons_of(["CUS-C", "CUS-B", "CUS-A"]),
                [("CUS-A", "CUS-B"), ("CUS-C",)],
            )

    def test_an_unknown_record_is_its_own_person(self):
        with fixture.Folder(customers=[fixture.customer("CUS-A", "Ada")]) as data:
            self.assertEqual(persons.Persons(data).person_of("CUS-NOPE"), ("CUS-NOPE",))


class TestKycChain(unittest.TestCase):
    def test_onboarding_is_joined_on_both_keys(self):
        # ACC-1 is a joint account.  CUS-B must not inherit CUS-A's applicant.
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada"), fixture.customer("CUS-B", "Byron")],
            accounts=[fixture.account("ACC-1", "CUS-A"), fixture.account("ACC-1", "CUS-B")],
            onboarding=[fixture.onboarding("ACC-1", "CUS-A", "APP-A")],
            kyc_checks=[fixture.check("KYC-A", "APP-A", verified_name="Augusta Ada Byron")],
        ) as data:
            self.assertEqual(kyc.applicant_ids(data, "CUS-A"), ["APP-A"])
            self.assertEqual(kyc.applicant_ids(data, "CUS-B"), [])
            self.assertIsNone(kyc.latest_approved(data, "CUS-B"))

    def test_only_approved_checks_count(self):
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada")],
            accounts=[fixture.account("ACC-A", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            kyc_checks=[fixture.check("KYC-1", "APP-A", "rejected", verified_name="Wrong"),
                        fixture.check("KYC-2", "APP-A", "expired", verified_name="Old")],
        ) as data:
            self.assertEqual(len(kyc.checks(data, "CUS-A")), 2)
            self.assertEqual(kyc.approved_checks(data, "CUS-A"), [])
            self.assertIsNone(kyc.latest_approved(data, "CUS-A"))

    def test_the_most_recent_approved_check_wins(self):
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada")],
            accounts=[fixture.account("ACC-A", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            kyc_checks=[
                fixture.check("KYC-1", "APP-A", verified_name="Older", checked_at="2020-01-01"),
                fixture.check("KYC-2", "APP-A", verified_name="Newer", checked_at="2024-06-01"),
            ],
        ) as data:
            self.assertEqual(kyc.latest_approved(data, "CUS-A")["verified_name"], "Newer")

    def test_checks_from_several_accounts_are_all_reachable(self):
        with fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada")],
            accounts=[fixture.account("ACC-1", "CUS-A"), fixture.account("ACC-2", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-1", "CUS-A", "APP-1"),
                        fixture.onboarding("ACC-2", "CUS-A", "APP-2")],
            kyc_checks=[fixture.check("KYC-1", "APP-1", document_number="P1"),
                        fixture.check("KYC-2", "APP-2", document_number="P2")],
        ) as data:
            self.assertEqual(sorted(kyc.applicant_ids(data, "CUS-A")), ["APP-1", "APP-2"])
            self.assertEqual(sorted(kyc.document_numbers(data, "CUS-A")), ["P1", "P2"])


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.persons = persons.Persons(cls.data)

    def test_the_merged_groups(self):
        groups = self.persons.merged_groups()
        self.assertEqual(len(groups), 123)  # 116 by phone and dob, 7 by document number
        self.assertEqual({len(g) for g in groups}, {2})

    def test_shared_phones_alone_do_not_merge(self):
        merged = set()
        for group in self.persons.merged_groups():
            for i, left in enumerate(group):
                for right in group[i + 1:]:
                    merged.add((left, right))
        by_phone = {}
        for cust in self.data.customers:
            if cust.get("phone"):
                by_phone.setdefault(cust["phone"], []).append(cust["record_id"])
        unmerged = 0
        for ids in by_phone.values():
            ids = sorted(ids)
            for i, left in enumerate(ids):
                for right in ids[i + 1:]:
                    if (left, right) not in merged:
                        unmerged += 1
        self.assertEqual(unmerged, 88)

    def test_the_onboarding_account_belongs_to_the_customer_it_names(self):
        for row in self.data.onboarding:
            accounts = self.data.accounts_by_customer.get(row["customer_id"], ())
            self.assertIn(row["account_id"], [a["account_id"] for a in accounts], row["customer_id"])

    def test_every_customer_reaches_at_most_one_applicant(self):
        for cust in self.data.customers[:5000]:
            self.assertLessEqual(len(kyc.applicant_ids(self.data, cust["record_id"])), 1)

    def test_building_is_deterministic(self):
        again = persons.Persons(self.data)
        self.assertEqual(again.merged_groups(), self.persons.merged_groups())


if __name__ == "__main__":
    unittest.main(verbosity=2)

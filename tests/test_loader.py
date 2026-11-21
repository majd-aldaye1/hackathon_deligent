"""Step 1 acceptance: the loader reads the data room's JSON Lines into one shape.

The fixture below is written the way the real folder writes things — the screened details
nested under `customer`, `null` for absent values, numbers as numbers, `details` as an
object, `path` as a list — and the files are named so that only their fields identify them.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import loader, model  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")

MINIMAL = {
    "alerts": [
        {
            "alert_id": "A-1",
            "screened_at": "2026-11-06",
            "customer": {
                "name": "Ada Lovelace",
                "entity_type": "Individual",
                "dob": "1815-12-10",
                "country": "GB",
                "city": None,
            },
            "account_ref": "ACC-1",
            "login_handle": None,
            "email": None,
            "hit_ids": ["H-1"],
        }
    ],
    "hits": [
        {
            "hit_id": "H-1",
            "alert_id": "A-1",
            "match_score": 100,
            "entity_type": "Individual",
            "name": "Lovelace, Ada",
            "first_name": "Ada",
            "middle_name": None,
            "last_name": "Lovelace",
            "best_matching_name": "Lovelace, Ada",
            "aliases": ["Augusta Ada King (AKA)"],
            "dobs": ["1815", "1816"],
            "place_of_birth": None,
            "life_status": "Alive",
            "deceased_date": None,
            "countries": ["United Kingdom"],
            "addresses": ["London, United Kingdom [Residency]"],
            "categories": ["PEP"],
            "subcategories": ["Legislature"],
            "primary_category": "PEP",
            "profile_notes": "She was born in 1815.",
            "details": {"pep": "Member | United Kingdom", "sanctions": ""},
            "relationships": ["Analytical Engine (AffiliatedCompany", "SOE)"],
        }
    ],
    "customers": [
        {
            "record_id": "CUS-1",
            "entity_type": "Individual",
            "full_name": "Ada Lovelace",
            "preferred_name": None,
            "login_name": None,
            "email": "ada@example.test",
            "dob": "10 December 1815",
            "phone": "+44 1",
        }
    ],
    "accounts": [{"account_id": "ACC-1", "customer_id": "CUS-1", "login_handle": "ada1"}],
    "onboarding": [
        {"account_id": "ACC-1", "customer_id": "CUS-1", "kyc_applicant_id": "APP-1"}
    ],
    "kyc_checks": [
        {
            "check_id": "KYC-1",
            "applicant_id": "APP-1",
            "result": "approved",
            "verified_name": "Augusta Ada Byron",
            "verified_dob": "1815-12-10",
            "document_country": "United Kingdom",
            "checked_at": "2024-01-01",
        }
    ],
    "notes": [
        {
            "note_id": "NOTE-1",
            "requester_email": "ada@example.test",
            "channel": "email",
            "text": "The client lived in Italy from 1840 to 1841.",
            "created_at": "2026-01-01",
        }
    ],
    "search_results": [
        {
            "result_id": "SR-1",
            "query": "ada lovelace",
            "title": "Ada Lovelace - report",
            "snippet": "Ada Lovelace, 36, a politically exposed person in United Kingdom.",
            "source": "x.example",
        }
    ],
    "practice_labels": [
        {
            "hit_id": "H-1",
            "alert_id": "A-1",
            "decision": "SAME_ENTITY",
            "reason_code": "NAME_DOB_MATCH",
            "customer_record_id": "CUS-1",
            "evidence": ["CUS-1", "KYC-1"],
            "reason": "Agrees on name and date of birth.",
            "path": ["account_ref ACC-1 -> accounts", "customer CUS-1"],
        }
    ],
}

# Filenames sharing no stem with a table name, to prove identification by field works.
ODD_NAMES = {
    "alerts": "table_01.jsonl",
    "hits": "table_02.jsonl",
    "customers": "table_03.jsonl",
    "accounts": "table_04.jsonl",
    "onboarding": "table_05.jsonl",
    "kyc_checks": "table_06.jsonl",
    "notes": "table_07.jsonl",
    "search_results": "table_08.jsonl",
    "practice_labels": "table_09.jsonl",
}


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="sponl-")
        for table, rows in MINIMAL.items():
            with open(os.path.join(cls.folder, ODD_NAMES[table]), "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
        cls.data = loader.load(cls.folder)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_every_table_identified_by_its_fields(self):
        for table in MINIMAL:
            self.assertEqual(len(self.data.tables[table]), 1, table)

    def test_accounts_and_onboarding_are_not_confused(self):
        self.assertEqual(self.data.accounts[0]["account_id"], "ACC-1")
        self.assertEqual(self.data.onboarding[0]["kyc_applicant_id"], "APP-1")
        self.assertNotIn("kyc_applicant_id", self.data.accounts[0])

    def test_the_screened_customer_object_is_flattened(self):
        alert = self.data.alerts[0]
        self.assertEqual(alert["customer_name"], "Ada Lovelace")
        self.assertEqual(alert["entity_type"], "Individual")
        self.assertEqual(alert["dob"], "1815-12-10")
        self.assertEqual(alert["country"], "GB")
        self.assertEqual(alert["city"], "")  # null inside the object
        self.assertNotIn("customer", alert)

    def test_list_fields_stay_lists(self):
        hit = self.data.hits[0]
        self.assertEqual(hit["dobs"], ["1815", "1816"])
        self.assertEqual(hit["countries"], ["United Kingdom"])
        self.assertEqual(hit["subcategories"], ["Legislature"])
        self.assertEqual(self.data.alerts[0]["hit_ids"], ["H-1"])

    def test_a_details_object_becomes_readable_text_keeping_its_keys(self):
        self.assertEqual(self.data.hits[0]["details"], "pep: Member | United Kingdom")

    def test_null_becomes_empty_string(self):
        hit = self.data.hits[0]
        self.assertEqual(hit["deceased_date"], "")
        self.assertEqual(hit["middle_name"], "")
        self.assertEqual(self.data.alerts[0]["login_handle"], "")

    def test_missing_multi_fields_become_empty_lists(self):
        self.assertEqual(self.data.hits[0]["nationality"], [])

    def test_numbers_become_strings(self):
        self.assertEqual(self.data.hits[0]["match_score"], "100")

    def test_label_field_aliases_and_list_path(self):
        label = self.data.practice_labels[0]
        self.assertEqual(label["reason_codes"], ["NAME_DOB_MATCH"])
        self.assertEqual(label["customer_record_ids"], ["CUS-1"])
        self.assertEqual(label["evidence"], ["CUS-1", "KYC-1"])
        self.assertEqual(label["reference_reason"], "Agrees on name and date of birth.")
        self.assertEqual(len(label["path"]), 2)

    def test_indexes(self):
        d = self.data
        self.assertEqual(d.hits_by_alert["A-1"][0]["hit_id"], "H-1")
        self.assertEqual(d.accounts_by_id["ACC-1"][0]["customer_id"], "CUS-1")
        self.assertEqual(d.accounts_by_login["ada1"][0]["account_id"], "ACC-1")
        self.assertEqual(d.customers_by_email["ada@example.test"][0]["record_id"], "CUS-1")
        self.assertIn(("ACC-1", "CUS-1"), d.onboarding_by_account_customer)
        self.assertEqual(d.kyc_by_applicant["APP-1"][0]["result"], "approved")
        self.assertEqual(d.notes_by_email["ada@example.test"][0]["note_id"], "NOTE-1")
        self.assertEqual(d.search_by_query["ada lovelace"][0]["result_id"], "SR-1")

    def test_name_index_uses_the_tokeniser_given(self):
        index = self.data.name_index(lambda text, company: text.lower().split())
        self.assertEqual(index["ada"], ["CUS-1"])

    def test_a_json_array_file_reads_as_well_as_json_lines(self):
        folder = tempfile.mkdtemp(prefix="sponl-array-")
        try:
            for table, rows in MINIMAL.items():
                with open(os.path.join(folder, ODD_NAMES[table]), "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
            data = loader.load(folder)
            self.assertEqual(data.alerts[0]["customer_name"], "Ada Lovelace")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_a_folder_without_the_core_tables_is_an_error(self):
        empty = tempfile.mkdtemp(prefix="sponl-empty-")
        try:
            with self.assertRaises(loader.DataError):
                loader.load(empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)

    def test_expected_row_counts(self):
        self.assertEqual(
            self.data.counts(),
            {
                "accounts": 86659,
                "alerts": 440,
                "customers": 72265,
                "hits": 819,
                "kyc_checks": 54488,
                "notes": 31895,
                "onboarding": 72265,
                "practice_labels": 50,
                "search_results": 16882,
            },
        )

    def test_every_table_came_from_its_own_file(self):
        for table, files in sorted(self.data.files.items()):
            self.assertEqual(len(files), 1, table)

    def test_the_screened_details_are_present_on_every_alert(self):
        for alert in self.data.alerts:
            self.assertTrue(alert["customer_name"], alert["alert_id"])
            self.assertIn(alert["entity_type"], ("Individual", "Company"))
            self.assertTrue(alert["screened_at"])
            for field in ("dob", "country", "city", "account_ref", "login_handle", "email"):
                self.assertIsInstance(alert[field], str, alert["alert_id"])

    def test_alerts_hit_ids_cover_every_hit_exactly_once(self):
        listed = [hid for a in self.data.alerts for hid in a["hit_ids"]]
        self.assertEqual(len(listed), len(self.data.hits))
        self.assertEqual(set(listed), {h["hit_id"] for h in self.data.hits})

    def test_no_link_dangles(self):
        d = self.data
        for alert in d.alerts:
            if alert["account_ref"]:
                self.assertIn(alert["account_ref"], d.accounts_by_id)
            if alert["login_handle"]:
                self.assertIn(alert["login_handle"], d.accounts_by_login)
            if alert["email"]:
                self.assertIn(alert["email"].lower(), d.customers_by_email)

    def test_every_alert_carries_exactly_one_link_or_none(self):
        for alert in self.data.alerts:
            links = [f for f in ("account_ref", "login_handle", "email") if alert[f]]
            self.assertLessEqual(len(links), 1, alert["alert_id"])

    def test_policy_and_variants_came_across(self):
        self.assertIn("Clear only on a contradiction", self.data.policy_text)
        variants = self.data.name_variants_raw
        self.assertEqual(len(variants["groups"]), 55)
        self.assertEqual(len(variants["company_legal_forms"]), 30)

    def test_reason_codes_in_the_labels_are_all_known(self):
        for label in self.data.practice_labels:
            for code in label["reason_codes"]:
                self.assertIn(code, model.REASON_CODES)
                self.assertEqual(model.REASON_CODES[code], label["decision"], code)

    def test_every_label_points_at_a_real_hit_and_alert(self):
        for label in self.data.practice_labels:
            self.assertIn(label["hit_id"], self.data.hit_by_id)
            self.assertIn(label["alert_id"], self.data.alert_by_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

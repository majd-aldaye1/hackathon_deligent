"""Step 1 acceptance: the loader reads the folder whatever it is called and however
multi-valued fields are encoded, and the CSV export and the JSONL folder agree.
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

CSV_FOLDER = os.path.join(ROOT, "dataset")
JSONL_FOLDER = os.path.join(ROOT, "dev")

MINIMAL = {
    "alerts": [
        {
            "alert_id": "A-1",
            "screened_at": "2026-11-06",
            "customer_name": "Ada Lovelace",
            "entity_type": "Individual",
            "dob": "1815-12-10",
            "country": "GB",
            "city": "",
            "account_ref": "ACC-1",
            "login_handle": "",
            "email": "",
            "hit_count": 1,
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
            "aliases": ["Augusta Ada King (AKA)"],
            "dobs": ["1815", "1816"],
            "countries": ["United Kingdom"],
            "addresses": ["London, United Kingdom [Residency]"],
            "categories": ["PEP"],
            "primary_category": "PEP",
            "profile_notes": "She was born in 1815.",
            "relationships": "Analytical Engine (AffiliatedCompany; SOE)",
            "deceased_date": None,
        }
    ],
    "customers": [
        {
            "record_id": "CUS-1",
            "entity_type": "Individual",
            "full_name": "Ada Lovelace",
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
        }
    ],
}

# Filenames that share no stem with our table names, to prove identification is by field.
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
    """A hand-written folder with list-valued fields and unhelpful filenames."""

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

    def test_list_fields_stay_lists(self):
        hit = self.data.hits[0]
        self.assertEqual(hit["dobs"], ["1815", "1816"])
        self.assertEqual(hit["countries"], ["United Kingdom"])
        self.assertEqual(self.data.alerts[0]["hit_ids"], ["H-1"])

    def test_semicolons_inside_single_values_survive(self):
        self.assertEqual(
            self.data.hits[0]["relationships"], "Analytical Engine (AffiliatedCompany; SOE)"
        )

    def test_missing_multi_fields_become_empty_lists(self):
        self.assertEqual(self.data.hits[0]["nationality"], [])

    def test_null_becomes_empty_string(self):
        self.assertEqual(self.data.hits[0]["deceased_date"], "")

    def test_numbers_become_strings(self):
        self.assertEqual(self.data.alerts[0]["hit_count"], "1")
        self.assertEqual(self.data.hits[0]["match_score"], "100")

    def test_label_field_aliases(self):
        label = self.data.practice_labels[0]
        self.assertEqual(label["reason_codes"], ["NAME_DOB_MATCH"])
        self.assertEqual(label["customer_record_ids"], ["CUS-1"])
        self.assertEqual(label["evidence"], ["CUS-1", "KYC-1"])
        self.assertEqual(label["reference_reason"], "Agrees on name and date of birth.")

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

    def test_a_folder_without_the_core_tables_is_an_error(self):
        empty = tempfile.mkdtemp(prefix="sponl-empty-")
        try:
            with self.assertRaises(loader.DataError):
                loader.load(empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


@unittest.skipUnless(
    os.path.isdir(CSV_FOLDER) and os.path.isdir(JSONL_FOLDER),
    "development data not present",
)
class TestDevelopmentSet(unittest.TestCase):
    """The CSV export and the generated dev/ folder must be the same data."""

    @classmethod
    def setUpClass(cls):
        cls.csv = loader.load(CSV_FOLDER)
        cls.jsonl = loader.load(JSONL_FOLDER)

    def test_row_counts_match(self):
        self.assertEqual(self.csv.counts(), self.jsonl.counts())

    def test_expected_row_counts(self):
        self.assertEqual(
            self.jsonl.counts(),
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

    def test_every_record_matches_field_for_field(self):
        for table in sorted(self.jsonl.tables):
            left, right = self.csv.tables[table], self.jsonl.tables[table]
            self.assertEqual(len(left), len(right), table)
            for a, b in zip(left, right):
                self.assertEqual(a, b, "%s %s" % (table, a))

    def test_alerts_hit_ids_cover_every_hit_exactly_once(self):
        listed = [hid for a in self.jsonl.alerts for hid in a["hit_ids"]]
        self.assertEqual(len(listed), len(self.jsonl.hits))
        self.assertEqual(set(listed), {h["hit_id"] for h in self.jsonl.hits})

    def test_no_link_dangles(self):
        d = self.jsonl
        for alert in d.alerts:
            if alert["account_ref"]:
                self.assertIn(alert["account_ref"], d.accounts_by_id)
            if alert["login_handle"]:
                self.assertIn(alert["login_handle"], d.accounts_by_login)
            if alert["email"]:
                self.assertIn(alert["email"].lower(), d.customers_by_email)

    def test_policy_and_variants_came_across(self):
        self.assertIn("Clear only on a contradiction", self.jsonl.policy_text)
        variants = self.jsonl.name_variants_raw
        self.assertEqual(len(variants["given_name_groups"]), 55)
        self.assertEqual(len(variants["company_legal_forms"]), 30)
        self.assertIn(["hassan", "hasan"], variants["given_name_groups"])

    def test_reason_codes_in_the_labels_are_all_known(self):
        for label in self.jsonl.practice_labels:
            for code in label["reason_codes"]:
                self.assertIn(code, model.REASON_CODES)
                self.assertEqual(model.REASON_CODES[code], label["decision"], code)


if __name__ == "__main__":
    unittest.main(verbosity=2)

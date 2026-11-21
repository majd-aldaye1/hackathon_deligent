"""Step 2: the normalisation in system/ agrees with the whole development folder.

tools/audit.py derives the same counts with its own small helpers; these assertions are
what stops the two from drifting apart, and what will fail loudly if the unseen set
brings a date shape or a country spelling we have not seen.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import countries, dates, loader, names  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestWholeFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)

    def test_every_date_string_parses(self):
        unparsed = []
        fields = [
            (self.data.customers, ["dob", "onboarded_at", "last_kyc_refresh"]),
            (self.data.kyc_checks, ["verified_dob", "checked_at"]),
            (self.data.alerts, ["dob", "screened_at"]),
            (self.data.accounts, ["opened_at"]),
            (self.data.onboarding, ["onboarded_at"]),
            (self.data.notes, ["created_at"]),
        ]
        total = 0
        for rows, keys in fields:
            for row in rows:
                for key in keys:
                    value = row.get(key, "")
                    if not value:
                        continue
                    total += 1
                    if dates.parse(value) is None:
                        unparsed.append((key, value))
        self.assertGreater(total, 100000)
        self.assertEqual(unparsed[:10], [], "%d date strings did not parse" % len(unparsed))

    def test_every_hit_dob_parses(self):
        unparsed = [v for h in self.data.hits for v in h["dobs"] if dates.parse(v) is None]
        self.assertEqual(unparsed, [])

    def test_every_deceased_date_parses(self):
        for hit in self.data.hits:
            if hit["deceased_date"]:
                self.assertIsNotNone(dates.parse(hit["deceased_date"]), hit["hit_id"])

    def test_every_bank_side_country_is_a_known_country(self):
        unmapped = set()
        for cust in self.data.customers:
            for field in ("nationality", "residence_country"):
                value = cust.get(field, "")
                if value and countries.key(value) not in countries.KNOWN_NAMES:
                    unmapped.add(value)
        for check in self.data.kyc_checks:
            value = check.get("document_country", "")
            if value and countries.key(value) not in countries.KNOWN_NAMES:
                unmapped.add(value)
        for alert in self.data.alerts:
            value = alert.get("country", "")
            if value and countries.key(value) not in countries.KNOWN_NAMES:
                unmapped.add(value)
        self.assertEqual(sorted(unmapped), [])

    def test_every_hit_side_country_is_a_known_country_or_not_a_country(self):
        unmapped = set()
        for hit in self.data.hits:
            values = list(hit["countries"]) + list(hit["nationality"]) + list(hit["citizenship"])
            values += list(hit["addresses"])
            if hit.get("place_of_birth"):
                values.append(hit["place_of_birth"])
            for value in values:
                key = countries.key_from_place(value)
                if key is not None and key not in countries.KNOWN_NAMES:
                    unmapped.add(value)
        self.assertEqual(sorted(unmapped), [])

    def test_international_and_europe_are_dropped(self):
        self.assertIsNone(countries.key_from_place("International"))
        self.assertIsNone(countries.key_from_place("Europe"))
        # and they really do occur in the data
        present = set()
        for hit in self.data.hits:
            present |= set(hit["countries"])
        self.assertIn("International", present)
        self.assertIn("Europe", present)

    def test_every_individual_hit_maps_to_a_query_that_exists(self):
        missing = [
            h["hit_id"]
            for h in self.data.hits
            if h["entity_type"] != "Company"
            and not any(k in self.data.search_by_query for k in names.query_keys(h["name"]))
        ]
        self.assertEqual(missing, [])

    def test_no_company_hit_has_search_results(self):
        # Worth knowing: a company can never gain a date of birth from a search result.
        present = [
            h["hit_id"]
            for h in self.data.hits
            if h["entity_type"] == "Company"
            and any(k in self.data.search_by_query for k in names.query_keys(h["name"]))
        ]
        self.assertEqual(present, [])

    def test_non_kyc_notes_name_at_most_one_country(self):
        multi = []
        with_country = 0
        for note in self.data.notes:
            if note["channel"] == "kyc":
                continue
            found = countries.mentioned_in(note["text"])
            if len(found) > 1:
                multi.append((note["note_id"], found))
            elif found:
                with_country += 1
        self.assertEqual(multi[:5], [])
        self.assertEqual(with_country, 3067)

    def test_only_single_part_names_are_unusable_for_a_name_decision(self):
        # 257 individual records have exactly one real part: either a placeholder
        # ("Pawel N/a N/a", "Sani 0000 0000") or a repeated word ("Lawal Lawal", which
        # counts once because "each distinct part counts once").  Nobody else is unusable.
        unusable = [
            c
            for c in self.data.customers
            if c["entity_type"] != "Company"
            and not names.usable_for_name_decision(
                [c.get("full_name", ""), c.get("preferred_name", ""), c.get("login_name", "")]
            )
        ]
        self.assertEqual(len(unusable), 257)
        for cust in unusable:
            best = max(
                len(names.parts(cust.get(f, "")))
                for f in ("full_name", "preferred_name", "login_name")
            )
            self.assertEqual(best, 1, cust["record_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

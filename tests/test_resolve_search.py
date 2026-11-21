"""Step 4: resolving an alert that carries no link, and the ambiguity verdict.

POLICY.md principle 2: "Without a link, find the records that fit what was screened."
Principle 3: "If more than one person fits an alert, decide the hit for each ... Either
way `customer_record_id` is `AMBIGUOUS`."
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import loader, persons, resolve  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def resolve_one(data, alert_row):
    screened = resolve.Screened(data.alert_by_id[alert_row["alert_id"]])
    return resolve.resolve_customer(data, persons.Persons(data), screened)


class TestSearch(unittest.TestCase):
    def test_the_blocking_index_finds_a_differently_spelled_record(self):
        row = fixture.alert(name="Muhammad Nadeem GHANI", dob="1968-02", country="United Kingdom")
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", "Mohammad Nadeem GHANI", dob="February 1968",
                                        nationality="British", residence_country="GB")],
        ) as data:
            self.assertEqual(resolve_one(data, row).record_ids, ["CUS-A"])

    def test_a_record_that_fails_one_screened_detail_is_not_found(self):
        row = fixture.alert(name="Ada Lovelace", dob="1815-12-10", country="GB")
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10",
                                        residence_country="Ireland", nationality="Irish")],
        ) as data:
            resolution = resolve_one(data, row)
            self.assertFalse(resolution.found)
            self.assertIsNone(resolution.customer_record_id())

    def test_the_screened_city_narrows_the_search(self):
        row = fixture.alert(name="Farah Damji", dob="1986-01-01", country="South Africa",
                            city="Vienna")
        with fixture.Folder(
            alerts=[row],
            customers=[
                fixture.customer("CUS-A", "Farah Damji", dob="1986-01-01",
                                 nationality="South African", residence_country="ZA",
                                 city="Vienna", address="189 High Street, Vienna"),
                fixture.customer("CUS-B", "Farah Damji", dob="1986-01-01",
                                 nationality="South African", residence_country="ZA",
                                 city="Stockholm", address="2 Main Street, Stockholm"),
            ],
        ) as data:
            self.assertEqual(resolve_one(data, row).record_ids, ["CUS-A"])

    def test_a_one_word_company_name_is_found(self):
        # POLICY principle 8: "every part of the shorter name matches" covers one-word names.
        row = fixture.alert(name="Pescanova", entity_type="Company", country="Spain")
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", "Pescanova, Sociedad Anonima",
                                        entity_type="Company", residence_country="ES")],
        ) as data:
            self.assertEqual(resolve_one(data, row).record_ids, ["CUS-A"])

    def test_a_linked_alert_does_not_fall_back_to_the_search(self):
        row = fixture.alert(name="Ada Lovelace", account_ref="ACC-1")
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", "Ada Lovelace"),
                       fixture.customer("CUS-B", "Ada Lovelace")],
            accounts=[fixture.account("ACC-1", "CUS-B")],
        ) as data:
            resolution = resolve_one(data, row)
            self.assertEqual(resolution.how, resolve.ACCOUNT_REF)
            self.assertEqual(resolution.record_ids, ["CUS-B"])


class TestEveryLinkIsFollowed(unittest.TestCase):
    """POLICY principle 2: "Follow whatever link the alert carries."  When an alert carries
    an account and an email that lead to different people, both are followed and the
    screened details pick between them, as they do between joint holders."""

    def _resolve(self, screened_name, name_a="Ada Lovelace", name_b="Ada Lovelace",
                 email="cus-b@example.test"):
        row = fixture.alert(name=screened_name, account_ref="ACC-1", email=email)
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", name_a), fixture.customer("CUS-B", name_b)],
            accounts=[fixture.account("ACC-1", "CUS-A")],
        ) as data:
            return resolve_one(data, row)

    def test_two_links_to_two_people_who_both_fit_keep_both(self):
        resolution = self._resolve("Ada Lovelace")
        self.assertEqual(resolution.record_ids, ["CUS-A", "CUS-B"])
        self.assertTrue(resolution.ambiguous)
        self.assertEqual(resolution.how, "account_ref+email")

    def test_the_screened_details_pick_the_one_that_fits(self):
        self.assertEqual(self._resolve("Grace Hopper", name_a="Ada Lovelace",
                                       name_b="Grace Hopper").record_ids, ["CUS-B"])
        self.assertEqual(self._resolve("Ada Lovelace", name_a="Ada Lovelace",
                                       name_b="Grace Hopper").record_ids, ["CUS-A"])

    def test_when_neither_fits_both_are_kept(self):
        resolution = self._resolve("Mary Shelley", name_a="Ada Lovelace", name_b="Grace Hopper")
        self.assertEqual(resolution.record_ids, ["CUS-A", "CUS-B"])

    def test_two_links_to_the_same_person_are_one_person(self):
        resolution = self._resolve("Ada Lovelace", email="cus-a@example.test")
        self.assertEqual(resolution.record_ids, ["CUS-A"])
        self.assertFalse(resolution.ambiguous)

    def test_a_single_link_reports_its_own_kind(self):
        row = fixture.alert(name="Ada Lovelace", email="cus-a@example.test")
        with fixture.Folder(alerts=[row],
                            customers=[fixture.customer("CUS-A", "Ada Lovelace")]) as data:
            self.assertEqual(resolve_one(data, row).how, resolve.EMAIL)


class TestResolutionVerdict(unittest.TestCase):
    def test_one_person_reports_a_record_id(self):
        row = fixture.alert(name="Ada Lovelace", dob="1815-12-10")
        with fixture.Folder(
            alerts=[row],
            customers=[fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10")],
        ) as data:
            resolution = resolve_one(data, row)
            self.assertTrue(resolution.found)
            self.assertFalse(resolution.ambiguous)
            self.assertEqual(resolution.customer_record_id(), "CUS-A")

    def test_one_person_with_several_records_reports_one_of_them(self):
        row = fixture.alert(name="Ada Lovelace", dob="1815-12-10")
        with fixture.Folder(
            alerts=[row],
            customers=[
                fixture.customer("CUS-Z", "Ada Lovelace", dob="1815-12-10", phone="+44 1"),
                fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10", phone="+44 1"),
            ],
        ) as data:
            resolution = resolve_one(data, row)
            self.assertFalse(resolution.ambiguous)
            self.assertEqual(resolution.customer_record_id(), "CUS-A")
            self.assertEqual(sorted(resolution.record_ids), ["CUS-A", "CUS-Z"])

    def test_two_persons_are_ambiguous(self):
        row = fixture.alert(name="Juan Gonzalez", dob="1970", country="Panama")
        with fixture.Folder(
            alerts=[row],
            customers=[
                fixture.customer("CUS-A", "Juan Gonzalez", dob="1970-03-01",
                                 residence_country="Panama"),
                fixture.customer("CUS-B", "Juan Gonzalez", dob="1970-09-09",
                                 residence_country="Panama"),
            ],
        ) as data:
            resolution = resolve_one(data, row)
            self.assertTrue(resolution.ambiguous)
            self.assertEqual(resolution.customer_record_id(), "AMBIGUOUS")
            self.assertEqual(len(resolution.persons), 2)

    def test_no_customer_reports_none(self):
        row = fixture.alert(name="Nobody At All", dob="1900-01-01")
        with fixture.Folder(alerts=[row], customers=[fixture.customer("CUS-A", "Ada Lovelace")]) as data:
            resolution = resolve_one(data, row)
            self.assertFalse(resolution.found)
            self.assertIsNone(resolution.customer_record_id())
            self.assertEqual(resolution.record_ids, [])


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.persons = persons.Persons(cls.data)
        cls.resolutions = {}
        for alert_row in cls.data.alerts:
            screened = resolve.Screened(alert_row)
            cls.resolutions[alert_row["alert_id"]] = resolve.resolve_customer(
                cls.data, cls.persons, screened
            )

    def test_every_alert_resolves_to_at_least_one_person(self):
        missing = [a for a, r in self.resolutions.items() if not r.found]
        self.assertEqual(missing, [])

    def test_how_each_alert_was_resolved(self):
        counts = {}
        for resolution in self.resolutions.values():
            counts[resolution.how] = counts.get(resolution.how, 0) + 1
        self.assertEqual(
            counts, {"account_ref": 170, "login_handle": 70, "email": 54, "search": 146}
        )

    def test_only_the_search_produces_ambiguity(self):
        ambiguous = [r for r in self.resolutions.values() if r.ambiguous]
        self.assertEqual(len(ambiguous), 27)
        for resolution in ambiguous:
            self.assertEqual(resolution.how, resolve.SEARCH)

    def test_every_practice_label_resolves_to_what_it_expects(self):
        for label in self.data.practice_labels:
            resolution = self.resolutions[label["alert_id"]]
            accepted = set(label["customer_record_ids"])
            if accepted == {"AMBIGUOUS"}:
                self.assertTrue(resolution.ambiguous, label["hit_id"])
                self.assertEqual(resolution.customer_record_id(), "AMBIGUOUS")
                continue
            # The label lists every record of the resolved person; we must find them all.
            self.assertTrue(
                accepted <= set(resolution.record_ids),
                "%s: %s not within %s" % (label["hit_id"], sorted(accepted),
                                          sorted(resolution.record_ids)),
            )
            self.assertIn(resolution.customer_record_id(), accepted, label["hit_id"])

    def test_the_two_ambiguous_labels_find_the_records_their_path_names(self):
        expected = {
            "H-6C7985": {"CUS-618916", "CUS-885413"},
            "H-CDEC83": {"CUS-037213", "CUS-565167", "CUS-892985"},
        }
        for label in self.data.practice_labels:
            if label["hit_id"] not in expected:
                continue
            resolution = self.resolutions[label["alert_id"]]
            self.assertEqual(set(resolution.record_ids), expected[label["hit_id"]])

    def test_resolution_is_deterministic(self):
        again = {}
        for alert_row in self.data.alerts:
            screened = resolve.Screened(alert_row)
            again[alert_row["alert_id"]] = resolve.resolve_customer(
                self.data, self.persons, screened
            )
        for alert_id, resolution in sorted(self.resolutions.items()):
            self.assertEqual(resolution.persons, again[alert_id].persons, alert_id)
            self.assertEqual(
                resolution.customer_record_id(), again[alert_id].customer_record_id(), alert_id
            )

    def test_resolving_every_alert_is_fast_enough(self):
        start = time.time()
        for alert_row in self.data.alerts:
            resolve.resolve_customer(self.data, self.persons, resolve.Screened(alert_row))
        self.assertLess(time.time() - start, 30.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

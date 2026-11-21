"""Step 3: following the alert's link to the customer, and the screened-detail fit test.

POLICY.md principle 2: "Follow whatever link the alert carries.  A link can lead to more
than one person; the screened details then pick between them."
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import loader, resolve  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def alert(**kwargs):
    row = {
        "alert_id": "A-1",
        "screened_at": "2026-11-06",
        "customer_name": "",
        "entity_type": "Individual",
        "dob": "",
        "country": "",
        "city": "",
        "account_ref": "",
        "login_handle": "",
        "email": "",
        "hit_ids": [],
    }
    row.update(kwargs)
    return row


def customer(**kwargs):
    row = {
        "record_id": "CUS-1",
        "entity_type": "Individual",
        "full_name": "",
        "preferred_name": "",
        "login_name": "",
        "dob": "",
        "nationality": "",
        "residence_country": "",
        "city": "",
        "address": "",
        "email": "",
        "phone": "",
    }
    row.update(kwargs)
    return row


class TestScreened(unittest.TestCase):
    def test_the_link_the_alert_carries(self):
        self.assertEqual(resolve.Screened(alert(account_ref="ACC-1")).link_kind, resolve.ACCOUNT_REF)
        self.assertEqual(resolve.Screened(alert(login_handle="h")).link_kind, resolve.LOGIN_HANDLE)
        self.assertEqual(resolve.Screened(alert(email="a@b")).link_kind, resolve.EMAIL)
        self.assertEqual(resolve.Screened(alert()).link_kind, resolve.NO_LINK)

    def test_account_ref_wins_when_more_than_one_field_is_set(self):
        screened = resolve.Screened(alert(account_ref="ACC-1", email="a@b"))
        self.assertEqual(screened.link_kind, resolve.ACCOUNT_REF)

    def test_every_link_field_is_kept(self):
        screened = resolve.Screened(alert(account_ref="ACC-1", login_handle="h", email="a@b"))
        self.assertEqual(screened.links, [(resolve.ACCOUNT_REF, "ACC-1"),
                                          (resolve.LOGIN_HANDLE, "h"), (resolve.EMAIL, "a@b")])
        self.assertEqual(resolve.Screened(alert()).links, [])

    def test_the_screened_details_are_parsed(self):
        screened = resolve.Screened(alert(customer_name="Ada", dob="1968-02", country="GB"))
        self.assertEqual(screened.dob.iso(), "1968-02")
        self.assertEqual(screened.country, "United Kingdom")

    def test_a_company_alert_knows_it_is_a_company(self):
        self.assertTrue(resolve.Screened(alert(entity_type="Company")).is_company)
        self.assertFalse(resolve.Screened(alert(entity_type="Individual")).is_company)


class TestCityPieces(unittest.TestCase):
    """The screened city field is not always one city."""

    def test_one_city(self):
        self.assertEqual(resolve._city_pieces("Munich"), ["munich"])

    def test_accents_are_folded(self):
        self.assertEqual(resolve._city_pieces("München"), ["munchen"])

    def test_a_city_and_a_state(self):
        # "GA" is dropped: two letters would match inside unrelated words.
        self.assertEqual(resolve._city_pieces("Savannah, GA"), ["savannah"])

    def test_alternatives_separated_by_a_slash(self):
        self.assertEqual(
            resolve._city_pieces("Cherry Hill, NJ / Wilmington, DE"),
            ["cherry hill", "wilmington"],
        )

    def test_a_country_in_the_city_field(self):
        self.assertEqual(resolve._city_pieces("United Kingdom"), ["united kingdom"])

    def test_empty(self):
        self.assertEqual(resolve._city_pieces(""), [])


class TestCheckFit(unittest.TestCase):
    """A criterion the alert is silent about stays None: it can neither support nor rule
    out a record."""

    def test_a_criterion_the_alert_does_not_screen_on_is_none(self):
        checks = resolve.check_fit(resolve.Screened(alert(customer_name="Ada Lovelace")),
                                   customer(full_name="Ada Lovelace"))
        self.assertTrue(checks[resolve.NAME])
        self.assertIsNone(checks[resolve.DOB])
        self.assertIsNone(checks[resolve.COUNTRY])
        self.assertIsNone(checks[resolve.CITY])

    def test_name_uses_full_preferred_or_login(self):
        screened = resolve.Screened(alert(customer_name="Jessica Jackson"))
        self.assertTrue(resolve.check_fit(screened, customer(full_name="Jessica Jackson"))[resolve.NAME])
        self.assertTrue(
            resolve.check_fit(screened, customer(preferred_name="Jessica Jackson"))[resolve.NAME]
        )
        self.assertTrue(
            resolve.check_fit(screened, customer(login_name="Jessica Jackson"))[resolve.NAME]
        )
        self.assertFalse(resolve.check_fit(screened, customer(full_name="Grace Hopper"))[resolve.NAME])

    def test_name_tolerates_the_typos_and_nicknames_policy_warns_about(self):
        screened = resolve.Screened(alert(customer_name="MD. SAEDUL ISLAM"))
        self.assertTrue(
            resolve.check_fit(screened, customer(full_name="Md. Saidul Islam"))[resolve.NAME]
        )

    def test_dob_must_be_equal_in_every_part_both_give(self):
        screened = resolve.Screened(alert(dob="1968-02"))
        self.assertTrue(resolve.check_fit(screened, customer(dob="February 1968"))[resolve.DOB])
        self.assertTrue(resolve.check_fit(screened, customer(dob="1968-02-17"))[resolve.DOB])
        self.assertFalse(resolve.check_fit(screened, customer(dob="1968-03-17"))[resolve.DOB])
        self.assertFalse(resolve.check_fit(screened, customer(dob="1967-02-17"))[resolve.DOB])

    def test_a_record_with_no_dob_cannot_match_a_screened_dob(self):
        screened = resolve.Screened(alert(dob="1968-02-17"))
        self.assertFalse(resolve.check_fit(screened, customer(dob=""))[resolve.DOB])

    def test_country_matches_residence_or_nationality(self):
        screened = resolve.Screened(alert(country="United Kingdom"))
        self.assertTrue(resolve.check_fit(screened, customer(residence_country="GB"))[resolve.COUNTRY])
        self.assertTrue(resolve.check_fit(screened, customer(nationality="British"))[resolve.COUNTRY])
        self.assertFalse(resolve.check_fit(screened, customer(residence_country="Ireland"))[resolve.COUNTRY])

    def test_city_matches_the_city_or_the_address(self):
        screened = resolve.Screened(alert(city="Munich"))
        self.assertTrue(resolve.check_fit(screened, customer(city="Munich"))[resolve.CITY])
        self.assertTrue(
            resolve.check_fit(screened, customer(address="201 Market Square, Munich"))[resolve.CITY]
        )
        self.assertFalse(resolve.check_fit(screened, customer(city="Madrid"))[resolve.CITY])

    def test_an_accented_city_matches_its_accented_record(self):
        screened = resolve.Screened(alert(city="München"))
        self.assertTrue(resolve.check_fit(screened, customer(city="München"))[resolve.CITY])

    def test_a_country_in_the_city_field_matches_a_record_that_says_so(self):
        # A-C21BD3 screens city "United Kingdom" and its record's city says the same.
        screened = resolve.Screened(alert(city="United Kingdom"))
        self.assertTrue(resolve.check_fit(screened, customer(city="United Kingdom"))[resolve.CITY])

    def test_entity_type_must_agree(self):
        screened = resolve.Screened(alert(entity_type="Company"))
        self.assertTrue(resolve.check_fit(screened, customer(entity_type="Company"))[resolve.ENTITY_TYPE])
        self.assertFalse(
            resolve.check_fit(screened, customer(entity_type="Individual"))[resolve.ENTITY_TYPE]
        )

    def test_fits_is_false_as_soon_as_one_screened_detail_disagrees(self):
        screened = resolve.Screened(alert(customer_name="Ada Lovelace", dob="1815-12-10", country="GB"))
        good = customer(full_name="Ada Lovelace", dob="10 December 1815", residence_country="GB")
        self.assertTrue(resolve.fits(screened, good))
        wrong_country = dict(good, residence_country="Ireland", nationality="")
        self.assertFalse(resolve.fits(screened, wrong_country))

    def test_fit_score_counts_the_details_that_match(self):
        screened = resolve.Screened(alert(customer_name="Ada Lovelace", dob="1815-12-10", country="GB"))
        good = customer(full_name="Ada Lovelace", dob="10 December 1815", residence_country="GB")
        # name, dob, country and entity type
        self.assertEqual(resolve.fit_score(screened, good), 4)


class TestChooseAmong(unittest.TestCase):
    """"A link can lead to more than one person; the screened details then pick between
    them." """

    def setUp(self):
        self.screened = resolve.Screened(alert(customer_name="Abdullahi Abubakar Sadiq",
                                               dob="1989-02-07"))
        self.right = customer(record_id="CUS-A", full_name="Abdullahi Abubakar Sadiq",
                              dob="1989-02-07")
        self.other = customer(record_id="CUS-B", full_name="Hannah Sadiq", dob="July 4, 1964")

    def test_one_record_is_taken_as_it_stands(self):
        # Nothing to pick between, so the link is not second-guessed even if the screened
        # name disagrees with the record.
        odd = customer(record_id="CUS-C", full_name="Someone Else", dob="1900-01-01")
        self.assertEqual([c["record_id"] for c in resolve.choose_among(self.screened, [odd])],
                         ["CUS-C"])

    def test_the_screened_details_pick_the_joint_holder(self):
        chosen = resolve.choose_among(self.screened, [self.other, self.right])
        self.assertEqual([c["record_id"] for c in chosen], ["CUS-A"])

    def test_when_none_of_them_fits_they_are_all_kept(self):
        a = customer(record_id="CUS-A", full_name="Nobody One", dob="1900-01-01")
        b = customer(record_id="CUS-B", full_name="Nobody Two", dob="1901-01-01")
        chosen = resolve.choose_among(self.screened, [a, b])
        self.assertEqual(sorted(c["record_id"] for c in chosen), ["CUS-A", "CUS-B"])

    def test_when_several_fit_equally_well_they_are_all_kept(self):
        screened = resolve.Screened(alert(customer_name="Ada Lovelace"))
        a = customer(record_id="CUS-A", full_name="Ada Lovelace")
        b = customer(record_id="CUS-B", full_name="Ada Lovelace")
        chosen = resolve.choose_among(screened, [a, b])
        self.assertEqual(sorted(c["record_id"] for c in chosen), ["CUS-A", "CUS-B"])

    def test_no_records_at_all(self):
        self.assertEqual(resolve.choose_among(self.screened, []), [])


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.screened = {a["alert_id"]: resolve.Screened(a) for a in cls.data.alerts}

    def test_link_kinds(self):
        kinds = {}
        for screened in self.screened.values():
            kinds[screened.link_kind] = kinds.get(screened.link_kind, 0) + 1
        self.assertEqual(
            kinds, {"account_ref": 170, "login_handle": 70, "email": 54, "none": 146}
        )

    def test_every_link_resolves_to_at_least_one_record(self):
        for screened in self.screened.values():
            if screened.link_kind == resolve.NO_LINK:
                continue
            self.assertTrue(resolve.linked_record_ids(self.data, screened), screened.alert_id)

    def test_joint_accounts_are_the_only_links_leading_to_two_records(self):
        two = [
            s.alert_id
            for s in self.screened.values()
            if len(resolve.linked_record_ids(self.data, s)) > 1
        ]
        self.assertEqual(len(two), 58)
        for alert_id in two:
            self.assertEqual(self.screened[alert_id].link_kind, resolve.ACCOUNT_REF)

    def test_the_screened_details_separate_every_joint_holder(self):
        for screened in self.screened.values():
            ids = resolve.linked_record_ids(self.data, screened)
            if len(ids) <= 1:
                continue
            fitting = [i for i in ids if resolve.fits(screened, self.data.customer_by_id[i])]
            self.assertEqual(len(fitting), 1, screened.alert_id)

    def test_every_linked_alert_resolves_to_exactly_one_record(self):
        for screened in self.screened.values():
            if screened.link_kind == resolve.NO_LINK:
                continue
            records, how = resolve.seed_records(self.data, screened)
            self.assertEqual(how, screened.link_kind)
            self.assertEqual(len(records), 1, screened.alert_id)

    def test_unlinked_alerts_find_nothing_yet(self):
        for screened in self.screened.values():
            if screened.link_kind != resolve.NO_LINK:
                continue
            self.assertEqual(resolve.seed_records(self.data, screened), ([], resolve.NO_LINK))

    def test_every_linked_practice_label_resolves_to_an_accepted_record(self):
        checked = 0
        for label in self.data.practice_labels:
            screened = self.screened[label["alert_id"]]
            if screened.link_kind == resolve.NO_LINK:
                continue
            checked += 1
            records, _ = resolve.seed_records(self.data, screened)
            found = {r["record_id"] for r in records}
            accepted = set(label["customer_record_ids"])
            if accepted == {"AMBIGUOUS"}:
                continue
            # Any record of the resolved person is accepted; step 4 adds the rest of them.
            self.assertTrue(found & accepted, "%s: %s vs %s" % (label["hit_id"], found, accepted))
        self.assertEqual(checked, 38)

    def test_resolution_is_stable_across_runs(self):
        first = [
            [r["record_id"] for r in resolve.seed_records(self.data, s)[0]]
            for s in (self.screened[a["alert_id"]] for a in self.data.alerts)
        ]
        second = [
            [r["record_id"] for r in resolve.seed_records(self.data, s)[0]]
            for s in (self.screened[a["alert_id"]] for a in self.data.alerts)
        ]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)

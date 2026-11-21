"""Step 6: deciding which search results are about the hit.

POLICY.md principle 5: "Most search results are about other people with the same name: a
result is about the hit only if it describes the same kind of listing in a country tied to
the hit. ... This form and the listing phrases above are worded the same in the unseen set."
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import loader, search_anchor as sa  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def result(snippet, title="Someone - report", result_id="SR-1"):
    return {"result_id": result_id, "query": "q", "title": title, "snippet": snippet,
            "source": "x.example"}


class TestListingPhrase(unittest.TestCase):
    def test_each_category_from_policy(self):
        self.assertEqual(sa.listing_phrase("Sanctions", []), "a sanctioned individual")
        self.assertEqual(sa.listing_phrase("PEP", []), "a politically exposed person")
        self.assertEqual(sa.listing_phrase("Enforcement", []), "the subject of enforcement action")
        self.assertEqual(sa.listing_phrase("Adverse Media", []), "named in adverse media")
        self.assertEqual(sa.listing_phrase("SOE", []), "a state-owned enterprise official")

    def test_any_other_category_gets_the_watchlist_phrase(self):
        self.assertEqual(sa.listing_phrase("Registration", []), "named on a watchlist")
        self.assertEqual(sa.listing_phrase("Other Segment", []), "named on a watchlist")

    def test_without_a_primary_category_the_first_one_decides(self):
        self.assertEqual(sa.listing_phrase("", ["Adverse Media", "PEP"]), "named in adverse media")
        self.assertEqual(sa.listing_phrase(None, ["PEP"]), "a politically exposed person")

    def test_no_category_at_all(self):
        self.assertEqual(sa.listing_phrase("", []), "named on a watchlist")

    def test_the_category_name_is_matched_case_insensitively(self):
        self.assertEqual(sa.listing_phrase("pep", []), "a politically exposed person")


class TestIsAbout(unittest.TestCase):
    PHRASE = "a politically exposed person"

    def test_the_phrase_and_a_country_of_the_hit(self):
        row = result("Nils Martin, 29, a politically exposed person from the United Kingdom.")
        self.assertTrue(sa.is_about(row, self.PHRASE, ["United Kingdom"]))

    def test_the_phrase_without_one_of_the_hits_countries(self):
        row = result("Nils Martin, 29, a politically exposed person from the United Kingdom.")
        self.assertFalse(sa.is_about(row, self.PHRASE, ["Nigeria"]))

    def test_a_country_without_the_phrase(self):
        row = result("Nils Martin, 29, a taxi driver in the United Kingdom.")
        self.assertFalse(sa.is_about(row, self.PHRASE, ["United Kingdom"]))

    def test_a_different_kind_of_listing_does_not_count(self):
        row = result("Nils Martin, 29, a sanctioned individual in the United Kingdom.")
        self.assertFalse(sa.is_about(row, self.PHRASE, ["United Kingdom"]))

    def test_a_nationality_adjective_names_the_country(self):
        row = result("Brazilian authorities named Anna Lindqvist, 30, a politically exposed person.")
        self.assertTrue(sa.is_about(row, self.PHRASE, ["Brazil"]))

    def test_the_phrase_may_sit_in_the_title(self):
        row = result("In Spain, 2016.", title="Someone - a politically exposed person")
        self.assertTrue(sa.is_about(row, self.PHRASE, ["Spain"]))

    def test_a_hit_with_no_country_can_never_be_anchored(self):
        row = result("Nils Martin, 29, a politically exposed person from the United Kingdom.")
        self.assertFalse(sa.is_about(row, self.PHRASE, []))


class TestBirthYears(unittest.TestCase):
    def test_the_example_from_policy(self):
        # "someone aged 45 in March 2019 was born in 1973 or 1974"
        self.assertEqual(sa.birth_years("aged 45 in March 2019"), [1973, 1974])

    def test_an_age_in_apposition(self):
        self.assertEqual(
            sa.birth_years("Published in December 2007, a list identified Elena Johansson, 51, "
                           "as the subject of enforcement action."),
            [1955, 1956],
        )

    def test_a_hyphenated_age(self):
        self.assertEqual(
            sa.birth_years("June 2024 documentation lists 27-year-old Samuel Hill."), [1996, 1997]
        )

    def test_a_bare_year_when_there_is_no_month(self):
        self.assertEqual(
            sa.birth_years("A 2006 news report profiled 29-year-old James Neal that July."),
            [1976, 1977],
        )

    def test_two_ages_yield_nothing(self):
        self.assertEqual(sa.birth_years("aged 45 and aged 50 in March 2019"), [])

    def test_two_years_yield_nothing(self):
        self.assertEqual(sa.birth_years("aged 45 in March 2019 and again in March 2020"), [])

    def test_no_age_yields_nothing(self):
        self.assertEqual(sa.birth_years("a politically exposed person in March 2019"), [])

    def test_thousands_separators_are_not_ages(self):
        for text in ["recovered INR 250,000 in March 2019", "paid USD 8,877,564 in March 2019",
                     "seized 1,310 grams in March 2019"]:
            self.assertEqual(sa.birth_years(text), [], text)

    def test_an_impossible_age_yields_nothing(self):
        self.assertEqual(sa.birth_years("the 300 in March 2019"), [])

    def test_empty(self):
        self.assertEqual(sa.birth_years(""), [])
        self.assertEqual(sa.birth_years(None), [])


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)

    def test_no_result_carries_two_listing_phrases(self):
        for row in self.data.search_results:
            text = row["title"] + " " + row["snippet"]
            self.assertLessEqual(sum(1 for p in sa.ALL_PHRASES if p in text), 1, row["result_id"])

    def test_most_results_carry_no_phrase_at_all(self):
        # 10 203 of 16 882 are namesake noise and can never anchor.
        without = sum(
            1
            for row in self.data.search_results
            if not any(p in row["title"] + " " + row["snippet"] for p in sa.ALL_PHRASES)
        )
        self.assertEqual(without, 10203)

    def test_every_anchorable_result_states_exactly_one_age(self):
        for row in self.data.search_results:
            text = row["title"] + " " + row["snippet"]
            if any(p in text for p in sa.ALL_PHRASES):
                self.assertEqual(len(sa._AGE.findall(row["snippet"])), 1, row["result_id"])

    def test_every_anchorable_result_yields_two_birth_years(self):
        for row in self.data.search_results:
            text = row["title"] + " " + row["snippet"]
            if any(p in text for p in sa.ALL_PHRASES):
                years = sa.birth_years(row["snippet"])
                self.assertEqual(len(years), 2, row["result_id"])
                self.assertEqual(years[1] - years[0], 1, row["result_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Step 2: country keys.

POLICY.md principle 6: "Codes and nationalities are countries; territories count as their
own country."  Principle 5: ""International" and "Europe" are not countries."
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import countries  # noqa: E402


class TestOneKeyPerCountry(unittest.TestCase):
    def test_code_name_and_nationality_are_one_key(self):
        for group in [
            ["GB", "GBR", "United Kingdom", "British", "UK"],
            ["US", "USA", "United States", "American"],
            ["DE", "Germany", "German"],
            ["NG", "Nigeria", "Nigerian"],
            ["BD", "Bangladesh", "Bangladeshi"],
            ["NL", "Netherlands", "Dutch", "Holland"],
            ["ZA", "South Africa", "South African"],
            ["SE", "Sweden", "Swedish"],
            ["IE", "Ireland", "Irish"],
            ["CI", "Cote D'Ivoire", "Côte d'Ivoire", "Ivory Coast", "Ivorian"],
        ]:
            keys = {countries.key(value) for value in group}
            self.assertEqual(len(keys), 1, "%s -> %s" % (group, keys))
            self.assertIn(list(keys)[0], countries.KNOWN_NAMES)

    def test_different_countries_are_different_keys(self):
        self.assertNotEqual(countries.key("Germany"), countries.key("Austria"))
        self.assertNotEqual(countries.key("Nigeria"), countries.key("Niger"))
        self.assertNotEqual(countries.key("South Korea"), countries.key("North Korea"))


class TestTerritories(unittest.TestCase):
    """"territories count as their own country" """

    def test_macao_is_not_china(self):
        self.assertNotEqual(
            countries.key("Macao Special Administrative Region of China"),
            countries.key("China"),
        )

    def test_hong_kong_is_not_china(self):
        self.assertNotEqual(countries.key("Hong Kong"), countries.key("China"))

    def test_puerto_rico_is_not_the_united_states(self):
        self.assertNotEqual(countries.key("Puerto Rico"), countries.key("United States"))

    def test_jersey_and_the_virgin_islands_are_their_own(self):
        self.assertNotEqual(countries.key("Jersey"), countries.key("United Kingdom"))
        self.assertNotEqual(
            countries.key("British Virgin Islands"), countries.key("United Kingdom")
        )

    def test_northern_mariana_islands_is_its_own(self):
        self.assertNotEqual(
            countries.key("Northern Mariana Islands"), countries.key("United States")
        )


class TestNotCountries(unittest.TestCase):
    def test_regions_are_not_countries(self):
        for value in ["International", "Europe", "Africa", "Asia", "Middle East", "worldwide"]:
            self.assertIsNone(countries.key(value), value)

    def test_placeholders_are_not_countries(self):
        for value in ["", None, "N/A", "NA", "unknown", "none", "---"]:
            self.assertIsNone(countries.key(value), repr(value))


class TestUnknownStringsEqualOnlyThemselves(unittest.TestCase):
    def test_an_unmapped_country_keeps_its_own_key(self):
        self.assertEqual(countries.key("Atlantis"), countries.key("ATLANTIS"))
        self.assertNotEqual(countries.key("Atlantis"), countries.key("Narnia"))

    def test_an_unmapped_country_is_not_a_known_one(self):
        self.assertNotIn(countries.key("Atlantis"), countries.KNOWN_NAMES)


class TestKeyFromPlace(unittest.TestCase):
    """Hit addresses and places of birth name their country last."""

    def test_an_address_with_a_tag(self):
        self.assertEqual(countries.key_from_place("Spain [Residency]"), "Spain")
        self.assertEqual(
            countries.key_from_place(
                "10 Fort William Place, Suite 302, St. John's, "
                "Newfoundland and Labrador, A1C 1K4, Canada [Business]"
            ),
            "Canada",
        )

    def test_a_place_of_birth(self):
        self.assertEqual(countries.key_from_place("Zamora, Zamora, Spain"), "Spain")
        self.assertEqual(
            countries.key_from_place("Fayette County, Atlanta, Georgia, United States"),
            "United States",
        )

    def test_a_whole_string_that_is_itself_a_country(self):
        self.assertEqual(
            countries.key_from_place("Macao Special Administrative Region of China"), "Macao"
        )

    def test_a_region_only_address_is_not_a_country(self):
        self.assertIsNone(countries.key_from_place("Europe"))
        self.assertIsNone(countries.key_from_place(""))


class TestMentionedIn(unittest.TestCase):
    """Free-text scanning, used for notes and search snippets."""

    def test_a_residence_note(self):
        self.assertEqual(
            countries.mentioned_in("The client maintained a job and home in Portugal between 2010 and 2011."),
            ["Portugal"],
        )

    def test_a_nationality_adjective(self):
        self.assertEqual(
            countries.mentioned_in("Brazilian authorities published a notice"), ["Brazil"]
        )

    def test_a_generic_support_note_names_no_country(self):
        self.assertEqual(
            countries.mentioned_in("Customer reported a lost card. Card frozen and a replacement ordered."),
            [],
        )

    def test_a_multi_word_country_is_not_split(self):
        # "United Kingdom" must not also be read as the United States.
        self.assertEqual(
            countries.mentioned_in("lived and worked in the United Kingdom from 2010 to 2016"),
            ["United Kingdom"],
        )
        self.assertEqual(countries.mentioned_in("a home in Costa Rica"), ["Costa Rica"])
        self.assertEqual(countries.mentioned_in("based in New Zealand"), ["New Zealand"])
        self.assertEqual(countries.mentioned_in("worked in South Korea"), ["South Korea"])
        self.assertEqual(countries.mentioned_in("resident of Puerto Rico"), ["Puerto Rico"])

    def test_two_countries_are_both_found(self):
        found = countries.mentioned_in("moved between the United States and Germany")
        self.assertEqual(sorted(found), ["Germany", "United States"])

    def test_two_letter_codes_are_not_looked_for_in_prose(self):
        # "as", "co" and "se" are ordinary words and company legal forms.
        self.assertEqual(countries.mentioned_in("the account was closed as agreed"), [])
        self.assertEqual(countries.mentioned_in("Blue Star Co filed late"), [])

    def test_a_country_inside_a_longer_word_is_not_a_mention(self):
        self.assertEqual(countries.mentioned_in("the chinaware was damaged"), [])

    def test_empty(self):
        self.assertEqual(countries.mentioned_in(""), [])
        self.assertEqual(countries.mentioned_in(None), [])


class TestDisplay(unittest.TestCase):
    def test_sorted_and_comma_separated(self):
        self.assertEqual(
            countries.display(["United States", "Bangladesh", "United States", None]),
            "Bangladesh, United States",
        )

    def test_empty(self):
        self.assertEqual(countries.display([]), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

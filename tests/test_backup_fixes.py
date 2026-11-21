"""Regression tests for the backup/dev-final fixes.

Each test pins one way the system used to fail *open* (turn something it could not read
into a clear) or miss a fact POLICY.md says to read.  None of these cases occurs in the
development set, which is why the practice labels could not catch them; the unseen set is
"worded differently", so they are tested here directly.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import countries, hit_facts, names, rules  # noqa: E402


class _Customer(object):
    def __init__(self, keys, entity_type="Individual"):
        self._keys = keys
        self.entity_type = entity_type

    def country_keys(self):
        return list(self._keys)


class _Hit(object):
    def __init__(self, keys, entity_type="Individual"):
        self.countries = list(keys)
        self.entity_type = entity_type


class NamesJoinedAndShortParts(unittest.TestCase):
    def test_written_apart_covers_both_parts(self):
        # principle 8: "Abdulsalam matches Abdul Salam, counting as one part that covers both"
        self.assertTrue(names.agree("Bluegrass Craft Coffee Roasters LLC", "Blue Grass, LLC", True))

    def test_short_part_cannot_be_absorbed_by_the_edit_allowance(self):
        # "logistics" is 2 edits from "st" + "logistics"; "ST" is under 4 letters, so it
        # must be identical, and the names share only one part.
        self.assertFalse(names.agree("Starling Logistics Ltd", "ST Logistics (UK) Ltd.", True))

    def test_equal_length_names_try_both_sides(self):
        self.assertTrue(names.agree("Almohammad Ali", "Al Mohammad"))

    def test_short_join_must_be_exact(self):
        self.assertFalse(names.agree("Elmohammed Xavier", "Al Mohammad"))


class CountriesFailClosed(unittest.TestCase):
    def test_unrecognised_place_is_marked_not_invented(self):
        k = countries.key_from_place("Ikeja, Lagos State")
        self.assertTrue(countries.is_unmapped(k))

    def test_location_mismatch_cannot_fire_on_an_unrecognised_place(self):
        cust = _Customer(["United Kingdom"])
        hit = _Hit([countries.key_from_place("Ikeja, Lagos State")])
        self.assertFalse(rules.countries_disjoint(cust, hit))

    def test_recognised_places_still_differ(self):
        self.assertTrue(rules.countries_disjoint(_Customer(["United Kingdom"]), _Hit(["Nigeria"])))

    def test_territory_wins_over_its_parent_state(self):
        self.assertEqual(countries.key_from_place("Hong Kong, China"), "Hong Kong")
        self.assertEqual(countries.key_from_place("Taiwan, Province of China"), "Taiwan")

    def test_official_long_forms(self):
        self.assertEqual(countries.key_from_place("Iran, Islamic Republic of"), "Iran")
        self.assertEqual(countries.key("Kingdom of Saudi Arabia"), "Saudi Arabia")
        self.assertEqual(countries.key("Republic of Turkey"), "Turkey")

    def test_codes_and_punctuation(self):
        self.assertEqual(countries.key("GBR"), "United Kingdom")
        self.assertEqual(countries.key("U.S.A."), "United States")
        self.assertEqual(countries.key("Côte d’Ivoire"), countries.key("Cote d'Ivoire"))

    def test_trailing_postcode_is_skipped(self):
        self.assertEqual(countries.key_from_place("12 Allen Avenue, Ikeja, Lagos, Nigeria, 100001"), "Nigeria")

    def test_small_states_are_known(self):
        for name in ("Saint Lucia", "Timor-Leste", "Antigua and Barbuda", "Holy See"):
            self.assertFalse(countries.is_unmapped(countries.key(name)), name)

    def test_regions_are_still_not_countries(self):
        self.assertIsNone(countries.key_from_place("International"))
        self.assertIsNone(countries.key_from_place("Europe"))


class EntityTypeUnknownIsNotADifference(unittest.TestCase):
    def test_unknown_kinds_do_not_fire(self):
        for kind in ("Vessel", "Aircraft", "Unknown", ""):
            self.assertIsNone(rules.entity_type_mismatch(_Customer([], "Individual"), _Hit([], kind), None), kind)

    def test_person_and_company_still_fire_through_the_kind_map(self):
        self.assertEqual(rules._kind("Organisation"), "company")
        self.assertEqual(rules._kind("Individual"), "person")


class AgesFromProfileNotes(unittest.TestCase):
    def ages(self, text):
        return [d.iso() for d in hit_facts.birth_dates_from_notes(text)]

    def test_quantities_and_ordinals_are_not_ages(self):
        self.assertEqual(self.ages("In March 2019, the scheme reached 50 million dollars in losses."), [])
        self.assertEqual(self.ages("By May 2018 the network was 12 strong."), [])
        self.assertEqual(self.ages("In January 2015 he was 3rd on the list of suspects."), [])
        self.assertEqual(self.ages("He was sentenced to 28 years in prison in April 2013."), [])

    def test_ages_the_old_cue_list_missed(self):
        self.assertEqual(self.ages("Mark E Phillips, at 24, was taken into custody in May 1999."), ["1974", "1975"])
        self.assertEqual(self.ages("In June 2006, when questioning by investigators took place, Tomasz Drozd was 27."),
                         ["1978", "1979"])
        self.assertEqual(self.ages("Regarding the June 2006 investigation, Tomasz Drozd was 27 at the time he was questioned."),
                         ["1978", "1979"])
        self.assertEqual(self.ages("Pere Punti reached 37 years of age by November 1981, the time he was charged."),
                         ["1943", "1944"])

    def test_labelled_date_of_birth(self):
        self.assertEqual(self.ages("Name: James, Richard DIN: 08A DOB: 6/20/1955 Height: 5 10"), ["1955-06-20"])
        # both numbers could be a month: keep only the year (it can agree, never contradict)
        self.assertEqual(self.ages("DOB: 05/06/1955"), ["1955"])


if __name__ == "__main__":
    unittest.main()

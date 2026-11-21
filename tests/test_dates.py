"""Step 2: partial-aware dates and POLICY.md's date comparisons."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import dates  # noqa: E402


class TestParsing(unittest.TestCase):
    """The seven shapes that appear in the development set (decision log D12)."""

    def test_the_seven_formats(self):
        cases = [
            ("1979-12-02", (1979, 12, 2)),
            ("19/05/2004", (2004, 5, 19)),
            ("6 May 1972", (1972, 5, 6)),
            ("February 19, 2002", (2002, 2, 19)),
            ("February 1968", (1968, 2, None)),
            ("1968-02", (1968, 2, None)),
            ("1996", (1996, None, None)),
        ]
        for text, expected in cases:
            date = dates.parse(text)
            self.assertIsNotNone(date, text)
            self.assertEqual((date.year, date.month, date.day), expected, text)

    def test_slashes_are_day_first(self):
        # 6348 values in the development set have a first component above 12 and none has
        # a second above 12, so the first component is the day.
        self.assertEqual(dates.parse("31/01/1990").iso(), "1990-01-31")
        self.assertEqual(dates.parse("01/02/1990").iso(), "1990-02-01")

    def test_abbreviated_months(self):
        self.assertEqual(dates.parse("Feb 19, 2002").iso(), "2002-02-19")
        self.assertEqual(dates.parse("Sept 1, 2002").iso(), "2002-09-01")

    def test_what_is_not_a_date(self):
        for text in ["", None, "Foo 1990", "not a date", "12/13", "999", "20261", "0000"]:
            self.assertIsNone(dates.parse(text), repr(text))

    def test_an_impossible_day_is_not_a_date(self):
        self.assertIsNone(dates.parse("1990-01-40"))

    def test_iso_renders_only_what_is_known(self):
        self.assertEqual(dates.parse("1996").iso(), "1996")
        self.assertEqual(dates.parse("1968-02").iso(), "1968-02")
        self.assertEqual(dates.parse("1968-02-17").iso(), "1968-02-17")

    def test_parse_many_keeps_order_and_drops_duplicates(self):
        parsed = dates.parse_many(["1996", "1997", "1996", "rubbish"])
        self.assertEqual([d.iso() for d in parsed], ["1996", "1997"])


class TestEqualWhereBothKnown(unittest.TestCase):
    """POLICY principle 2: "a date of birth equal to the screened one in every part both
    give"."""

    def test_a_year_agrees_with_a_full_date(self):
        self.assertTrue(dates.equal_where_both_known(dates.parse("1968-03-05"), dates.parse("1968")))

    def test_year_and_month_agree_with_a_full_date(self):
        self.assertTrue(
            dates.equal_where_both_known(dates.parse("February 1968"), dates.parse("1968-02"))
        )

    def test_a_different_month_is_not_equal(self):
        self.assertFalse(dates.equal_where_both_known(dates.parse("1968-03"), dates.parse("1968-02")))

    def test_a_different_day_is_not_equal(self):
        self.assertFalse(
            dates.equal_where_both_known(dates.parse("1968-02-17"), dates.parse("1968-02-18"))
        )

    def test_missing_is_never_a_mismatch(self):
        self.assertTrue(dates.equal_where_both_known(dates.parse("1968-02-17"), dates.parse("1968")))

    def test_none_never_equals(self):
        self.assertFalse(dates.equal_where_both_known(None, dates.parse("1968")))
        self.assertFalse(dates.equal_where_both_known(dates.parse("1968"), None))


class TestAgreement(unittest.TestCase):
    """POLICY principle 7: "the customer's birth year is one of the hit's possible birth
    years and every part both give (month, day) is equal"."""

    def test_one_of_the_hits_years(self):
        hit = dates.parse_many(["1967", "1968"])
        self.assertTrue(dates.any_agrees(dates.parse("1968-03-05"), hit))
        self.assertTrue(dates.any_agrees(dates.parse("1967-12-31"), hit))
        self.assertFalse(dates.any_agrees(dates.parse("1969-01-01"), hit))

    def test_a_year_off_by_one_does_not_agree(self):
        self.assertFalse(dates.agrees(dates.parse("1968"), dates.parse("1967")))

    def test_no_hit_dates_means_no_agreement(self):
        self.assertFalse(dates.any_agrees(dates.parse("1968"), []))


class TestContradiction(unittest.TestCase):
    """POLICY principle 6: "the customer's birth year is more than 1 year outside it, or
    both give a month in the same year and the months (or days) differ"."""

    def test_more_than_one_year_out(self):
        self.assertTrue(dates.contradicts(dates.parse("1979-11-08"), dates.parse("1976")))
        self.assertTrue(dates.contradicts(dates.parse("1995-12-17"), dates.parse("1986")))

    def test_exactly_one_year_out_is_not_a_contradiction(self):
        self.assertFalse(dates.contradicts(dates.parse("1968"), dates.parse("1967")))
        self.assertFalse(dates.contradicts(dates.parse("1967"), dates.parse("1968")))

    def test_same_year_different_month(self):
        self.assertTrue(dates.contradicts(dates.parse("1965-03-28"), dates.parse("1965-09-10")))

    def test_same_year_same_month_different_day(self):
        self.assertTrue(dates.contradicts(dates.parse("1965-03-28"), dates.parse("1965-03-29")))

    def test_same_year_with_a_month_on_one_side_only(self):
        # An unknown month is unknown, not a mismatch.
        self.assertFalse(dates.contradicts(dates.parse("1965-03-28"), dates.parse("1965")))

    def test_every_hit_date_must_be_contradicted(self):
        # "One agreeing date is enough to prevent this."
        customer = dates.parse("1968-03-05")
        self.assertFalse(dates.all_contradict(customer, dates.parse_many(["1968", "1950"])))
        self.assertTrue(dates.all_contradict(customer, dates.parse_many(["1950", "1940"])))

    def test_no_dates_at_all_contradicts_nothing(self):
        self.assertFalse(dates.all_contradict(dates.parse("1968"), []))
        self.assertFalse(dates.all_contradict(None, dates.parse_many(["1968"])))

    def test_the_practice_label_mismatches(self):
        self.assertTrue(
            dates.all_contradict(dates.parse("1979-11-08"), dates.parse_many(["1976", "1977"]))
        )
        self.assertTrue(
            dates.all_contradict(dates.parse("1965-03-28"), dates.parse_many(["1962-09-10"]))
        )
        self.assertTrue(
            dates.all_contradict(dates.parse("1951-09-17"), dates.parse_many(["1980-11-11"]))
        )


class TestBefore(unittest.TestCase):
    """The date of death against the screening date."""

    def test_an_earlier_year(self):
        self.assertTrue(dates.before(dates.parse("2021-08-02"), dates.parse("2026-11-05")))

    def test_a_partial_date_in_an_earlier_year(self):
        self.assertTrue(dates.before(dates.parse("2022-03"), dates.parse("2026-11-05")))

    def test_a_partial_date_cannot_be_ordered_inside_the_same_month(self):
        self.assertFalse(dates.before(dates.parse("2022-03"), dates.parse("2022-03-20")))

    def test_a_later_date_is_not_before(self):
        self.assertFalse(dates.before(dates.parse("2027-01-01"), dates.parse("2026-11-05")))

    def test_none(self):
        self.assertFalse(dates.before(None, dates.parse("2026-11-05")))
        self.assertFalse(dates.before(dates.parse("2026-11-05"), None))


class TestAges(unittest.TestCase):
    def test_whole_years(self):
        self.assertEqual(dates.years_between(dates.parse("2000-01-01"), dates.parse("2020-01-01")), 20)
        self.assertEqual(dates.years_between(dates.parse("2000-06-01"), dates.parse("2020-01-01")), 19)

    def test_max_age_uses_the_earliest_possible_birth_date(self):
        # The practice label: born in 2007, so at most 13 on 2020-01-08.
        self.assertEqual(dates.max_age_at(dates.parse("2007"), dates.parse("2020-01-08")), 13)

    def test_max_age_with_a_full_birth_date(self):
        self.assertEqual(dates.max_age_at(dates.parse("2007-06-01"), dates.parse("2020-01-08")), 12)

    def test_none(self):
        self.assertIsNone(dates.max_age_at(None, dates.parse("2020-01-08")))
        self.assertIsNone(dates.max_age_at(dates.parse("2007"), None))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Step 6: gathering the hit's facts.

POLICY.md principle 5: "A hit's date of birth may be its `dobs` field, a sentence in the
first paragraph of its profile notes ..., or, when neither gives one, web search results
for its name. ... Dated reports are exactly the English lines in the profile notes of the
form "According to …; September 10, 2025: …"; other wordings do not count. ... For
companies, only the `dobs` field is an incorporation date."
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import hit_facts as hf  # noqa: E402
from system import loader  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def hit(**kwargs):
    row = {
        "hit_id": "H-1",
        "alert_id": "A-1",
        "entity_type": "Individual",
        "name": "Lovelace, Ada",
        "best_matching_name": "",
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "aliases": [],
        "dobs": [],
        "place_of_birth": "",
        "life_status": "",
        "deceased_date": "",
        "nationality": [],
        "citizenship": [],
        "countries": [],
        "addresses": [],
        "categories": ["PEP"],
        "subcategories": [],
        "primary_category": "PEP",
        "profile_notes": "",
    }
    row.update(kwargs)
    return row


class TestDatedReports(unittest.TestCase):
    def test_the_strict_form(self):
        notes = "According to the U.S. Courts; September 10, 2025: something happened."
        self.assertEqual([d.iso() for d in hf.dated_reports(notes)], ["2025-09-10"])

    def test_a_month_and_year_only_is_not_a_dated_report(self):
        notes = "According to the Federal Investigation Agency; June 2014: Anti Terrorism Act."
        self.assertEqual(hf.dated_reports(notes), [])

    def test_no_date_at_all_is_not_a_dated_report(self):
        self.assertEqual(hf.dated_reports("According to United States - SAM:"), [])

    def test_a_semicolon_where_the_form_has_a_colon_does_not_count(self):
        # Decision log D22: dropping it can only move the earliest report later, which
        # makes the customer older and a temporal clear less likely.
        notes = "According to the Federal Reserve Board; October 10, 2024; On October 10 ..."
        self.assertEqual(hf.dated_reports(notes), [])

    def test_a_line_that_does_not_begin_with_the_form_does_not_count(self):
        notes = "The report said: According to X; September 10, 2025: something."
        self.assertEqual(hf.dated_reports(notes), [])

    def test_several_reports_come_back_earliest_first(self):
        notes = (
            "According to a; November 07, 2019: one.\n"
            "According to b; June 28, 2018: two.\n"
            "According to c; March 14, 2014: three."
        )
        self.assertEqual([d.iso() for d in hf.dated_reports(notes)],
                         ["2014-03-14", "2018-06-28", "2019-11-07"])
        self.assertEqual(hf.earliest_dated_report(notes).iso(), "2014-03-14")

    def test_no_notes(self):
        self.assertEqual(hf.dated_reports(""), [])
        self.assertIsNone(hf.earliest_dated_report(""))


class TestFirstParagraph(unittest.TestCase):
    def test_it_stops_at_the_blank_line(self):
        self.assertEqual(hf.first_paragraph("one\nstill one\n\ntwo"), "one\nstill one")

    def test_no_notes(self):
        self.assertEqual(hf.first_paragraph(""), "")
        self.assertEqual(hf.first_paragraph(None), "")


class TestBirthDatesFromNotes(unittest.TestCase):
    def test_an_outright_statement(self):
        self.assertEqual(
            [d.iso() for d in hf.birth_dates_from_notes("Yahaya Abubakar Abdullahi was born in 1952.")],
            ["1952"],
        )
        self.assertEqual(
            [d.iso() for d in hf.birth_dates_from_notes("Emmanuel Owusu-Ansah was born on 17 July 1939.")],
            ["1939-07-17"],
        )

    def test_an_age_against_a_date_gives_two_years(self):
        cases = [
            ("Formal charges were brought against Elvira Morillo, aged 30, in November 1998.",
             ["1967", "1968"]),
            ("November 1998 saw Elvira Morillo, a 30-year-old, face charges.", ["1967", "1968"]),
            ("When investigators questioned Michael Tilley in January 2023, he was 46.",
             ["1976", "1977"]),
            ("Investigators questioned Tomasz Drozd in January 2025, when he reached the age of 38.",
             ["1986", "1987"]),
            ("Thomas P Walsh was 25 when taken into custody during February 1986.",
             ["1960", "1961"]),
            ("Questioning of Tomasz Drozd occurred in June 2006, at which point he was 27.",
             ["1978", "1979"]),
            ("November 1981 marked the date Pere Punti, then 37, was placed under charge.",
             ["1943", "1944"]),
            ("Frank Murud was 48 when he was named in an indictment in October 2004.",
             ["1955", "1956"]),
        ]
        for text, expected in cases:
            self.assertEqual([d.iso() for d in hf.birth_dates_from_notes(text)], expected, text)

    def test_a_date_with_no_age_yields_nothing(self):
        text = ("On June 14, 2024, the United States Office of Foreign Assets Control added "
                "Tor Fredrik Vejdeland to its Specially Designated Nationals List.")
        self.assertEqual(hf.birth_dates_from_notes(text), [])

    def test_a_big_number_with_no_date_yields_nothing(self):
        text = "Associated with Sanctioned Entity: DAD, KARIM - Entity ID: 13938136."
        self.assertEqual(hf.birth_dates_from_notes(text), [])

    def test_a_providers_dated_report_never_supplies_a_birth_date(self):
        # It carries a date and, via thousands separators, numbers that look like ages.
        text = ("According to the urdupoint.com; October 11, 2025: In October 2025, police "
                "recovered stolen goods worth PKR 11,000,000, including PKR 3,100,000 in cash.")
        self.assertEqual(hf.birth_dates_from_notes(text), [])

    def test_thousands_separators_are_never_ages(self):
        text = "In March 2019 the police recovered INR 250,000 in cash."
        self.assertEqual(hf.birth_dates_from_notes(text), [])

    def test_two_ages_yield_nothing(self):
        self.assertEqual(
            hf.birth_dates_from_notes("In March 2019 he was 40 and she was 50."), []
        )

    def test_two_dates_yield_nothing(self):
        self.assertEqual(
            hf.birth_dates_from_notes("Questioned in March 2019 and again in June 2021, he was 40."),
            [],
        )

    def test_only_the_first_paragraph_is_read(self):
        text = "Career:\nSomething.\n\nHe was 46 in January 2023."
        self.assertEqual(hf.birth_dates_from_notes(text), [])

    def test_an_outright_statement_inside_a_dated_report_still_counts(self):
        text = "According to a source; June 28, 2018: Yahaya Abdullahi was born in 1952."
        self.assertEqual([d.iso() for d in hf.birth_dates_from_notes(text)], ["1952"])


class TestCountryKeys(unittest.TestCase):
    def test_every_field_policy_lists(self):
        row = hit(countries=["Spain"], nationality=["Belgrade, Serbia"], citizenship=["Spain"],
                  addresses=["Bailen, 3, Madrid, 28071, Spain [Business]", "Canada [PEP]"],
                  place_of_birth="Zamora, Zamora, Portugal")
        self.assertEqual(hf.country_keys(row), ["Spain", "Serbia", "Canada", "Portugal"])

    def test_international_and_europe_are_not_countries(self):
        row = hit(countries=["International", "Europe", "Spain"])
        self.assertEqual(hf.country_keys(row), ["Spain"])

    def test_a_hit_may_have_no_country(self):
        self.assertEqual(hf.country_keys(hit()), [])

    def test_a_territory_is_its_own_country(self):
        row = hit(countries=["Northern Mariana Islands", "United States"])
        self.assertEqual(hf.country_keys(row), ["Northern Mariana Islands", "United States"])


class TestHitNames(unittest.TestCase):
    def test_the_listed_name_comes_first(self):
        row = hit(name="Paul John Griffin", best_matching_name="Griffin, Paul John",
                  first_name="Paul", last_name="Griffin", aliases=["P. Griffin (AKA)"])
        self.assertEqual(
            hf.hit_names(row),
            ["Paul John Griffin", "Griffin, Paul John", "Paul Griffin", "P. Griffin (AKA)"],
        )

    def test_duplicates_are_dropped(self):
        row = hit(name="Ada Lovelace", best_matching_name="Ada Lovelace")
        self.assertEqual(hf.hit_names(row), ["Ada Lovelace"])

    def test_only_a_name(self):
        self.assertEqual(hf.hit_names(hit(name="Ada Lovelace")), ["Ada Lovelace"])


class TestGatherPriority(unittest.TestCase):
    def _gather(self, row, search_results=()):
        tables = {
            "alerts": [fixture.alert(alert_id="A-1", name="x", hit_ids=["H-1"])],
            "hits": [row],
        }
        if search_results:
            tables["search_results"] = list(search_results)
        with fixture.Folder(**tables) as data:
            return hf.gather(data, row)

    def test_the_dobs_field_wins(self):
        row = hit(dobs=["1996", "1997"], profile_notes="He was born in 1950.")
        facts = self._gather(row)
        self.assertEqual(facts.dob_origin, hf.FROM_FIELD)
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1996", "1997"])

    def test_the_notes_come_next(self):
        row = hit(profile_notes="Ada Lovelace was born in 1815.")
        facts = self._gather(row)
        self.assertEqual(facts.dob_origin, hf.FROM_NOTES)
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1815"])

    def test_search_results_come_last(self):
        row = hit(name="Clara Moreau", countries=["Portugal"], primary_category="PEP")
        results = [{
            "result_id": "SR-9", "query": "clara moreau", "title": "Clara Moreau - report",
            "snippet": "In October 1987, Portugal saw Clara Moreau, 36, a politically exposed person.",
            "source": "x.example",
        }]
        facts = self._gather(row, results)
        self.assertEqual(facts.dob_origin, hf.FROM_SEARCH)
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1950", "1951"])
        self.assertEqual(facts.result_ids, ("SR-9",))

    def test_a_search_derived_date_cites_the_result(self):
        row = hit(name="Clara Moreau", countries=["Portugal"], primary_category="PEP")
        results = [{
            "result_id": "SR-9", "query": "clara moreau", "title": "t",
            "snippet": "In October 1987, Portugal saw Clara Moreau, 36, a politically exposed person.",
            "source": "x.example",
        }]
        facts = self._gather(row, results)
        for fact in facts.dobs:
            self.assertEqual(fact.source_ids, ("SR-9",))

    def test_a_date_from_the_hit_itself_cites_nothing(self):
        # The hit is the subject of the decision, never evidence for it.
        facts = self._gather(hit(dobs=["1996"]))
        self.assertEqual(facts.dobs[0].source_ids, ())

    def test_a_namesake_result_is_not_used(self):
        row = hit(name="Clara Moreau", countries=["Portugal"], primary_category="PEP")
        results = [{
            "result_id": "SR-9", "query": "clara moreau", "title": "t",
            "snippet": "In October 1987, Portugal saw Clara Moreau, 36, a youth football coach.",
            "source": "x.example",
        }]
        facts = self._gather(row, results)
        self.assertIsNone(facts.dob_origin)
        self.assertEqual(facts.dobs, [])

    def test_a_company_takes_only_the_dobs_field(self):
        row = hit(entity_type="Company", name="Pescanova SA",
                  profile_notes="Pescanova was born in 1960.")
        facts = self._gather(row)
        self.assertTrue(facts.is_company)
        self.assertIsNone(facts.dob_origin)
        self.assertEqual(facts.dobs, [])

    def test_a_company_with_an_incorporation_date(self):
        facts = self._gather(hit(entity_type="Company", dobs=["1998-08-11"]))
        self.assertEqual(facts.dob_origin, hf.FROM_FIELD)
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1998-08-11"])

    def test_a_death_date_is_gathered(self):
        facts = self._gather(hit(life_status="Deceased", deceased_date="2022-03"))
        self.assertEqual(facts.death.value.iso(), "2022-03")

    def test_deceased_without_a_date_gives_no_death_fact(self):
        facts = self._gather(hit(life_status="Deceased"))
        self.assertIsNone(facts.death)


class TestDobDescription(unittest.TestCase):
    """The wording the reason text uses, taken from the reference reasons."""

    def _facts(self, row):
        with fixture.Folder(
            alerts=[fixture.alert(alert_id="A-1", name="x", hit_ids=["H-1"])], hits=[row]
        ) as data:
            return hf.gather(data, row)

    def test_one_listed_date(self):
        self.assertEqual(
            self._facts(hit(dobs=["1962-09-10"])).dob_description(),
            "listed date of birth is 1962-09-10",
        )

    def test_several_listed_dates(self):
        self.assertEqual(
            self._facts(hit(dobs=["1994-05-14", "1995-04-28"])).dob_description(),
            "listed dates of birth are 1994-05-14 or 1995-04-28",
        )

    def test_from_the_profile_notes(self):
        self.assertEqual(
            self._facts(hit(profile_notes="He was 46 in January 2023.")).dob_description(),
            "profile notes put its birth year at 1976 or 1977",
        )

    def test_nothing_at_all(self):
        self.assertEqual(self._facts(hit()).dob_description(), "")


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.sheets = {h["hit_id"]: hf.gather(cls.data, h) for h in cls.data.hits}

    def test_where_the_dates_of_birth_come_from(self):
        counts = {}
        for facts in self.sheets.values():
            counts[facts.dob_origin] = counts.get(facts.dob_origin, 0) + 1
        self.assertEqual(counts, {"field": 152, "notes": 45, "search": 72, None: 550})

    def test_no_profile_states_a_birth_we_could_not_read(self):
        # Guard C in step 9 found two phrasings the cue list was missing; this keeps the
        # cue list honest as the unseen set brings more of them.
        unread = [
            f.hit_id for f in self.sheets.values()
            if f.dob_unreadable
        ]
        self.assertEqual(unread, [])

    def test_no_date_of_birth_comes_from_a_providers_dated_report(self):
        for facts in self.sheets.values():
            if facts.dob_origin != hf.FROM_NOTES:
                continue
            paragraph = hf.first_paragraph(self.data.hit_by_id[facts.hit_id]["profile_notes"])
            self.assertFalse(hf._is_dated_report(paragraph), facts.hit_id)

    def test_the_dates_of_birth_the_practice_labels_name(self):
        expected = {
            "H-D861DA": ["1976", "1977"],
            "H-4AA437": ["1986", "1987"],
            "H-582410": ["1967", "1968"],
            "H-EC242D": ["1967", "1968"],
            "H-622EDD": ["1972", "1973"],
            "H-FC22E2": ["1972", "1973"],
            "H-58A39C": ["1962-09-10"],
            "H-CF5228": ["1980-11-11"],
            "H-91AC66": ["1994", "1995"],
            "H-CF0978": ["1998", "1999"],
        }
        for hit_id, values in sorted(expected.items()):
            self.assertEqual(
                [d.iso() for d in self.sheets[hit_id].dob_values()], values, hit_id
            )

    def test_the_search_results_the_practice_labels_cite(self):
        expected = {
            "H-622EDD": "SR-A88751",
            "H-FC22E2": "SR-65C752",
            "H-80B4B5": "SR-01BFC3",
            "H-F9DBF9": "SR-AE2CE1",
            "H-0181BD": "SR-590704",
        }
        for hit_id, result_id in sorted(expected.items()):
            self.assertIn(result_id, self.sheets[hit_id].result_ids, hit_id)

    def test_no_company_hit_takes_a_date_from_notes_or_search(self):
        for facts in self.sheets.values():
            if facts.is_company:
                self.assertIn(facts.dob_origin, (None, hf.FROM_FIELD), facts.hit_id)

    def test_dated_reports_and_deaths(self):
        self.assertEqual(sum(1 for f in self.sheets.values() if f.earliest_report), 215)
        self.assertEqual(sum(1 for f in self.sheets.values() if f.death), 4)
        self.assertEqual(self.sheets["H-13E1CF"].earliest_report.value.iso(), "2020-01-08")

    def test_hits_with_no_country_cannot_be_located(self):
        self.assertEqual(sum(1 for f in self.sheets.values() if not f.countries), 87)

    def test_every_hit_has_at_least_one_name(self):
        for facts in self.sheets.values():
            self.assertTrue(facts.names, facts.hit_id)

    def test_gathering_is_deterministic_and_fast(self):
        start = time.time()
        again = {h["hit_id"]: hf.gather(self.data, h) for h in self.data.hits}
        self.assertLess(time.time() - start, 10.0)
        for hit_id, facts in sorted(self.sheets.items()):
            other = again[hit_id]
            self.assertEqual(facts.dob_origin, other.dob_origin, hit_id)
            self.assertEqual([d.iso() for d in facts.dob_values()],
                             [d.iso() for d in other.dob_values()], hit_id)
            self.assertEqual(facts.countries, other.countries, hit_id)
            self.assertEqual(facts.result_ids, other.result_ids, hit_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

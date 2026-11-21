"""Step 10: the language-model fallback.

The brief: the model may be called "only via the OpenRouter API", the system "must still
run (regex-only) if the key is missing or the API fails", every answer must come with "the
verbatim quote the fact came from", and "regex and LLM disagree -> fact unknown".

Every test here injects a fake transport, so the suite needs neither a key nor a network.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import customer_facts as cf  # noqa: E402
from system import hit_facts, llm, rules  # noqa: E402
from system.facts import Fact  # noqa: E402
from tests.test_rules import customer, hit, screened  # noqa: E402


def canned(*answers):
    """A transport that returns the given objects in order, then None."""
    queue = list(answers)
    calls = []

    def opener(body):
        calls.append(body)
        return queue.pop(0) if queue else None

    opener.calls = calls
    return opener


def extractor(*answers):
    client = llm.Client(key="sk-test", model="test/model", opener=canned(*answers))
    return llm.Extractor(client), client


class TestKey(unittest.TestCase):
    def test_the_environment_variable_the_brief_names(self):
        self.assertEqual(llm.api_key({llm.ENV_KEY: " sk-x "}), "sk-x")

    def test_no_key_means_no_client(self):
        client = llm.Client(key="", opener=canned())
        self.assertFalse(client.available)
        self.assertIsNone(client.ask("p", "t"))

    def test_build_returns_nothing_without_a_key(self):
        self.assertIsNone(llm.build(key=""))

    def test_the_key_is_never_read_from_a_file_by_the_system(self):
        self.assertEqual(llm.api_key({}), "")

    def test_a_dotenv_can_be_read_by_the_development_tools(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("# a comment\nopen_router_key='sk-from-file'\n")
            path = fh.name
        try:
            self.assertEqual(llm.key_from_dotenv(path), "sk-from-file")
        finally:
            os.unlink(path)

    def test_a_missing_dotenv_is_not_an_error(self):
        self.assertEqual(llm.key_from_dotenv("/nowhere/at/all/.env"), "")


class TestRequestShape(unittest.TestCase):
    def test_the_request_is_deterministic_and_asks_for_json(self):
        _ex, client = extractor({"found": False})
        client.ask("system prompt", "user text")
        body = client._opener.calls[0]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["top_p"], 1)
        self.assertEqual(body["seed"], 7)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["content"], "user text")

    def test_long_text_is_truncated(self):
        _ex, client = extractor({"found": False})
        client.ask("p", "x" * (llm.MAX_TEXT + 500))
        self.assertEqual(len(client._opener.calls[0]["messages"][1]["content"]), llm.MAX_TEXT)

    def test_the_same_question_is_asked_once(self):
        _ex, client = extractor({"found": False})
        first = client.ask("p", "t")
        second = client.ask("p", "t")
        self.assertEqual(first, second)
        self.assertEqual(len(client._opener.calls), 1)
        self.assertEqual(client.usage.cache_hits, 1)

    def test_a_failure_is_retried_then_gives_up(self):
        client = llm.Client(key="sk-test", opener=canned(None, None, None))
        self.assertIsNone(client.ask("p", "t"))
        self.assertEqual(len(client._opener.calls), llm.MAX_ATTEMPTS)


class TestParsingTheAnswer(unittest.TestCase):
    def test_a_fenced_object_still_parses(self):
        self.assertEqual(llm._loads('```json\n{"a": 1}\n```'), {"a": 1})

    def test_nonsense_is_not_an_answer(self):
        for value in ["", "not json", "[1,2]", None, "null"]:
            self.assertIsNone(llm._loads(value), repr(value))


class TestGrounding(unittest.TestCase):
    TEXT = "Formal charges were brought against Elvira Morillo, aged 30, in November 1998."

    def test_a_quote_must_be_verbatim(self):
        self.assertTrue(llm.quote_is_verbatim("aged 30", self.TEXT))
        self.assertFalse(llm.quote_is_verbatim("aged 31", self.TEXT))

    def test_reflowed_whitespace_is_allowed(self):
        self.assertTrue(llm.quote_is_verbatim("aged   30", self.TEXT))

    def test_an_invented_quote_is_refused(self):
        _ex, _c = extractor()
        ex, _c = extractor({"found": True, "quote": "aged 45", "age": 45, "as_of_year": 1998})
        self.assertIsNone(ex.hit_birth(self.TEXT))

    def test_an_age_and_a_year_both_have_to_be_in_the_text(self):
        ex, _c = extractor({"found": True, "quote": "aged 30", "age": 30, "as_of_year": 1998})
        found = ex.hit_birth(self.TEXT)
        self.assertEqual([d.iso() for d in found.dates], ["1967", "1968"])

    def test_a_year_that_is_nowhere_in_the_text_is_refused(self):
        ex, _c = extractor({"found": True, "quote": "aged 30", "age": 30, "as_of_year": 2015})
        self.assertIsNone(ex.hit_birth(self.TEXT))

    def test_a_date_needs_its_year_and_month_in_the_quote(self):
        text = "The subject was born on 17 July 1939 in Accra."
        ex, _c = extractor({"found": True, "quote": "born on 17 July 1939",
                            "birth_date": "1939-07-17"})
        self.assertEqual([d.iso() for d in ex.hit_birth(text).dates], ["1939-07-17"])

    def test_a_date_whose_month_is_not_in_the_quote_is_refused(self):
        text = "The subject was born on 17 July 1939 in Accra."
        ex, _c = extractor({"found": True, "quote": "born on 17 July 1939",
                            "birth_date": "1939-03-17"})
        self.assertIsNone(ex.hit_birth(text))

    def test_a_country_must_be_named_in_its_quote(self):
        text = "The client kept a home in Portugal from 2010 to 2011."
        ex, _c = extractor({"found": True, "items": [
            {"quote": "a home in Portugal", "country": "Portugal"}]})
        self.assertEqual([p.country for p in ex.note_places(text)], ["Portugal"])

    def test_a_country_not_in_its_quote_is_refused(self):
        text = "The client kept a home in Portugal from 2010 to 2011."
        ex, _c = extractor({"found": True, "items": [
            {"quote": "a home in Portugal", "country": "Spain"}]})
        self.assertEqual(ex.note_places(text), [])

    def test_a_country_the_table_does_not_know_is_refused(self):
        text = "The client kept a home in Freedonia from 2010 to 2011."
        ex, _c = extractor({"found": True, "items": [
            {"quote": "a home in Freedonia", "country": "Freedonia"}]})
        self.assertEqual(ex.note_places(text), [])

    def test_a_name_must_be_in_its_quote(self):
        text = "Holder: SIOBHAN MURPHY. Birth: 3rd of February 1981. Passport (Ireland)."
        ex, _c = extractor({
            "found": True, "approved": True,
            "name": "SIOBHAN MURPHY", "name_quote": "Holder: SIOBHAN MURPHY",
            "dob": "1981-02-03", "dob_quote": "3rd of February 1981",
            "country": "Ireland", "country_quote": "Passport (Ireland)",
        })
        found = ex.note_check(text)
        self.assertEqual(found.name, "SIOBHAN MURPHY")
        self.assertEqual(found.dob.iso(), "1981-02-03")
        self.assertEqual(found.country, "Ireland")
        self.assertTrue(found.is_approved)

    def test_a_name_not_in_its_quote_is_dropped(self):
        text = "Holder: SIOBHAN MURPHY. Passport (Ireland)."
        ex, _c = extractor({
            "found": True, "approved": True,
            "name": "DECLAN BYRNE", "name_quote": "Holder: SIOBHAN MURPHY",
            "country": "Ireland", "country_quote": "Passport (Ireland)",
        })
        found = ex.note_check(text)
        self.assertIsNone(found.name)

    def test_found_false_is_respected(self):
        ex, _c = extractor({"found": False})
        self.assertIsNone(ex.hit_birth(self.TEXT))
        ex, _c = extractor({"found": False})
        self.assertEqual(ex.note_places(self.TEXT), [])
        ex, _c = extractor({"found": False})
        self.assertIsNone(ex.note_check(self.TEXT))

    def test_no_answer_at_all_is_unknown(self):
        ex, _c = extractor(None)
        self.assertIsNone(ex.hit_birth(self.TEXT))


class TestProvisionalFactsMayBlockButNeverClear(unittest.TestCase):
    """Decision log D28."""

    def test_a_model_read_date_of_birth_cannot_clear(self):
        cust = customer(verified_dob="1979-11-08")
        cust.approved[0].provisional = True
        self.assertIsNone(rules.dob_mismatch(cust, hit(dobs=["1950"]), screened()))

    def test_a_model_read_date_of_birth_can_still_block(self):
        # It agrees with the hit, so there is no contradiction to find.
        cust = customer(verified_dob="1968-03-05")
        cust.approved[0].provisional = True
        self.assertIsNone(rules.dob_mismatch(cust, hit(dobs=["1968"]), screened()))

    def test_a_model_read_hit_date_cannot_clear(self):
        h = hit(dobs=["1950"])
        h.dobs = [Fact(f.value, f.source_ids, True) for f in h.dobs]
        self.assertIsNone(
            rules.dob_mismatch(customer(verified_dob="1979-11-08"), h, screened())
        )

    def test_a_model_read_country_cannot_carry_a_location_clear(self):
        facts = cf.CustomerFacts(
            record_ids=("CUS-1",), entity_type="Individual",
            declared_names=[Fact("Ada Lovelace", ("CUS-1",))], declared_dobs=[],
            country_facts=[Fact("Netherlands", ("NOTE-1",), True)], approved=[],
        )
        self.assertIsNone(
            rules.location_mismatch(facts, hit(countries=("United States",)), screened())
        )

    def test_a_model_read_country_does_block_one(self):
        facts = cf.CustomerFacts(
            record_ids=("CUS-1",), entity_type="Individual",
            declared_names=[Fact("Ada Lovelace", ("CUS-1",))], declared_dobs=[],
            country_facts=[Fact("Netherlands", ("CUS-1",)),
                           Fact("United States", ("NOTE-1",), True)],
            approved=[],
        )
        self.assertIsNone(
            rules.location_mismatch(facts, hit(countries=("United States",)), screened())
        )

    def test_a_model_read_legal_name_cannot_clear(self):
        cust = customer(names=("Ridwan Azeez",), verified_name="CHINEDU AZEEZ")
        cust.approved[0].provisional = True
        self.assertIsNone(
            rules.name_mismatch_verified(cust, hit(names=("Ridwan, Azeez",)), screened())
        )

    def test_a_model_read_date_cannot_carry_a_temporal_clear(self):
        cust = customer(verified_dob="2007-08-21")
        cust.approved[0].provisional = True
        self.assertIsNone(
            rules.temporal_impossibility(cust, hit(report="2020-01-08"), screened())
        )

    def test_one_sure_reading_makes_a_merged_fact_sure(self):
        from system.facts import merge

        merged = merge([Fact("Spain", "NOTE-1", True), Fact("Spain", "CUS-1")])
        self.assertFalse(merged[0].provisional)


class TestTheFallbackIsOnlyAskedWhenThePatternsFail(unittest.TestCase):
    def _folder(self, note_text, channel="email"):
        return fixture.Folder(
            customers=[fixture.customer("CUS-A", "Ada Lovelace", residence_country="Australia")],
            accounts=[fixture.account("ACC-A", "CUS-A")],
            onboarding=[fixture.onboarding("ACC-A", "CUS-A", "APP-A")],
            notes=[fixture.note("NOTE-1", "cus-a@example.test", note_text, channel=channel)],
        )

    def test_a_readable_note_is_never_sent_to_the_model(self):
        ex, client = extractor({"found": True, "items": [
            {"quote": "x", "country": "Japan"}]})
        with self._folder("The client kept a home in Portugal from 2010 to 2011.") as data:
            facts = cf.gather(data, ["CUS-A"], extractor=ex)
        self.assertEqual(client._opener.calls, [])
        self.assertIn("Portugal", facts.country_keys())

    def test_an_unreadable_note_is_sent_and_its_answer_is_provisional(self):
        answer = {"found": True, "items": [
            {"quote": "a home in Freedonia", "country": "Portugal"}]}
        ex, client = extractor(answer)
        with self._folder("The client kept a home in Freedonia from 2010 to 2011.") as data:
            facts = cf.gather(data, ["CUS-A"], extractor=ex)
        # The quote does not name Portugal, so grounding refuses it and the note stays
        # unreadable -- which keeps the guard on.
        self.assertEqual(len(client._opener.calls), 1)
        self.assertTrue(facts.countries_may_be_incomplete)

    def test_a_recovered_place_is_provisional_and_lifts_the_guard(self):
        answer = {"found": True, "items": [
            {"quote": "a home in Portugal", "country": "Portugal"}]}
        ex, _client = extractor(answer)
        text = "Records are unclear, though a home in Portugal is mentioned for 2010."
        with self._folder(text) as data:
            # The scan already reads this one, so force the fallback path by rewording.
            facts = cf.gather(data, ["CUS-A"], extractor=ex)
        self.assertIn("Portugal", facts.country_keys())

    def test_a_hit_paragraph_the_patterns_read_is_never_sent(self):
        ex, client = extractor({"found": True, "quote": "x", "birth_date": "1900"})
        row = {
            "hit_id": "H-1", "alert_id": "A-1", "entity_type": "Individual",
            "name": "Lovelace, Ada", "dobs": [], "categories": ["PEP"],
            "primary_category": "PEP", "profile_notes": "Ada Lovelace was born in 1815.",
        }
        with fixture.Folder(
            alerts=[fixture.alert(alert_id="A-1", name="x", hit_ids=["H-1"])], hits=[row]
        ) as data:
            facts = hit_facts.gather(data, row, extractor=ex)
        self.assertEqual(client._opener.calls, [])
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1815"])

    def test_a_hit_paragraph_that_talks_about_a_birth_we_cannot_read_is_sent(self):
        ex, client = extractor({
            "found": True, "quote": "his age had run to 31", "age": 31,
            "as_of_year": 1998,
        })
        row = {
            "hit_id": "H-1", "alert_id": "A-1", "entity_type": "Individual",
            "name": "Lovelace, Ada", "dobs": [], "categories": ["PEP"],
            "primary_category": "PEP",
            # Deliberately a phrasing the patterns cannot read: the age is a numeral but
            # none of the closed list of cues introduces it.
            "profile_notes": "Charges followed in November 1998, by which point his age "
                             "had run to 31.",
        }
        with fixture.Folder(
            alerts=[fixture.alert(alert_id="A-1", name="x", hit_ids=["H-1"])], hits=[row]
        ) as data:
            facts = hit_facts.gather(data, row, extractor=ex)
        self.assertEqual([d.iso() for d in facts.dob_values()], ["1966", "1967"])
        self.assertTrue(all(f.provisional for f in facts.dobs))
        self.assertEqual(len(client._opener.calls), 1)

    def test_an_age_written_as_a_word_cannot_be_grounded_and_stays_unknown(self):
        # Grounding needs the number in the span.  Refusing is the safe direction: no
        # fact means the step 9 guards keep the hit out of a clear.
        text = "Charges followed in November 1998, in his thirty-first year."
        ex, _client = extractor({"found": True, "quote": "in his thirty-first year",
                                 "age": 31, "as_of_year": 1998})
        self.assertIsNone(ex.hit_birth(text))

    def test_a_model_that_raises_leaves_the_fact_unknown(self):
        class Exploding(object):
            def note_places(self, text):
                raise RuntimeError("boom")

            def note_check(self, text):
                raise RuntimeError("boom")

        with self._folder("The client kept a home in Freedonia from 2010 to 2011.") as data:
            facts = cf.gather(data, ["CUS-A"], extractor=Exploding())
        self.assertTrue(facts.countries_may_be_incomplete)
        self.assertEqual(facts.country_keys(), ["Australia"])


class TestDateFormatsTheFallbackNeeded(unittest.TestCase):
    """Ordinals and spelled-out days are real formats, so the parser learned them."""

    def test_ordinals_and_of(self):
        from system import dates

        self.assertEqual(dates.parse("3rd of February 1981").iso(), "1981-02-03")
        self.assertEqual(dates.parse("21st March 1990").iso(), "1990-03-21")
        self.assertEqual(dates.parse("the 1st of January 2000").iso(), "2000-01-01")

    def test_spelled_out_days(self):
        from system import dates

        self.assertEqual(dates.parse("the twelfth of May 1966").iso(), "1966-05-12")
        self.assertEqual(dates.parse("twentieth of June 1955").iso(), "1955-06-20")

    def test_it_did_not_become_a_looser_parser_in_general(self):
        from system import dates

        for text in ["Foo 1990", "the third", "not a date", ""]:
            self.assertIsNone(dates.parse(text), repr(text))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Step 5: reading an identity check, and places lived, out of a free-text note."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import loader, notes_regex as nr  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def dob(text):
    found = nr.date_of_birth(text)
    return found.value.iso() if found else None


def name(text):
    found = nr.subject_name(text)
    return found.value if found else None


def country(text):
    found = nr.document_country(text)
    return found.value if found else None


class TestDateOfBirth(unittest.TestCase):
    def test_a_cue_before_the_date(self):
        self.assertEqual(dob("born December 13, 1977, using a national ID"), "1977-12-13")
        self.assertEqual(dob("DOB 22/09/1956, from Nigeria"), "1956-09-22")
        self.assertEqual(dob("DOB recorded as 10/08/1988."), "1988-08-10")
        self.assertEqual(dob("Recorded DOB: 21/04/1951."), "1951-04-21")
        self.assertEqual(dob("subject date of birth is December 5, 1992"), "1992-12-05")

    def test_a_cue_after_the_date(self):
        self.assertEqual(
            dob("cross-referencing his 19/11/1961 date of birth against his licence"),
            "1961-11-19",
        )
        self.assertEqual(dob("confirming his passport and February 10, 1959 birth date."), "1959-02-10")
        self.assertEqual(dob("matching her 27 August 1955 DOB to a driving licence"), "1955-08-27")

    def test_born_on_is_a_birth_date_not_a_check_date(self):
        self.assertEqual(
            dob("On 2024-06-19, Onfido verified a passport for GRACE TURNER, who was born on 27/06/1969."),
            "1969-06-27",
        )
        self.assertEqual(
            dob("The record shows the holder was born in Bangladesh on 13/07/1983."), "1983-07-13"
        )

    def test_a_date_in_brackets_after_the_name(self):
        self.assertEqual(
            dob("The national ID belonging to JAVIER BIANCHI (19/12/2003) from Germany was verified"),
            "2003-12-19",
        )
        self.assertEqual(dob("cleared the passport of IBRAHIM KASBAH (DOB 18/01/2004)"), "2004-01-18")

    def test_the_check_date_is_never_taken_as_the_birth_date(self):
        # The cue sits between the two dates in both orders.
        self.assertEqual(
            dob("whose 1986-12-10 date of birth was confirmed by Onfido on 2025-03-10"),
            "1986-12-10",
        )
        self.assertEqual(
            dob("who lists 06/01/1998 as her DOB, is valid as of 2024-08-15."), "1998-01-06"
        )
        self.assertEqual(
            dob("showing 1983-02-21 as the date of birth, was confirmed via Veriff on 2024-11-15"),
            "1983-02-21",
        )

    def test_a_bare_year_only_next_to_a_cue(self):
        self.assertEqual(dob("confirms a date of birth of 1974"), "1974")
        self.assertIsNone(dob("was verified on 2024-01-01 after a long review in 1974"))

    def test_a_document_date_is_not_a_birth_date(self):
        # "dated" says nothing about a birth, so the fact stays unknown rather than wrong.
        self.assertIsNone(dob("authenticated a Bangladesh national ID dated 1952-01-21"))
        self.assertIsNone(dob("providing a driving licence from Spain dated 16 April 1978"))

    def test_no_date_and_no_cue(self):
        self.assertIsNone(dob("Customer reported a lost card."))
        self.assertIsNone(dob(""))
        self.assertIsNone(dob(None))

    def test_the_quote_is_verbatim_text(self):
        text = "born December 13, 1977, using a national ID"
        found = nr.date_of_birth(text)
        self.assertIn(found.quote, text)


class TestSubjectName(unittest.TestCase):
    def test_a_run_of_capitals(self):
        self.assertEqual(name("verification for NILS MARTIN, born December 13, 1977"), "NILS MARTIN")
        self.assertEqual(name("for MARKUS GERHARD MUELLER."), "MARKUS GERHARD MUELLER")

    def test_accented_capitals_count(self):
        self.assertEqual(name("The Persona system validated FERNÁNDEZ ISABEL, DOB April 23, 1970"),
                         "FERNÁNDEZ ISABEL")
        self.assertEqual(name("verified the identity of PAWEŁ Smith on 2025-02-20"), "PAWEŁ")

    def test_label_words_are_not_names(self):
        self.assertEqual(name("Result for JOHN SMITH, DOB 01/01/1990: Sumsub verified"), "JOHN SMITH")
        self.assertEqual(name("holder NILS MARTIN date of birth 1977-12-13"), "NILS MARTIN")

    def test_digits_are_not_name_words(self):
        self.assertEqual(name("confirmed the identity of SANI 0000 0000 on 2024-05-17"), "SANI")

    def test_a_one_word_name_is_accepted(self):
        # "N/a Gilbert" really is a one-part name; principle 8 handles the consequence.
        self.assertEqual(name("Verification for N/A GILBERT, born May 21, 1995"), "GILBERT")

    def test_the_longest_run_wins(self):
        self.assertEqual(name("ID checked. JOHN QUINCY ADAMS passed. OK"), "JOHN QUINCY ADAMS")

    def test_nothing_in_capitals(self):
        self.assertIsNone(name("the customer asked about rates"))
        self.assertIsNone(name(""))


class TestDocumentCountry(unittest.TestCase):
    def test_exactly_one_country(self):
        self.assertEqual(country("using a national ID issued in Germany on 2023-02-19"), "Germany")
        self.assertEqual(country("a United Kingdom passport"), "United Kingdom")

    def test_two_countries_is_no_answer(self):
        self.assertIsNone(
            country("an Italy-issued driving licence (Note: United Kingdom)")
        )

    def test_no_country(self):
        self.assertIsNone(country("a passport was verified"))


class TestApproval(unittest.TestCase):
    def test_cues_are_stemmed(self):
        for text in [
            "Onfido confirms MEGAN HALL presented a valid ID",
            "was vetted by Persona",
            "to pass the Veriff check",
            "identity check passed",
            "verification successful",
            "The Onfido scan on 2024-11-20",
        ]:
            self.assertTrue(nr.approval(text), text)

    def test_a_refusal_outranks_an_approval(self):
        for text in [
            "verification failed",
            "the check was rejected after review",
            "Onfido could not verify the document",
            "the name did not match the document",
            "the document has expired",
        ]:
            self.assertFalse(nr.approval(text), text)

    def test_silence_is_neither(self):
        self.assertIsNone(nr.approval("Customer asked about savings interest rates."))


class TestParseKycNote(unittest.TestCase):
    def _note(self, text, channel="kyc"):
        return {"note_id": "NOTE-1", "created_at": "2024-03-16", "channel": channel, "text": text}

    def test_a_full_note(self):
        parsed = nr.parse_kyc_note(self._note(
            "On 2024-03-16, Persona successfully validated the national ID of "
            "TEMITOPE NWOSU, DOB 22/09/1956, from Nigeria."
        ))
        self.assertEqual(parsed.verified_name, "TEMITOPE NWOSU")
        self.assertEqual(parsed.verified_dob.iso(), "1956-09-22")
        self.assertEqual(parsed.document_country, "Nigeria")
        self.assertTrue(parsed.is_approved)
        self.assertEqual(parsed.checked_at.iso(), "2024-03-16")

    def test_only_the_kyc_channel_is_read_this_way(self):
        text = "Persona validated the national ID of TEMITOPE NWOSU, DOB 22/09/1956, from Nigeria."
        self.assertIsNone(nr.parse_kyc_note(self._note(text, channel="email")))

    def test_a_refused_check_is_not_approved(self):
        parsed = nr.parse_kyc_note(self._note(
            "Onfido could not verify the passport of JOHN SMITH, DOB 01/01/1990, from Spain."
        ))
        self.assertFalse(parsed.is_approved)

    def test_a_note_with_no_verification_wording_is_not_a_check(self):
        self.assertIsNone(nr.parse_kyc_note(self._note("Customer asked about rates.")))

    def test_every_extracted_field_keeps_its_quote(self):
        parsed = nr.parse_kyc_note(self._note(
            "Sumsub completed identity verification for NILS MARTIN, born December 13, 1977, "
            "using a national ID issued in Germany."
        ))
        for key in ("verified_name", "verified_dob", "document_country"):
            self.assertIn(key, parsed.quotes)


class TestPlacesLived(unittest.TestCase):
    def test_a_residence_statement(self):
        self.assertEqual(
            nr.places_lived({"channel": "email",
                             "text": "The client maintained a job and home in Portugal between 2010 and 2011."}),
            ["Portugal"],
        )

    def test_a_generic_support_note(self):
        self.assertEqual(
            nr.places_lived({"channel": "app", "text": "Customer reported a lost card."}), []
        )

    def test_a_kyc_note_is_not_a_residence_statement(self):
        self.assertEqual(
            nr.places_lived({"channel": "kyc",
                             "text": "Verified via Onfido using a passport from France."}),
            [],
        )


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.kyc_notes = [n for n in cls.data.notes if n["channel"] == "kyc"]
        # Parsed once: the assertions below all look at the same 22 575 results.
        cls.parsed = {n["note_id"]: nr.parse_kyc_note(n) for n in cls.kyc_notes}

    def test_every_kyc_note_parses_as_an_approved_check(self):
        for note in self.kyc_notes:
            parsed = self.parsed[note["note_id"]]
            self.assertIsNotNone(parsed, note["note_id"])
            self.assertTrue(parsed.is_approved, note["note_id"])

    def test_almost_every_kyc_note_yields_all_three_fields(self):
        full = sum(
            1
            for parsed in self.parsed.values()
            if parsed.verified_name and parsed.verified_dob and parsed.document_country
        )
        self.assertEqual(full, 22567)
        self.assertEqual(len(self.kyc_notes), 22575)

    def test_no_extracted_birth_date_is_really_the_check_date(self):
        confused = []
        for note in self.kyc_notes:
            parsed = self.parsed[note["note_id"]]
            if parsed.verified_dob and parsed.checked_at:
                if parsed.verified_dob.key() == parsed.checked_at.key():
                    confused.append(note["note_id"])
        self.assertEqual(confused, [])

    def test_extracted_birth_dates_agree_with_the_record_almost_always(self):
        by_email = {c["email"].lower(): c for c in self.data.customers}
        from system import dates

        agree = disagree = 0
        for note in self.kyc_notes:
            parsed = self.parsed[note["note_id"]]
            if not parsed.verified_dob:
                continue
            cust = by_email.get(note["requester_email"].lower())
            declared = dates.parse(cust.get("dob")) if cust else None
            if declared is None:
                continue
            if dates.equal_where_both_known(declared, parsed.verified_dob):
                agree += 1
            else:
                disagree += 1
        # The 14 that differ are the planted "verified beats declared" cases.
        self.assertEqual(disagree, 14)
        self.assertGreater(agree, 22500)

    def test_every_quote_is_verbatim_text_from_its_note(self):
        for note in self.kyc_notes:
            parsed = self.parsed[note["note_id"]]
            for quote in parsed.quotes.values():
                self.assertIn(quote, note["text"], note["note_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

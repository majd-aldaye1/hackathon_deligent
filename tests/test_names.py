"""Step 2: POLICY.md principle 8, clause by clause.

Every assertion below quotes the sentence of principle 8 it is testing, so a change to
the matcher has to argue with POLICY rather than with a practice label.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import names  # noqa: E402
from system.name_variants import DEFAULT, from_raw  # noqa: E402


class TestParts(unittest.TestCase):
    """"Compare name parts ignoring case, accents, punctuation and anything in brackets;
    single letters are initials, not parts, and each distinct part counts once." """

    def test_case_accents_and_punctuation_are_ignored(self):
        self.assertEqual(names.parts("Jérôme KERVIEL"), ["jerome", "kerviel"])
        self.assertEqual(names.parts("Bernard, Samuel"), ["bernard", "samuel"])
        self.assertEqual(names.parts("Md. Saidul Islam"), ["md", "saidul", "islam"])

    def test_brackets_are_dropped(self):
        self.assertEqual(names.parts("Elvira Velazco Morillo (AKA)"),
                         ["elvira", "velazco", "morillo"])
        self.assertEqual(names.parts("Port Authority (PANYNJ)"), ["port", "authority"])

    def test_single_letters_are_initials_not_parts(self):
        self.assertEqual(names.parts("Paul P Griffin"), ["paul", "griffin"])
        self.assertEqual(names.parts("Carl E. Andersen"), ["carl", "andersen"])
        self.assertEqual(names.parts("Mitchell, Charlee D."), ["mitchell", "charlee"])

    def test_each_distinct_part_counts_once(self):
        self.assertEqual(names.parts("Smith John Smith"), ["smith", "john"])

    def test_placeholders_are_not_parts(self):
        self.assertEqual(names.parts("Paweł N/a N/a"), ["pawel"])
        self.assertEqual(names.parts("Sani 0000 0000"), ["sani"])
        self.assertEqual(names.parts("Martin Xxx Xxx"), ["martin"])
        self.assertEqual(names.parts("0000 Barajas"), ["barajas"])

    def test_company_legal_forms_are_not_parts(self):
        self.assertEqual(names.parts("Blue Star LLC", company=True), ["blue", "star"])
        self.assertEqual(names.parts("Lafarge SA", company=True), ["lafarge"])
        self.assertEqual(names.parts("Bianchi Group GmbH", company=True), ["bianchi", "group"])
        self.assertEqual(names.parts("N26 Bank SE", company=True), ["n26", "bank"])

    def test_legal_forms_are_kept_for_individuals(self):
        # "For companies, the legal forms ... are not name parts" — only for companies.
        self.assertIn("co", names.parts("Mary Co", company=False))


class TestPartsMatch(unittest.TestCase):
    """"Two parts match when they are identical, are listed together in
    name_variants.json, ... or differ by at most 1 edit for parts of 4 to 6 letters and 2
    for longer ones ... parts shorter than 4 letters must be identical; the shorter part's
    length decides." """

    def test_identical(self):
        self.assertTrue(names.parts_match("islam", "islam"))

    def test_variant_group(self):
        self.assertTrue(names.parts_match("mohammad", "muhammad"))
        self.assertTrue(names.parts_match("hassan", "hasan"))
        self.assertTrue(names.parts_match("joe", "joseph"))  # short, but same group
        self.assertTrue(names.parts_match("tunde", "babatunde"))
        self.assertFalse(names.parts_match("john", "jonathan"))  # not a listed group

    def test_short_parts_must_be_identical(self):
        self.assertTrue(names.parts_match("md", "md"))
        self.assertFalse(names.parts_match("md", "mr"))
        self.assertFalse(names.parts_match("ali", "all"))  # 3 letters: no edits allowed

    def test_four_to_six_letters_allow_one_edit(self):
        self.assertTrue(names.parts_match("saidul", "saedul"))  # 6 letters, 1 edit
        self.assertTrue(names.parts_match("mark", "marc"))
        self.assertFalse(names.parts_match("velasco", "velxxxo"))  # 3 edits, shorter is 7

    def test_six_letters_refuse_two_edits(self):
        self.assertFalse(names.parts_match("nadeem", "nadxxm"))

    def test_seven_or_more_letters_allow_two_edits(self):
        self.assertTrue(names.parts_match("kowalski", "kowalsky"))
        self.assertTrue(names.parts_match("abdullahi", "abdullah"))
        self.assertFalse(names.parts_match("abdullahi", "abdxxxahi"))

    def test_the_shorter_part_decides_the_threshold(self):
        # "ali" is 3 letters, so no edits are allowed even though the other part is long.
        self.assertFalse(names.parts_match("ali", "alistair"))
        # 4 letters against 5: threshold 1.
        self.assertTrue(names.parts_match("khan", "khans"))

    def test_a_swap_is_two_edits(self):
        self.assertFalse(names.parts_match("daniel", "danile"))  # 6 letters, 2 edits
        self.assertTrue(names.parts_match("kowalski", "kowalsik"))  # 8 letters, 2 allowed


class TestJoinedOrApart(unittest.TestCase):
    """"are written together or apart (Abdulsalam matches Abdul Salam, counting as one
    part that covers both)" """

    def test_the_example_from_policy(self):
        self.assertTrue(names.agree("Abdulsalam", "Abdul Salam"))
        self.assertTrue(names.agree("Abdul Salam", "Abdulsalam"))

    def test_it_counts_as_one_part_covering_both(self):
        agree, matched = names.compare_parts(["abdulsalam"], ["abdul", "salam"])
        self.assertTrue(agree)
        self.assertEqual(matched, 1)

    def test_with_a_second_part_it_reaches_two_matches(self):
        agree, matched = names.compare("Abdulsalam Khan", "Abdul Salam Khan")[:2]
        self.assertTrue(agree)
        self.assertEqual(matched, 2)

    def test_a_joined_part_is_not_reused(self):
        # "salam" cannot match both halves of "abdulsalam" twice over.
        agree, matched = names.compare_parts(["abdulsalam"], ["abdul", "salam", "abdul"])
        self.assertEqual(matched, 1)


class TestAgreement(unittest.TestCase):
    """"Names agree when at least two parts match, or every part of the shorter name
    matches." """

    def test_two_matching_parts_agree(self):
        self.assertTrue(names.agree("Mohammad Nadeem Ghani", "Muhammad Nadeem GHANI"))
        self.assertTrue(names.agree("Carl E. ANDERSEN", "Carl J Andersen"))

    def test_one_matching_part_out_of_several_does_not_agree(self):
        self.assertFalse(names.agree("CHINEDU AZEEZ", "Ridwan, Azeez"))
        self.assertFalse(names.agree("SARAH JOHNSON", "Johnson, James Jacob"))
        self.assertFalse(names.agree("Jonathan Reyes Whitfield", "John Whitfield"))
        self.assertFalse(names.agree("MARKUS GERHARD MUELLER", "Mark Mueller"))
        self.assertFalse(names.agree("SAMUEL DIAZ", "Ramirez Diaz, Jesus Amable"))
        self.assertFalse(names.agree("Joseph gallardo", "Gallardo, Bartolo Diego"))

    def test_every_part_of_the_shorter_name_matching_agrees(self):
        # A single-part name whose only part matches: POLICY says "a hit's single-part
        # alias can still agree with a customer's name".
        self.assertTrue(names.agree("Smith", "John Smith"))
        self.assertTrue(names.agree("Pescanova, Sociedad Anonima", "Pescanova, Inc", company=True))

    def test_nothing_in_common_does_not_agree(self):
        self.assertFalse(names.agree("Ada Lovelace", "Grace Hopper"))

    def test_an_empty_name_never_agrees(self):
        self.assertFalse(names.agree("", "John Smith"))
        self.assertFalse(names.agree("John Smith", ""))
        self.assertFalse(names.agree("N/a 0000", "John Smith"))


class TestAliasesAndSides(unittest.TestCase):
    """"Aliases count as names, nicknames included." """

    def test_any_pair_agreeing_is_enough(self):
        agree, left, right = names.any_agree(
            ["Aleksandar Raskovic"], ["Rakovic, Aleksandar", "Aleksandar Raskovic (AKA)"]
        )
        self.assertTrue(agree)
        self.assertEqual(left, "Aleksandar Raskovic")

    def test_it_names_the_pair_that_agreed(self):
        agree, left, right = names.any_agree(
            ["Robert Smith"], ["Nobody Here", "Bob Smith"]
        )
        self.assertTrue(agree)
        self.assertEqual(right, "Bob Smith")

    def test_nicknames_count(self):
        self.assertTrue(names.agree("Robert Smith", "Bob Smith"))
        self.assertTrue(names.agree("William Jones", "Bill Jones"))

    def test_no_pair_agreeing(self):
        agree, left, right = names.any_agree(["Ada Lovelace"], ["Grace Hopper"])
        self.assertFalse(agree)
        self.assertIsNone(left)
        self.assertIsNone(right)

    def test_empty_sides(self):
        self.assertEqual(names.any_agree([], ["x"])[0], False)
        self.assertEqual(names.any_agree(["x"], [])[0], False)


class TestUsableForNameDecision(unittest.TestCase):
    """"an individual customer whose names have fewer than two real parts can be neither
    confirmed nor cleared on name" """

    def test_fewer_than_two_real_parts_is_unusable(self):
        self.assertFalse(names.usable_for_name_decision(["Paweł N/a N/a"]))
        self.assertFalse(names.usable_for_name_decision(["Brooks N/a"]))
        self.assertFalse(names.usable_for_name_decision(["0000 0000"]))
        self.assertFalse(names.usable_for_name_decision([""]))

    def test_two_real_parts_is_usable(self):
        self.assertTrue(names.usable_for_name_decision(["Ada Lovelace"]))
        self.assertTrue(names.usable_for_name_decision(["N/a Gilbert", "Mary Gilbert"]))

    def test_a_single_initial_does_not_count_as_a_part(self):
        self.assertFalse(names.usable_for_name_decision(["J Smith"]))

    def test_a_company_may_be_one_word(self):
        self.assertTrue(names.usable_for_name_decision(["Binanfx"], company=True))
        self.assertFalse(names.usable_for_name_decision(["Ltd"], company=True))


class TestTokens(unittest.TestCase):
    """The blocking index has to find a record whose spelling differs from the query's."""

    def test_tokens_include_variant_siblings(self):
        tokens = names.tokens("Mohammed Ali")
        self.assertIn("mohammed", tokens)
        self.assertIn("muhammad", tokens)
        self.assertIn("aly", tokens)

    def test_tokens_are_sorted_and_deduplicated(self):
        self.assertEqual(names.tokens("Smith Smith"), ["smith"])

    def test_a_screened_name_and_its_record_share_a_token(self):
        screened = set(names.tokens("Muhammad Nadeem GHANI"))
        record = set(names.tokens("Mohammad Nadeem GHANI"))
        self.assertTrue(screened & record)


class TestQueryKey(unittest.TestCase):
    """Decision log D11: the key a name is filed under in the search results."""

    def test_sorted_lowercase_words(self):
        self.assertEqual(names.query_key("Clara Moreau"), "clara moreau")
        self.assertEqual(names.query_key("Bernard, Samuel"), "bernard samuel")

    def test_accents_and_punctuation_out(self):
        self.assertEqual(names.query_key("Jérôme Kerviel"), "jerome kerviel")

    def test_single_letters_are_dropped(self):
        self.assertEqual(names.query_key("Paul P Griffin"), "griffin paul")
        self.assertEqual(names.query_key("Baker, Zachary M"), "baker zachary")

    def test_duplicates_are_kept(self):
        self.assertEqual(names.query_key("Lee Lee Chan"), "chan lee lee")

    def test_letters_outside_ascii_are_dropped_not_transliterated(self):
        # The data room files "Drozd, Tomasz Pawe\u0142" under "drozd pawe tomasz".
        self.assertEqual(names.query_key("Drozd, Tomasz Pawe\u0142"), "drozd pawe tomasz")

    def test_query_keys_offers_the_transliterated_spelling_too(self):
        keys = names.query_keys("Drozd, Tomasz Pawe\u0142")
        self.assertEqual(keys, ["drozd pawe tomasz", "drozd pawel tomasz"])

    def test_query_keys_is_one_key_when_the_name_is_plain_ascii(self):
        self.assertEqual(names.query_keys("Clara Moreau"), ["clara moreau"])


class TestVariantSources(unittest.TestCase):
    def test_builtin_matches_the_policy_tab(self):
        self.assertEqual(len(DEFAULT.groups), 55)
        self.assertEqual(len(DEFAULT.legal_forms), 30)
        for form in ["ltd", "gmbh", "sa", "llc", "plc", "srl"]:
            self.assertTrue(DEFAULT.is_legal_form(form), form)

    def test_a_folder_file_can_be_a_list_of_groups(self):
        variants = from_raw([["aaa", "bbb"], ["ccc", "ddd"]])
        self.assertTrue(variants.same_group("aaa", "bbb"))
        self.assertFalse(variants.same_group("aaa", "ccc"))

    def test_a_folder_file_can_be_a_mapping(self):
        variants = from_raw({"muhammad": ["mohd"], "company_legal_forms": ["ltd"]})
        self.assertTrue(variants.same_group("muhammad", "mohd"))
        self.assertTrue(variants.is_legal_form("ltd"))

    def test_nested_groups_under_a_key(self):
        variants = from_raw({"given_name_groups": [["aaa", "bbb"], ["ccc", "ddd"]],
                             "company_legal_forms": ["xyz"]})
        self.assertEqual(len(variants.groups), 2)
        self.assertTrue(variants.is_legal_form("xyz"))

    def test_an_unusable_file_falls_back_to_the_builtin(self):
        variants = from_raw({"nonsense": 7})
        self.assertEqual(len(variants.groups), 55)
        self.assertEqual(len(variants.legal_forms), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

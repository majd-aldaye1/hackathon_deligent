"""Step 2: text normalisation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import norm  # noqa: E402


class TestStripAccents(unittest.TestCase):
    def test_combining_marks(self):
        self.assertEqual(norm.strip_accents("Müller"), "Muller")
        self.assertEqual(norm.strip_accents("Jérôme"), "Jerome")
        self.assertEqual(norm.strip_accents("Stefanović"), "Stefanovic")
        self.assertEqual(norm.strip_accents("Sulęcin"), "Sulecin")
        self.assertEqual(norm.strip_accents("Côte d'Ivoire"), "Cote d'Ivoire")

    def test_letters_that_do_not_decompose(self):
        # Without the transliteration table these lose a letter instead of keeping it.
        self.assertEqual(norm.strip_accents("Paweł"), "Pawel")
        self.assertEqual(norm.strip_accents("Ørsted"), "Orsted")
        self.assertEqual(norm.strip_accents("Straße"), "Strasse")
        self.assertEqual(norm.strip_accents("Æthelred"), "AEthelred")

    def test_empty(self):
        self.assertEqual(norm.strip_accents(""), "")
        self.assertEqual(norm.strip_accents(None), "")


class TestFoldAndWords(unittest.TestCase):
    def test_fold_squeezes_and_lowercases(self):
        self.assertEqual(norm.fold("  ROMAINE   MEGAN "), "romaine megan")

    def test_fold_keeps_punctuation(self):
        self.assertEqual(norm.fold("Md. Saidul"), "md. saidul")

    def test_words_splits_on_punctuation(self):
        self.assertEqual(norm.words("Md. Saidul Islam"), ["md", "saidul", "islam"])
        self.assertEqual(norm.words("Bernard, Samuel"), ["bernard", "samuel"])
        self.assertEqual(norm.words("STILE ITALIANO S.R.L."), ["stile", "italiano", "s", "r", "l"])


class TestBrackets(unittest.TestCase):
    def test_round_square_and_angle(self):
        self.assertEqual(norm.words(norm.drop_brackets("Elvira Morillo (AKA)")),
                         ["elvira", "morillo"])
        self.assertEqual(norm.words(norm.drop_brackets("Spain [Residency]")), ["spain"])
        self.assertEqual(norm.words(norm.drop_brackets("A {x} B <y>")), ["a", "b"])


class TestPlaceholders(unittest.TestCase):
    def test_the_ones_in_the_data(self):
        for word in ["n/a", "N/A", "0000", "xxx", "XXX", "test", "unknown", "na"]:
            self.assertTrue(norm.is_placeholder(word), word)

    def test_real_names_are_not_placeholders(self):
        for word in ["smith", "md", "barajas", "sani", "martin", "none1"]:
            self.assertFalse(norm.is_placeholder(word), word)

    def test_any_run_of_digits(self):
        self.assertTrue(norm.is_placeholder("123456"))


class TestTailSegment(unittest.TestCase):
    def test_takes_the_last_piece_without_its_tag(self):
        self.assertEqual(norm.tail_segment("Spain [Residency]"), "Spain")
        self.assertEqual(
            norm.tail_segment("10 Fort William Place, St. John's, A1C 1K4, Canada [Business]"),
            "Canada",
        )
        self.assertEqual(norm.tail_segment("Zamora, Zamora, Spain"), "Spain")

    def test_single_piece_is_its_own_tail(self):
        self.assertEqual(norm.tail_segment("Pakistan"), "Pakistan")

    def test_empty(self):
        self.assertEqual(norm.tail_segment(""), "")
        self.assertEqual(norm.tail_segment("[PEP]"), "")


class TestLevenshtein(unittest.TestCase):
    def test_substitution_insertion_deletion(self):
        self.assertEqual(norm.levenshtein("saedul", "saidul"), 1)
        self.assertEqual(norm.levenshtein("abc", "abcd"), 1)
        self.assertEqual(norm.levenshtein("abcd", "abc"), 1)

    def test_a_swap_costs_two_edits(self):
        # POLICY principle 8: "swapping two letters is two edits".
        self.assertEqual(norm.levenshtein("ab", "ba"), 2)
        self.assertEqual(norm.levenshtein("daniel", "danile"), 2)

    def test_identical_and_empty(self):
        self.assertEqual(norm.levenshtein("x", "x"), 0)
        self.assertEqual(norm.levenshtein("", "abc"), 3)

    def test_cap_reports_above_the_cap(self):
        self.assertEqual(norm.levenshtein("john", "jonathan", cap=1), 2)
        self.assertEqual(norm.levenshtein("saedul", "saidul", cap=1), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Text normalisation shared by names, countries and note parsing.

POLICY.md principle 8: compare "ignoring case, accents, punctuation and anything in
brackets".  Everything that strips text down to comparable tokens lives here.
"""

import re
import unicodedata

# POLICY.md: "Placeholders (NA, N/A, TEST, UNKNOWN, XXX, NONE, digits and the like) are
# not name parts".  The ones actually present in the development set are N/a, 0000, Xxx,
# Test, NA and Unknown; the rest are the obvious members of the same family.
PLACEHOLDER_WORDS = frozenset(
    [
        "na",
        "n/a",
        "n.a",
        "nil",
        "none",
        "null",
        "test",
        "testing",
        "unknown",
        "unk",
        "tbd",
        "tba",
        "dummy",
        "sample",
        "placeholder",
        "notprovided",
        "noname",
        "nodata",
        "anon",
        "anonymous",
    ]
)

# Letters that NFKD cannot decompose into a Latin letter plus a combining mark.  Without
# these, "Paweł" would lose its last letter instead of becoming "Pawel".
TRANSLITERATE = {
    "\u0141": "L", "\u0142": "l",      # L with stroke
    "\u00d8": "O", "\u00f8": "o",      # O with stroke
    "\u0110": "D", "\u0111": "d",      # D with stroke
    "\u0126": "H", "\u0127": "h",
    "\u0131": "i", "\u0130": "I",      # dotless and dotted i
    "\u0166": "T", "\u0167": "t",
    "\u00c6": "AE", "\u00e6": "ae",
    "\u0152": "OE", "\u0153": "oe",
    "\u00df": "ss",
    "\u00de": "Th", "\u00fe": "th",
    "\u00d0": "D", "\u00f0": "d",
    "\u0409": "Lj", "\u040a": "Nj",
    "\u2019": "'", "\u2018": "'", "\u02bc": "'",
}
_TRANSLITERATE_TABLE = {ord(k): v for k, v in TRANSLITERATE.items()}

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|<[^>]*>")
_NOT_WORD = re.compile(r"[^0-9A-Za-z]+")
_XS = re.compile(r"^x{2,}$")
_DIGITS = re.compile(r"^[0-9]+$")


def strip_accents(text):
    """"Müller" -> "Muller", "Jérôme" -> "Jerome", "Paweł" -> "Pawel"."""
    text = (text or "").translate(_TRANSLITERATE_TABLE)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fold(text):
    """Accents out, lowercase, whitespace squeezed.  Punctuation kept."""
    return re.sub(r"\s+", " ", strip_accents(text or "")).strip().lower()


def drop_brackets(text):
    """POLICY principle 8: "anything in brackets" is not part of the name."""
    return _BRACKETS.sub(" ", text or "")


def words(text):
    """Split on anything that is not a letter or digit, after folding."""
    return [w for w in _NOT_WORD.split(fold(text)) if w]


def ascii_words(text):
    """Words after dropping every character that is not an ASCII letter.

    Deliberately lossy and deliberately *not* transliterated: the search results in the
    data room are filed under a key built this way, so "Tomasz Pawe\u0142 Drozd" is filed as
    "drozd pawe tomasz", with the stroked l simply gone.  Name comparison uses `words`,
    which keeps the letter.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return [w.lower() for w in re.sub(r"[^A-Za-z ]", " ", stripped).split() if w]


def is_placeholder(word):
    """A token that stands in for a missing name, not a name part."""
    word = (word or "").strip().lower()
    bare = word.strip(".").replace("/", "").replace(".", "")
    if not bare:
        return True
    if _DIGITS.match(bare):
        return True
    if _XS.match(bare):
        return True
    return bare in PLACEHOLDER_WORDS or word in PLACEHOLDER_WORDS


def tail_segment(text):
    """The last comma-separated piece, with any "[tag]" suffix removed.

    Hit addresses read "10 Fort William Place, ..., A1C 1K4, Canada [Business]" and
    places of birth read "Zamora, Zamora, Spain"; both name their country last.
    """
    cleaned = drop_brackets(text or "").strip().strip(".,;")
    if not cleaned:
        return ""
    return cleaned.split(",")[-1].strip()


def levenshtein(a, b, cap=None):
    """Edit distance, where an edit "adds, removes or changes one letter".

    `cap` returns early: anything above the cap is reported as cap + 1, which is all a
    threshold test needs.
    """
    if a == b:
        return 0
    if cap is not None and abs(len(a) - len(b)) > cap:
        return cap + 1
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        best = current[0]
        for j, cb in enumerate(b, start=1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (0 if ca == cb else 1),
            )
            best = min(best, current[j])
        if cap is not None and best > cap:
            return cap + 1
        previous = current
    return previous[len(b)]

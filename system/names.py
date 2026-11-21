"""Name comparison, POLICY.md principle 8.

    Compare name parts ignoring case, accents, punctuation and anything in brackets;
    single letters are initials, not parts, and each distinct part counts once.  Two
    parts match when they are identical, are listed together in name_variants.json, are
    written together or apart (Abdulsalam matches Abdul Salam, counting as one part that
    covers both), or differ by at most 1 edit for parts of 4 to 6 letters and 2 for
    longer ones (an edit adds, removes or changes one letter, so swapping two letters is
    two edits; parts shorter than 4 letters must be identical; the shorter part's length
    decides).  Names agree when at least two parts match, or every part of the shorter
    name matches.  Aliases count as names, nicknames included.  Placeholders ... are not
    name parts: an individual customer whose names have fewer than two real parts can be
    neither confirmed nor cleared on name; a hit's single-part alias can still agree with
    a customer's name.  For companies, the legal forms listed in name_variants.json ...
    are not name parts.
"""

from . import norm
from .name_variants import DEFAULT as DEFAULT_VARIANTS

# Beyond this many parts the exhaustive matcher falls back to a greedy pass.  Real names
# never come close; the cap only stops a pathological input from costing time.
MAX_EXHAUSTIVE_PARTS = 12


def parts(name, company=False, variants=None):
    """The comparable parts of one name, in order, each counted once."""
    variants = variants or DEFAULT_VARIANTS
    out = []
    for word in norm.words(norm.drop_brackets(name)):
        if len(word) == 1:
            continue  # a single letter is an initial, not a part
        if norm.is_placeholder(word):
            continue
        if company and variants.is_legal_form(word):
            continue
        if word not in out:
            out.append(word)
    return out


def tokens(name, company=False, variants=None):
    """Blocking-index tokens for a name: its parts and their variant-group siblings."""
    variants = variants or DEFAULT_VARIANTS
    out = set()
    for part in parts(name, company, variants):
        out.add(part)
        for index in variants.group_ids.get(part, ()):
            out.update(variants.groups[index])
    return sorted(out)


def parts_match(left, right, variants=None):
    """Do two single parts match?"""
    variants = variants or DEFAULT_VARIANTS
    if left == right:
        return True
    if variants.same_group(left, right):
        return True
    shorter = min(len(left), len(right))
    if shorter < 4:
        return False  # "parts shorter than 4 letters must be identical"
    threshold = 1 if shorter <= 6 else 2
    return norm.levenshtein(left, right, cap=threshold) <= threshold


def _joined_match(whole, first, second, variants):
    """`whole` written together against `first` + `second` written apart.

    A piece shorter than 4 letters must be identical (principle 8), so when either piece
    is that short the join must be exact.  Otherwise the edit allowance lets a long part
    swallow a short one: "logistics" is 2 edits from "st" + "logistics".
    """
    if min(len(first), len(second)) < 4:
        return whole == first + second
    return parts_match(whole, first + second, variants)


def _covers_shorter(short, long_, variants):
    """Can every part of the shorter name be matched, each long part used at most once?

    A join counts as one matched part that covers both pieces (principle 8: "Abdulsalam
    matches Abdul Salam, counting as one part that covers both"), so "Blue Grass" is
    fully covered by "Bluegrass".
    """
    n, m = len(short), len(long_)
    if n > MAX_EXHAUSTIVE_PARTS or m > MAX_EXHAUSTIVE_PARTS:
        return False
    cache = {}

    def go(i, used):
        if i >= n:
            return True
        key = (i, used)
        if key in cache:
            return cache[key]
        ok = False
        for j in range(m):
            if used & (1 << j):
                continue
            if parts_match(short[i], long_[j], variants) and go(i + 1, used | (1 << j)):
                ok = True
                break
            if (j + 1 < m and not used & (1 << (j + 1))
                    and _joined_match(short[i], long_[j], long_[j + 1], variants)
                    and go(i + 1, used | (1 << j) | (1 << (j + 1)))):
                ok = True
                break
            if (i + 1 < n and _joined_match(long_[j], short[i], short[i + 1], variants)
                    and go(i + 2, used | (1 << j))):
                ok = True
                break
        cache[key] = ok
        return ok

    return go(0, 0)


def _match_count(left, right, variants):
    """The largest number of parts that can be matched, each part used at most once.

    A part on one side may be matched by two adjacent parts on the other written
    together, which counts as one matched part covering both.
    """
    n, m = len(left), len(right)
    if n == 0 or m == 0:
        return 0
    if n > MAX_EXHAUSTIVE_PARTS or m > MAX_EXHAUSTIVE_PARTS:
        return _greedy_match_count(left, right, variants)

    cache = {}

    def best(i, used_right):
        """Most matches obtainable from left[i:] given the right parts already used."""
        if i >= n:
            return 0
        key = (i, used_right)
        if key in cache:
            return cache[key]
        result = best(i + 1, used_right)  # leave left[i] unmatched
        for j in range(m):
            if used_right & (1 << j):
                continue
            if parts_match(left[i], right[j], variants):
                result = max(result, 1 + best(i + 1, used_right | (1 << j)))
            # left[i] written as two adjacent right parts joined
            if j + 1 < m and not used_right & (1 << (j + 1)):
                if _joined_match(left[i], right[j], right[j + 1], variants):
                    joined = used_right | (1 << j) | (1 << (j + 1))
                    result = max(result, 1 + best(i + 1, joined))
        # left[i] and left[i+1] written together matching one right part
        if i + 1 < n:
            for j in range(m):
                if used_right & (1 << j):
                    continue
                if _joined_match(right[j], left[i], left[i + 1], variants):
                    result = max(result, 1 + best(i + 2, used_right | (1 << j)))
        cache[key] = result
        return result

    return best(0, 0)


def _greedy_match_count(left, right, variants):
    used = set()
    count = 0
    for part in left:
        for j, other in enumerate(right):
            if j in used:
                continue
            if parts_match(part, other, variants):
                used.add(j)
                count += 1
                break
    return count


def compare(left_name, right_name, company=False, variants=None):
    """Compare two names.  Returns (agree, matched_parts, left_parts, right_parts)."""
    variants = variants or DEFAULT_VARIANTS
    left = parts(left_name, company, variants)
    right = parts(right_name, company, variants)
    return compare_parts(left, right, variants) + (left, right)


def compare_parts(left, right, variants=None):
    """Compare two already-split names.  Returns (agree, matched_parts)."""
    variants = variants or DEFAULT_VARIANTS
    if not left or not right:
        return False, 0
    matched = _match_count(left, right, variants)
    shorter = min(len(left), len(right))
    agree = matched >= 2 or matched >= shorter
    if not agree:
        # With names of equal length either one is "the shorter"; trying both can only
        # make agreement easier, which makes a name-based clear harder (the safe side).
        if len(left) <= len(right):
            agree = _covers_shorter(left, right, variants)
        if not agree and len(right) <= len(left):
            agree = _covers_shorter(right, left, variants)
    return agree, matched


def agree(left_name, right_name, company=False, variants=None):
    return compare(left_name, right_name, company, variants)[0]


def any_agree(left_names, right_names, company=False, variants=None):
    """Any name or alias on one side agreeing with any on the other.

    Returns (agree, left_name, right_name) naming the pair that agreed, so the reason
    text can quote the names actually compared.  Candidates are tried in the order given,
    which keeps the chosen pair stable.
    """
    variants = variants or DEFAULT_VARIANTS
    for left in left_names or ():
        if not left:
            continue
        for right in right_names or ():
            if not right:
                continue
            if agree(left, right, company, variants):
                return True, left, right
    return False, None, None


def usable_for_name_decision(names, company=False, variants=None):
    """POLICY: "an individual customer whose names have fewer than two real parts can be
    neither confirmed nor cleared on name"."""
    variants = variants or DEFAULT_VARIANTS
    if company:
        return any(parts(n, True, variants) for n in names or () if n)
    return any(len(parts(n, False, variants)) >= 2 for n in names or () if n)


def query_key(name):
    """The key a name is filed under in the search results.

    Decision log D11: combining marks stripped, every other non-ASCII letter dropped,
    lowercased, single-letter tokens dropped, duplicates kept, sorted, joined with one
    space.  Under this rule every individual hit in the development set maps to a query
    that exists; keeping single letters, dropping duplicates, or transliterating the
    stroked l of "Pawel" each break some of them.
    """
    return " ".join(sorted(w for w in norm.ascii_words(name) if len(w) > 1))


def query_keys(name):
    """Every key the name might be filed under, most likely first.

    The data room files "Pawe\u0142" as "pawe", but a provider that transliterates would
    file it as "pawel".  Looking both up costs nothing and cannot invent a match: a
    result still has to carry the hit's listing phrase and one of its countries before it
    says anything about the hit.
    """
    keys = [query_key(name)]
    transliterated = " ".join(sorted(w for w in norm.words(name) if len(w) > 1))
    if transliterated and transliterated not in keys:
        keys.append(transliterated)
    return [k for k in keys if k]

"""The given-name groups and company legal forms from name_variants.json.

The data folder's own file wins when it has one; these built-in copies (taken verbatim
from the Policy tab of the development workbook) are the fallback, so the system still
runs against a folder that ships the policy only as prose.
"""

BUILTIN_GROUPS = [
    "muhammad, mohammed, mohammad, mohamed, muhammed, mohamad, mohd, muhamad",
    "ahmed, ahmad, ahmet",
    "abdul, abdel, abd",
    "abdullah, abdallah, abdulla",
    "abubakar, abubakr, aboubakar, bubakar",
    "ibrahim, ebrahim, ibraheem, brahim",
    "yusuf, yousef, youssef, yousuf, josef, joseph, joe",
    "umar, omar, omer",
    "usman, uthman, othman, osman",
    "hussein, hussain, husain, hossain, hosein",
    "hassan, hasan",
    "ali, aly",
    "faruk, farouk, faruq, farooq, faroq",
    "sulaiman, suleiman, sulayman, suleman, solomon",
    "aminu, amin, ameen",
    "anthony, antony, tony, antonio",
    "robert, rob, robbie, bob, bobby, roberto",
    "william, will, bill, billy, liam, guillermo",
    "richard, rick, ricky, dick, ricardo",
    "james, jim, jimmy, jamie, jaime",
    "john, johnny, jon, jack, juan, jean, johann, johannes",
    "michael, mike, mick, mikey, miguel, michel, michele",
    "daniel, dan, danny, dani",
    "david, dave, davey, davit",
    "christopher, chris, kristopher, cristobal",
    "matthew, matt, mateo, matteo, mathieu",
    "andrew, andy, drew, andres, andrea, andreas",
    "thomas, tom, tommy, tomas, tomasz",
    "joshua, josh",
    "nicholas, nick, nicolas, nicola, nikola, nikolai",
    "alexander, alex, alejandro, alessandro, aleksandr, sasha",
    "peter, pete, pedro, pietro, pierre",
    "paul, pablo, paolo",
    "stephen, steven, steve, stefan, esteban, stefano",
    "joseph, joe, jose, giuseppe, jozef",
    "francis, frank, francisco, francesco, franco, francois",
    "charles, charlie, chuck, carlos, carlo, karl, karol",
    "edward, ed, eddie, ted, eduardo, edoardo",
    "henry, harry, enrique, enrico, henrik, heinrich",
    "mark, marc, marco",
    "markus, marcus, marcos",
    "catherine, katherine, kathryn, kate, katie, cathy, catalina, katarzyna",
    "elizabeth, liz, beth, betty, elisabeth, isabel",
    "margaret, maggie, meg, peggy, margarita",
    "jennifer, jen, jenny",
    "rebecca, becky",
    "susan, sue, susanna, susana",
    "maria, mary, marie, mariya",
    "olumide, mide",
    "oluwaseun, seun",
    "babatunde, tunde",
    "oluwatobiloba, tobi",
    "chukwuemeka, emeka",
    "ifeanyichukwu, ifeanyi",
    "nnamdi, namdi",
]

BUILTIN_LEGAL_FORMS = (
    "ab, ag, as, asa, bv, co, company, corp, corporation, gmbh, inc, kg, limited, llc, "
    "llp, lp, ltd, na, nv, oy, oyj, plc, sa, sarl, sas, se, sf, sl, spa, srl"
)


class NameVariants(object):
    """Which name parts count as the same part, and which words are legal forms."""

    def __init__(self, groups, legal_forms):
        self.groups = [tuple(g) for g in groups]
        self.group_ids = {}
        for index, group in enumerate(self.groups):
            for word in group:
                self.group_ids.setdefault(word, set()).add(index)
        self.legal_forms = frozenset(legal_forms)

    def same_group(self, left, right):
        a = self.group_ids.get(left)
        b = self.group_ids.get(right)
        return bool(a and b and (a & b))

    def is_legal_form(self, word):
        return word in self.legal_forms


def _words(value):
    if isinstance(value, str):
        return [w.strip().lower() for w in value.split(",") if w.strip()]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_words(item))
        return out
    return []


def from_raw(raw):
    """Build from whatever shape name_variants.json turns out to have.

    Accepts a list of groups, a mapping of canonical name -> forms, or an object with
    separate keys for the groups and the legal forms.  Unknown shapes fall back to the
    built-in copy rather than failing.
    """
    groups, legal = [], []
    if isinstance(raw, dict):
        for key, value in sorted(raw.items()):
            low = key.lower()
            if "legal" in low or "form" in low or "suffix" in low:
                legal.extend(_words(value))
            elif isinstance(value, (list, tuple)) and any(
                isinstance(item, (list, tuple)) for item in value
            ):
                # a list of groups, e.g. {"given_name_groups": [[...], [...]]}
                for item in value:
                    words = _words(item)
                    if words:
                        groups.append(words)
            elif isinstance(value, (list, tuple, str)):
                words = _words(value)
                if words:
                    # a mapping canonical -> forms also implies the canonical name
                    if low.isalpha() and low not in words:
                        words.append(low)
                    groups.append(words)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            words = _words(item)
            if words:
                groups.append(words)
    if not groups:
        groups = [_words(g) for g in BUILTIN_GROUPS]
    if not legal:
        legal = _words(BUILTIN_LEGAL_FORMS)
    return NameVariants(groups, legal)


DEFAULT = from_raw(None)

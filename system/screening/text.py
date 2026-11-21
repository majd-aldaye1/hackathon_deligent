"""Text primitives: name parts and name agreement (SOP principle 8), dates, countries."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# ----------------------------------------------------------------------------
# Name variants + legal forms (defaults from POLICY.md / name_variants.json;
# replaced at load time if the data room ships its own name_variants.json)
# ----------------------------------------------------------------------------
DEFAULT_VARIANT_GROUPS = [
    "muhammad, mohammed, mohammad, mohamed, muhammed, mohamad, mohd, muhamad",
    "ahmed, ahmad, ahmet", "abdul, abdel, abd", "abdullah, abdallah, abdulla",
    "abubakar, abubakr, aboubakar, bubakar", "ibrahim, ebrahim, ibraheem, brahim",
    "yusuf, yousef, youssef, yousuf, josef, joseph, joe", "umar, omar, omer",
    "usman, uthman, othman, osman", "hussein, hussain, husain, hossain, hosein",
    "hassan, hasan", "ali, aly", "faruk, farouk, faruq, farooq, faroq",
    "sulaiman, suleiman, sulayman, suleman, solomon", "aminu, amin, ameen",
    "anthony, antony, tony, antonio", "robert, rob, robbie, bob, bobby, roberto",
    "william, will, bill, billy, liam, guillermo", "richard, rick, ricky, dick, ricardo",
    "james, jim, jimmy, jamie, jaime", "john, johnny, jon, jack, juan, jean, johann, johannes",
    "michael, mike, mick, mikey, miguel, michel, michele", "daniel, dan, danny, dani",
    "david, dave, davey, davit", "christopher, chris, kristopher, cristobal",
    "matthew, matt, mateo, matteo, mathieu", "andrew, andy, drew, andres, andrea, andreas",
    "thomas, tom, tommy, tomas, tomasz", "joshua, josh",
    "nicholas, nick, nicolas, nicola, nikola, nikolai",
    "alexander, alex, alejandro, alessandro, aleksandr, sasha",
    "peter, pete, pedro, pietro, pierre", "paul, pablo, paolo",
    "stephen, steven, steve, stefan, esteban, stefano", "joseph, joe, jose, giuseppe, jozef",
    "francis, frank, francisco, francesco, franco, francois",
    "charles, charlie, chuck, carlos, carlo, karl, karol",
    "edward, ed, eddie, ted, eduardo, edoardo", "henry, harry, enrique, enrico, henrik, heinrich",
    "mark, marc, marco", "markus, marcus, marcos",
    "catherine, katherine, kathryn, kate, katie, cathy, catalina, katarzyna",
    "elizabeth, liz, beth, betty, elisabeth, isabel", "margaret, maggie, meg, peggy, margarita",
    "jennifer, jen, jenny", "rebecca, becky", "susan, sue, susanna, susana",
    "maria, mary, marie, mariya", "olumide, mide", "oluwaseun, seun", "babatunde, tunde",
    "oluwatobiloba, tobi", "chukwuemeka, emeka", "ifeanyichukwu, ifeanyi", "nnamdi, namdi",
]
DEFAULT_LEGAL_FORMS = (
    "ab, ag, as, asa, bv, co, company, corp, corporation, gmbh, inc, kg, limited, llc, llp, lp, "
    "ltd, na, nv, oy, oyj, plc, sa, sarl, sas, se, sf, sl, spa, srl"
)

VARIANT_GROUPS: list[frozenset[str]] = []
LEGAL_FORMS: set[str] = set()
_VARIANT_INDEX: dict[str, list[int]] = {}

PLACEHOLDERS = {
    "na", "n/a", "test", "unknown", "xxx", "xx", "x", "none", "null", "nil", "tbd", "tba",
    "dummy", "sample", "noname", "fnu", "lnu", "nn", "unk", "anon", "anonymous", "placeholder",
    "xxxx", "xxxxx", "zzz", "asdf", "qwerty", "nan", "undefined", "notknown", "notprovided",
}


def configure_names(groups: list[list[str]] | None = None, legal_forms: list[str] | None = None) -> None:
    global VARIANT_GROUPS, LEGAL_FORMS, _VARIANT_INDEX
    if groups is None:
        groups = [[w.strip() for w in g.split(",")] for g in DEFAULT_VARIANT_GROUPS]
    if legal_forms is None:
        legal_forms = [w.strip() for w in DEFAULT_LEGAL_FORMS.split(",")]
    VARIANT_GROUPS = [frozenset(fold(w) for w in g if w.strip()) for g in groups]
    LEGAL_FORMS = {fold(w).replace(".", "") for w in legal_forms if w.strip()}
    _VARIANT_INDEX = {}
    for i, g in enumerate(VARIANT_GROUPS):
        for w in g:
            _VARIANT_INDEX.setdefault(w, []).append(i)
    part_match.cache_clear()
    name_parts.cache_clear()


# ----------------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------------
_SPECIAL = str.maketrans({
    "ß": "ss", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ł": "l", "Ł": "l",
    "đ": "d", "Đ": "d", "ð": "d", "þ": "th", "ı": "i", "ħ": "h", "ŋ": "n",
})


def fold(s: str) -> str:
    """Lowercase, strip accents."""
    s = (s or "").translate(_SPECIAL)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|<[^>]*>")


def strip_brackets(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, _BRACKETS.sub(" ", s)
    return s


def is_placeholder(tok: str) -> bool:
    t = tok.replace("/", "").replace(".", "")
    if not t:
        return True
    if t in PLACEHOLDERS or tok in PLACEHOLDERS:
        return True
    if any(ch.isdigit() for ch in t) and not any(ch.isalpha() for ch in t):
        return True  # pure digits
    if len(set(t)) == 1 and len(t) >= 2 and t[0] in "xz":
        return True  # xxx, zzzz
    return False


@lru_cache(maxsize=200_000)
def name_parts(name: str, company: bool = False) -> tuple[str, ...]:
    """Distinct real name parts, in order. Drops brackets, punctuation, initials, placeholders,
    and (for companies) legal forms."""
    if not name:
        return ()
    s = strip_brackets(name)
    s = fold(s)
    # n/a style placeholders before punctuation is removed
    s = re.sub(r"\bn\s*/\s*a\b", " ", s)
    s = s.replace("'", "").replace("’", "").replace("`", "")
    if company:
        # a.b. / s.r.l. / l.p. legal forms written with dots -> join letters
        s = re.sub(r"\b((?:[a-z]\.){2,})", lambda m: m.group(1).replace(".", ""), s)
    s = re.sub(r"[^\w]+", " ", s)
    s = s.replace("_", " ")
    out: list[str] = []
    for tok in s.split():
        if len(tok) == 1:
            continue  # initials are not parts
        if is_placeholder(tok):
            continue
        if company and tok in LEGAL_FORMS:
            continue
        if tok not in out:
            out.append(tok)
    return tuple(out)


def search_key(name: str) -> str:
    """Search results are keyed by the name's lowercase words in alphabetical order."""
    toks = []
    s = fold(strip_brackets(name or "")).replace("'", "").replace("’", "")
    for tok in re.sub(r"[^\w]+", " ", s).split():
        if len(tok) > 1 and tok not in toks:
            toks.append(tok)
    return " ".join(sorted(toks))


# ----------------------------------------------------------------------------
# Name part matching and name agreement
# ----------------------------------------------------------------------------
def levenshtein(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _edit_allowance(a: str, b: str) -> int:
    n = min(len(a), len(b))
    if n < 4:
        return 0
    if n <= 6:
        return 1
    return 2


@lru_cache(maxsize=500_000)
def part_match(a: str, b: str) -> bool:
    if a == b:
        return True
    ga = _VARIANT_INDEX.get(a)
    if ga:
        gb = _VARIANT_INDEX.get(b)
        if gb and set(ga) & set(gb):
            return True
    k = _edit_allowance(a, b)
    if k and levenshtein(a, b, k) <= k:
        return True
    return False


def _units(pa: tuple[str, ...], pb: tuple[str, ...]):
    """All candidate match units: (set of A indices, set of B indices)."""
    units = []
    for i, a in enumerate(pa):
        for j, b in enumerate(pb):
            if part_match(a, b):
                units.append((frozenset([i]), frozenset([j])))
    # written together or apart: one part == two parts joined (either order)
    for i, a in enumerate(pa):
        for j in range(len(pb)):
            for k in range(len(pb)):
                if j != k and len(a) >= 4 and part_match(a, pb[j] + pb[k]):
                    units.append((frozenset([i]), frozenset([j, k])))
    for j, b in enumerate(pb):
        for i in range(len(pa)):
            for k in range(len(pa)):
                if i != k and len(b) >= 4 and part_match(b, pa[i] + pa[k]):
                    units.append((frozenset([i, k]), frozenset([j])))
    return units


def _best(units, pa, pb):
    """Search disjoint unit sets; return (max units, max coverage A, max coverage B)."""
    best = [0, 0, 0]

    def rec(idx, used_a, used_b, n):
        if n > best[0]:
            best[0] = n
        if len(used_a) > best[1]:
            best[1] = len(used_a)
        if len(used_b) > best[2]:
            best[2] = len(used_b)
        for t in range(idx, len(units)):
            ua, ub = units[t]
            if ua & used_a or ub & used_b:
                continue
            rec(t + 1, used_a | ua, used_b | ub, n + 1)

    rec(0, frozenset(), frozenset(), 0)
    return best


@lru_cache(maxsize=200_000)
def parts_agree(pa: tuple[str, ...], pb: tuple[str, ...]) -> bool:
    """Names agree when at least two parts match, or every part of the shorter name matches."""
    if not pa or not pb:
        return False
    units = _units(pa, pb)
    if not units:
        return False
    if len(units) > 18:  # keep the search bounded
        units = units[:18]
    n, cov_a, cov_b = _best(units, pa, pb)
    if n >= 2:
        return True
    if len(pa) < len(pb):
        return cov_a == len(pa)
    if len(pb) < len(pa):
        return cov_b == len(pb)
    return cov_a == len(pa) or cov_b == len(pb)


def names_agree(a: str, b: str, company: bool = False) -> bool:
    return parts_agree(name_parts(a, company), name_parts(b, company))


# ----------------------------------------------------------------------------
# Dates. A date is a tuple (year, month|None, day|None).
# ----------------------------------------------------------------------------
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"

DATE_PATTERNS = [
    ("iso", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("ymd_slash", re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")),
    ("slash", re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")),
    ("mdy", re.compile(r"\b(" + _MON + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
    ("dmy", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MON + r"),?\s+(\d{4})\b", re.I)),
    ("my", re.compile(r"\b(" + _MON + r"),?\s+(\d{4})\b", re.I)),
    ("ym", re.compile(r"\b(\d{4})-(\d{1,2})\b(?!-)")),
    ("y", re.compile(r"(?<![\d/.-])(1[89]\d{2}|20\d{2})(?![\d/-])")),
]


def _valid(y, m, d):
    if not (1800 <= y <= 2100):
        return False
    if m is not None and not (1 <= m <= 12):
        return False
    if d is not None and not (1 <= d <= 31):
        return False
    return True


def find_dates(text: str, dayfirst: bool = True, years: bool = True):
    """Find dates in free text. Returns list of (start, end, (y, m, d)) without overlaps,
    most specific formats first."""
    if not text:
        return []
    found = []
    taken: list[tuple[int, int]] = []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for kind, rx in DATE_PATTERNS:
        if kind == "y" and not years:
            continue
        for m in rx.finditer(text):
            s, e = m.span()
            if not free(s, e):
                continue
            g = m.groups()
            try:
                if kind in ("iso", "ymd_slash"):
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                elif kind == "slash":
                    a, b, y = int(g[0]), int(g[1]), int(g[2])
                    if a > 12:
                        d, mo = a, b
                    elif b > 12:
                        mo, d = a, b
                    elif dayfirst:
                        d, mo = a, b
                    else:
                        mo, d = a, b
                elif kind == "mdy":
                    mo, d, y = MONTHS[g[0].lower().rstrip(".")], int(g[1]), int(g[2])
                elif kind == "dmy":
                    d, mo, y = int(g[0]), MONTHS[g[1].lower().rstrip(".")], int(g[2])
                elif kind == "my":
                    mo, y, d = MONTHS[g[0].lower().rstrip(".")], int(g[1]), None
                elif kind == "ym":
                    y, mo, d = int(g[0]), int(g[1]), None
                else:
                    y, mo, d = int(g[0]), None, None
            except (KeyError, ValueError):
                continue
            if not _valid(y, mo, d):
                continue
            found.append((s, e, (y, mo, d)))
            taken.append((s, e))
    found.sort()
    return found


def parse_date(s, dayfirst: bool = True):
    """Parse a single structured date field. Returns (y, m, d) or None."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    ds = find_dates(s, dayfirst=dayfirst)
    return ds[0][2] if ds else None


def fmt_date(d) -> str:
    if not d:
        return ""
    y, m, dd = d
    if m is None:
        return f"{y}"
    if dd is None:
        return f"{y}-{m:02d}"
    return f"{y}-{m:02d}-{dd:02d}"


def date_key_low(d):
    y, m, dd = d
    return (y, m or 1, dd or 1)


def date_key_high(d):
    y, m, dd = d
    return (y, m or 12, dd or 31)


# ----------------------------------------------------------------------------
# Countries
# ----------------------------------------------------------------------------
# canonical name: (iso2, [aliases / demonyms])
_COUNTRIES = {
    "Afghanistan": ("AF", ["Afghan"]), "Albania": ("AL", ["Albanian"]), "Algeria": ("DZ", ["Algerian"]),
    "Andorra": ("AD", ["Andorran"]), "Angola": ("AO", ["Angolan"]), "Argentina": ("AR", ["Argentine", "Argentinian"]),
    "Armenia": ("AM", ["Armenian"]), "Australia": ("AU", ["Australian"]), "Austria": ("AT", ["Austrian"]),
    "Azerbaijan": ("AZ", ["Azerbaijani", "Azeri"]), "Bahamas": ("BS", ["Bahamian", "The Bahamas"]),
    "Bahrain": ("BH", ["Bahraini"]), "Bangladesh": ("BD", ["Bangladeshi"]), "Barbados": ("BB", ["Barbadian"]),
    "Belarus": ("BY", ["Belarusian"]), "Belgium": ("BE", ["Belgian"]), "Belize": ("BZ", ["Belizean"]),
    "Benin": ("BJ", ["Beninese"]), "Bhutan": ("BT", ["Bhutanese"]), "Bolivia": ("BO", ["Bolivian"]),
    "Bosnia and Herzegovina": ("BA", ["Bosnian", "Bosnia"]), "Botswana": ("BW", ["Botswanan", "Motswana"]),
    "Brazil": ("BR", ["Brazilian"]), "Brunei": ("BN", ["Bruneian"]), "Bulgaria": ("BG", ["Bulgarian"]),
    "Burkina Faso": ("BF", ["Burkinabe"]), "Burundi": ("BI", ["Burundian"]), "Cambodia": ("KH", ["Cambodian"]),
    "Cameroon": ("CM", ["Cameroonian"]), "Canada": ("CA", ["Canadian"]), "Cape Verde": ("CV", ["Cabo Verde", "Cape Verdean"]),
    "Central African Republic": ("CF", []), "Chad": ("TD", ["Chadian"]), "Chile": ("CL", ["Chilean"]),
    "China": ("CN", ["Chinese", "People's Republic of China", "PRC"]), "Colombia": ("CO", ["Colombian"]),
    "Comoros": ("KM", []), "Congo": ("CG", ["Republic of the Congo", "Congolese"]),
    "Democratic Republic of the Congo": ("CD", ["DR Congo", "DRC", "Congo, Democratic Republic of the"]),
    "Costa Rica": ("CR", ["Costa Rican"]), "Cote d'Ivoire": ("CI", ["Côte d'Ivoire", "Cote D'Ivoire", "Ivory Coast", "Ivorian"]),
    "Croatia": ("HR", ["Croatian"]), "Cuba": ("CU", ["Cuban"]), "Cyprus": ("CY", ["Cypriot"]),
    "Czech Republic": ("CZ", ["Czechia", "Czech"]), "Denmark": ("DK", ["Danish"]), "Djibouti": ("DJ", []),
    "Dominica": ("DM", []), "Dominican Republic": ("DO", ["Dominican"]), "Ecuador": ("EC", ["Ecuadorian", "Ecuadorean"]),
    "Egypt": ("EG", ["Egyptian"]), "El Salvador": ("SV", ["Salvadoran"]), "Equatorial Guinea": ("GQ", []),
    "Eritrea": ("ER", ["Eritrean"]), "Estonia": ("EE", ["Estonian"]), "Eswatini": ("SZ", ["Swaziland"]),
    "Ethiopia": ("ET", ["Ethiopian"]), "Fiji": ("FJ", ["Fijian"]), "Finland": ("FI", ["Finnish"]),
    "France": ("FR", ["French"]), "Gabon": ("GA", ["Gabonese"]), "Gambia": ("GM", ["Gambian", "The Gambia"]),
    "Georgia": ("GE", ["Georgian"]), "Germany": ("DE", ["German"]), "Ghana": ("GH", ["Ghanaian"]),
    "Greece": ("GR", ["Greek"]), "Grenada": ("GD", []), "Guatemala": ("GT", ["Guatemalan"]),
    "Guinea": ("GN", ["Guinean"]), "Guinea-Bissau": ("GW", []), "Guyana": ("GY", ["Guyanese"]),
    "Haiti": ("HT", ["Haitian"]), "Honduras": ("HN", ["Honduran"]), "Hungary": ("HU", ["Hungarian"]),
    "Iceland": ("IS", ["Icelandic"]), "India": ("IN", ["Indian"]), "Indonesia": ("ID", ["Indonesian"]),
    "Iran": ("IR", ["Iranian", "Islamic Republic of Iran"]), "Iraq": ("IQ", ["Iraqi"]), "Ireland": ("IE", ["Irish", "Republic of Ireland"]),
    "Israel": ("IL", ["Israeli"]), "Italy": ("IT", ["Italian"]), "Jamaica": ("JM", ["Jamaican"]),
    "Japan": ("JP", ["Japanese"]), "Jordan": ("JO", ["Jordanian"]), "Kazakhstan": ("KZ", ["Kazakh", "Kazakhstani"]),
    "Kenya": ("KE", ["Kenyan"]), "Kosovo": ("XK", ["Kosovar"]), "Kuwait": ("KW", ["Kuwaiti"]),
    "Kyrgyzstan": ("KG", ["Kyrgyz"]), "Laos": ("LA", ["Lao", "Laotian"]), "Latvia": ("LV", ["Latvian"]),
    "Lebanon": ("LB", ["Lebanese"]), "Lesotho": ("LS", []), "Liberia": ("LR", ["Liberian"]),
    "Libya": ("LY", ["Libyan"]), "Liechtenstein": ("LI", []), "Lithuania": ("LT", ["Lithuanian"]),
    "Luxembourg": ("LU", ["Luxembourgish", "Luxembourger"]), "Madagascar": ("MG", ["Malagasy"]),
    "Malawi": ("MW", ["Malawian"]), "Malaysia": ("MY", ["Malaysian"]), "Maldives": ("MV", ["Maldivian"]),
    "Mali": ("ML", ["Malian"]), "Malta": ("MT", ["Maltese"]), "Mauritania": ("MR", ["Mauritanian"]),
    "Mauritius": ("MU", ["Mauritian"]), "Mexico": ("MX", ["Mexican"]), "Moldova": ("MD", ["Moldovan", "Republic of Moldova"]),
    "Monaco": ("MC", ["Monegasque"]), "Mongolia": ("MN", ["Mongolian"]), "Montenegro": ("ME", ["Montenegrin"]),
    "Morocco": ("MA", ["Moroccan"]), "Mozambique": ("MZ", ["Mozambican"]), "Myanmar": ("MM", ["Burma", "Burmese"]),
    "Namibia": ("NA", ["Namibian"]), "Nepal": ("NP", ["Nepali", "Nepalese"]), "Netherlands": ("NL", ["Dutch", "The Netherlands", "Holland"]),
    "New Zealand": ("NZ", ["New Zealander"]), "Nicaragua": ("NI", ["Nicaraguan"]), "Niger": ("NE", ["Nigerien"]),
    "Nigeria": ("NG", ["Nigerian"]), "North Korea": ("KP", ["North Korean", "Democratic People's Republic of Korea", "DPRK"]),
    "North Macedonia": ("MK", ["Macedonia", "Macedonian"]), "Norway": ("NO", ["Norwegian"]), "Oman": ("OM", ["Omani"]),
    "Pakistan": ("PK", ["Pakistani"]), "Palestine": ("PS", ["Palestina", "Palestinian", "State of Palestine", "Palestinian Territories"]),
    "Panama": ("PA", ["Panamanian"]), "Papua New Guinea": ("PG", []), "Paraguay": ("PY", ["Paraguayan"]),
    "Peru": ("PE", ["Peruvian"]), "Philippines": ("PH", ["Filipino", "Philippine"]), "Poland": ("PL", ["Polish"]),
    "Portugal": ("PT", ["Portuguese"]), "Qatar": ("QA", ["Qatari"]), "Romania": ("RO", ["Romanian"]),
    "Russia": ("RU", ["Russian", "Russian Federation"]), "Rwanda": ("RW", ["Rwandan"]),
    "Saudi Arabia": ("SA", ["Saudi", "Saudi Arabian"]), "Senegal": ("SN", ["Senegalese"]), "Serbia": ("RS", ["Serbian"]),
    "Seychelles": ("SC", []), "Sierra Leone": ("SL", ["Sierra Leonean"]), "Singapore": ("SG", ["Singaporean"]),
    "Slovakia": ("SK", ["Slovak", "Slovakian"]), "Slovenia": ("SI", ["Slovenian", "Slovene"]), "Somalia": ("SO", ["Somali"]),
    "South Africa": ("ZA", ["South African"]), "South Korea": ("KR", ["South Korean", "Republic of Korea", "Korea, Republic of", "Korean"]),
    "South Sudan": ("SS", ["South Sudanese"]), "Spain": ("ES", ["Spanish"]), "Sri Lanka": ("LK", ["Sri Lankan"]),
    "Sudan": ("SD", ["Sudanese"]), "Suriname": ("SR", ["Surinamese"]), "Sweden": ("SE", ["Swedish"]),
    "Switzerland": ("CH", ["Swiss"]), "Syria": ("SY", ["Syrian", "Syrian Arab Republic"]), "Taiwan": ("TW", ["Taiwanese"]),
    "Tajikistan": ("TJ", ["Tajik"]), "Tanzania": ("TZ", ["Tanzanian"]), "Thailand": ("TH", ["Thai"]),
    "Togo": ("TG", ["Togolese"]), "Trinidad and Tobago": ("TT", ["Trinidadian"]), "Tunisia": ("TN", ["Tunisian"]),
    "Turkey": ("TR", ["Turkish", "Türkiye", "Turkiye"]), "Turkmenistan": ("TM", ["Turkmen"]), "Uganda": ("UG", ["Ugandan"]),
    "Ukraine": ("UA", ["Ukrainian"]), "United Arab Emirates": ("AE", ["UAE", "Emirati"]),
    "United Kingdom": ("GB", ["UK", "U.K.", "British", "Great Britain", "England", "Scotland", "Wales", "Northern Ireland", "Britain"]),
    "United States": ("US", ["USA", "U.S.", "U.S.A.", "American", "United States of America", "US"]),
    "Uruguay": ("UY", ["Uruguayan"]), "Uzbekistan": ("UZ", ["Uzbek"]), "Venezuela": ("VE", ["Venezuelan"]),
    "Vietnam": ("VN", ["Vietnamese", "Viet Nam"]), "Yemen": ("YE", ["Yemeni"]), "Zambia": ("ZM", ["Zambian"]),
    "Zimbabwe": ("ZW", ["Zimbabwean"]),
    # territories count as their own country
    "Hong Kong": ("HK", ["Hong Kong SAR", "Hong Kong Special Administrative Region of China"]),
    "Macao": ("MO", ["Macau", "Macao SAR", "Macao Special Administrative Region of China"]),
    "Puerto Rico": ("PR", ["Puerto Rican"]), "Jersey": ("JE", []), "Guernsey": ("GG", []), "Isle of Man": ("IM", []),
    "Gibraltar": ("GI", []), "Bermuda": ("BM", []), "Cayman Islands": ("KY", []),
    "British Virgin Islands": ("VG", ["Virgin Islands, British"]), "US Virgin Islands": ("VI", ["U.S. Virgin Islands"]),
    "Northern Mariana Islands": ("MP", []), "Guam": ("GU", []), "American Samoa": ("AS", []),
    "Greenland": ("GL", []), "Faroe Islands": ("FO", []), "Aruba": ("AW", []), "Curacao": ("CW", ["Curaçao"]),
    "New Caledonia": ("NC", []), "French Polynesia": ("PF", []), "Anguilla": ("AI", []), "Montserrat": ("MS", []),
    "Turks and Caicos Islands": ("TC", []), "Western Sahara": ("EH", []),
}
NOT_COUNTRIES = {"international", "europe", "global", "worldwide", "unknown", "n/a", "na", "none", "", "africa",
                 "asia", "middle east", "latin america", "eu", "european union"}

_NAME2CANON: dict[str, str] = {}
_CODE2CANON: dict[str, str] = {}
for _canon, (_code, _aliases) in _COUNTRIES.items():
    _NAME2CANON[fold(_canon)] = _canon
    _CODE2CANON[_code] = _canon
    for _a in _aliases:
        if _a in ("US",):
            continue
        _NAME2CANON[fold(_a)] = _canon
_CODE2CANON["UK"] = "United Kingdom"


def norm_country(s) -> str | None:
    """Structured country field -> canonical country name (codes, demonyms, names)."""
    if s is None:
        return None
    raw = strip_brackets(str(s)).strip().strip(".,;")
    if not raw:
        return None
    if raw.upper() == raw and 2 <= len(raw) <= 3 and raw.isalpha():
        if raw in _CODE2CANON:
            return _CODE2CANON[raw]
    f = fold(raw).strip()
    if f in NOT_COUNTRIES:
        return None
    if f in _NAME2CANON:
        return _NAME2CANON[f]
    f2 = re.sub(r"^the\s+", "", f)
    if f2 in _NAME2CANON:
        return _NAME2CANON[f2]
    # "Sassari, Sassari, Italy" -> last comma part
    if "," in raw:
        return norm_country(raw.split(",")[-1])
    # unknown: keep as-is (title case) so different unknowns still differ
    return raw.strip().title() if len(raw) > 2 else None


def is_country_name(s) -> bool:
    """True only when the whole string is a known country name or demonym ("United States", "the Netherlands")."""
    f = fold(strip_brackets(str(s or ""))).strip().strip(".,;")
    return bool(f) and (f in _NAME2CANON or re.sub(r"^the\s+", "", f) in _NAME2CANON)


# free-text country finder (names + demonyms; codes are NOT used in free text)
_FT_TERMS = sorted(
    {(_a, c) for c, (_code, al) in _COUNTRIES.items() for _a in [c] + al
     if not (len(_a) <= 3 and _a.isupper())},
    key=lambda t: -len(t[0]),
)
_FT_RX = re.compile(
    r"(?<![\w])(?<!New )(" + "|".join(re.escape(t[0]) for t in _FT_TERMS) + r")(?![\w])"
)
_FT_MAP = {t[0]: t[1] for t in _FT_TERMS}


def find_countries(text: str) -> list[str]:
    if not text:
        return []
    out = []
    for m in _FT_RX.finditer(text):
        c = _FT_MAP.get(m.group(1))
        if c and c not in out:
            out.append(c)
    return out


configure_names()

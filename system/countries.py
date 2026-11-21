"""Country keys.

POLICY.md principle 6: "Codes and nationalities are countries; territories count as their
own country."  So GB, United Kingdom and British are one key, while Macao and China, or
Puerto Rico and the United States, are not.

A string the table does not know becomes an UNMAPPED key ("?" + folded text).  It still
equals itself, so the same unknown text on both sides agrees, but it is never evidence of a
difference: LOCATION_MISMATCH does not fire while either side holds one (rules.py).  A bare
unknown key would be different from every real country and so fake a mismatch.
"""

import re

from . import norm

# key, names and codes, demonyms.  The key is the name we print.
_ROWS = [
    ('Afghanistan',                      'AF AFG',    'Afghan'),
    ('Albania',                          'AL ALB',    'Albanian'),
    ('Algeria',                          'DZ DZA',    'Algerian'),
    ('Andorra',                          'AD AND',    'Andorran'),
    ('Angola',                           'AO AGO',    'Angolan'),
    ('Argentina',                        'AR ARG',    'Argentine|Argentinian|Argentinean'),
    ('Armenia',                          'AM ARM',    'Armenian'),
    ('Australia',                        'AU AUS',    'Australian'),
    ('Austria',                          'AT AUT',    'Austrian'),
    ('Azerbaijan',                       'AZ AZE',    'Azerbaijani|Azeri'),
    ('Bahamas',                          'BS BHS',    'The Bahamas|Bahamian'),
    ('Bahrain',                          'BH BHR',    'Bahraini'),
    ('Bangladesh',                       'BD BGD',    'Bangladeshi'),
    ('Barbados',                         'BB BRB',    'Barbadian'),
    ('Belarus',                          'BY BLR',    'Belarusian'),
    ('Belgium',                          'BE BEL',    'Belgian'),
    ('Belize',                           'BZ BLZ',    'Belizean'),
    ('Benin',                            'BJ BEN',    'Beninese'),
    ('Bermuda',                          'BM BMU',    'Bermudian'),
    ('Bolivia',                          'BO BOL',    'Bolivian'),
    ('Bosnia and Herzegovina',           'BA BIH',    'Bosnia|Bosnia-Herzegovina|Bosnian'),
    ('Botswana',                         'BW BWA',    'Botswanan'),
    ('Brazil',                           'BR BRA',    'Brazilian'),
    ('British Virgin Islands',           'VG VGB',    ''),
    ('Brunei',                           'BN BRN',    'Brunei Darussalam|Bruneian'),
    ('Bulgaria',                         'BG BGR',    'Bulgarian'),
    ('Burkina Faso',                     'BF BFA',    'Burkinabe'),
    ('Cambodia',                         'KH KHM',    'Cambodian'),
    ('Cameroon',                         'CM CMR',    'Cameroonian'),
    ('Canada',                           'CA CAN',    'Canadian'),
    ('Cape Verde',                       'CV CPV',    'Cabo Verde|Cape Verdean'),
    ('Cayman Islands',                   'KY CYM',    'Caymanian'),
    ('Chad',                             'TD TCD',    'Chadian'),
    ('Chile',                            'CL CHL',    'Chilean'),
    ('China',                            'CN CHN',    "People's Republic of China|PRC|Chinese"),
    ('Colombia',                         'CO COL',    'Colombian'),
    ('Costa Rica',                       'CR CRI',    'Costa Rican'),
    ("Cote D'Ivoire",                    'CI CIV',    "Ivory Coast|Côte d'Ivoire|Cote d Ivoire|Ivorian"),
    ('Croatia',                          'HR HRV',    'Croatian'),
    ('Cuba',                             'CU CUB',    'Cuban'),
    ('Curacao',                          'CW CUW',    'Curaçao'),
    ('Cyprus',                           'CY CYP',    'Cypriot'),
    ('Czech Republic',                   'CZ CZE',    'Czechia|Czech'),
    ('Democratic Republic of the Congo', 'CD COD',    'DR Congo|DRC|Congo-Kinshasa|Congolese'),
    ('Denmark',                          'DK DNK',    'Danish|Dane'),
    ('Dominican Republic',               'DO DOM',    'Dominican'),
    ('Ecuador',                          'EC ECU',    'Ecuadorian|Ecuadorean'),
    ('Egypt',                            'EG EGY',    'Egyptian'),
    ('El Salvador',                      'SV SLV',    'Salvadoran'),
    ('Eritrea',                          'ER ERI',    'Eritrean'),
    ('Estonia',                          'EE EST',    'Estonian'),
    ('Eswatini',                         'SZ SWZ',    'Swaziland|Swazi'),
    ('Ethiopia',                         'ET ETH',    'Ethiopian'),
    ('Finland',                          'FI FIN',    'Finnish|Finn'),
    ('France',                           'FR FRA',    'French'),
    ('Georgia',                          'GE GEO',    'Georgian'),
    ('Germany',                          'DE DEU',    'German'),
    ('Ghana',                            'GH GHA',    'Ghanaian'),
    ('Gibraltar',                        'GI GIB',    ''),
    ('Greece',                           'GR GRC',    'Greek'),
    ('Guatemala',                        'GT GTM',    'Guatemalan'),
    ('Guernsey',                         'GG GGY',    ''),
    ('Guinea',                           'GN GIN',    'Guinean'),
    ('Guyana',                           'GY GUY',    'Guyanese'),
    ('Haiti',                            'HT HTI',    'Haitian'),
    ('Honduras',                         'HN HND',    'Honduran'),
    ('Hong Kong',                        'HK HKG',    'Hong Kong Special Administrative Region of China|Hong Konger'),
    ('Hungary',                          'HU HUN',    'Hungarian'),
    ('Iceland',                          'IS ISL',    'Icelandic|Icelander'),
    ('India',                            'IN IND',    'Indian'),
    ('Indonesia',                        'ID IDN',    'Indonesian'),
    ('Iran',                             'IR IRN',    'Islamic Republic of Iran|Iranian'),
    ('Iraq',                             'IQ IRQ',    'Iraqi'),
    ('Ireland',                          'IE IRL',    'Republic of Ireland|Irish'),
    ('Isle of Man',                      'IM IMN',    'Manx'),
    ('Israel',                           'IL ISR',    'Israeli'),
    ('Italy',                            'IT ITA',    'Italian'),
    ('Jamaica',                          'JM JAM',    'Jamaican'),
    ('Japan',                            'JP JPN',    'Japanese'),
    ('Jersey',                           'JE JEY',    ''),
    ('Jordan',                           'JO JOR',    'Jordanian'),
    ('Kazakhstan',                       'KZ KAZ',    'Kazakh|Kazakhstani'),
    ('Kenya',                            'KE KEN',    'Kenyan'),
    ('Kosovo',                           'XK XKX',    'Kosovar|Kosovan'),
    ('Kuwait',                           'KW KWT',    'Kuwaiti'),
    ('Kyrgyzstan',                       'KG KGZ',    'Kyrgyz'),
    ('Laos',                             'LA LAO',    'Laotian'),
    ('Latvia',                           'LV LVA',    'Latvian'),
    ('Lebanon',                          'LB LBN',    'Lebanese'),
    ('Liberia',                          'LR LBR',    'Liberian'),
    ('Libya',                            'LY LBY',    'Libyan'),
    ('Liechtenstein',                    'LI LIE',    ''),
    ('Lithuania',                        'LT LTU',    'Lithuanian'),
    ('Luxembourg',                       'LU LUX',    'Luxembourgish'),
    ('Macao',                            'MO MAC',    'Macau|Macao Special Administrative Region of China|Macanese'),
    ('Madagascar',                       'MG MDG',    'Malagasy'),
    ('Malawi',                           'MW MWI',    'Malawian'),
    ('Malaysia',                         'MY MYS',    'Malaysian'),
    ('Maldives',                         'MV MDV',    'Maldivian'),
    ('Mali',                             'ML MLI',    'Malian'),
    ('Malta',                            'MT MLT',    'Maltese'),
    ('Mauritius',                        'MU MUS',    'Mauritian'),
    ('Mexico',                           'MX MEX',    'Mexican'),
    ('Moldova',                          'MD MDA',    'Republic of Moldova|Moldovan'),
    ('Monaco',                           'MC MCO',    'Monegasque'),
    ('Mongolia',                         'MN MNG',    'Mongolian'),
    ('Montenegro',                       'ME MNE',    'Montenegrin'),
    ('Morocco',                          'MA MAR',    'Moroccan'),
    ('Mozambique',                       'MZ MOZ',    'Mozambican'),
    ('Myanmar',                          'MM MMR',    'Burma|Burmese'),
    ('Namibia',                          'NA NAM',    'Namibian'),
    ('Nepal',                            'NP NPL',    'Nepalese|Nepali'),
    ('Netherlands',                      'NL NLD',    'Holland|The Netherlands|Dutch|Netherlander'),
    ('New Zealand',                      'NZ NZL',    'New Zealander'),
    ('Nicaragua',                        'NI NIC',    'Nicaraguan'),
    ('Niger',                            'NE NER',    'Nigerien'),
    ('Nigeria',                          'NG NGA',    'Nigerian'),
    ('North Korea',                      'KP PRK',    "Democratic People's Republic of Korea|DPRK|North Korean"),
    ('North Macedonia',                  'MK MKD',    'Macedonia|Macedonian'),
    ('Northern Mariana Islands',         'MP MNP',    ''),
    ('Norway',                           'NO NOR',    'Norwegian'),
    ('Oman',                             'OM OMN',    'Omani'),
    ('Pakistan',                         'PK PAK',    'Pakistani'),
    ('Palestine',                        'PS PSE',    'Palestina|State of Palestine|Palestinian'),
    ('Panama',                           'PA PAN',    'Panamanian'),
    ('Papua New Guinea',                 'PG PNG',    'Papua New Guinean'),
    ('Paraguay',                         'PY PRY',    'Paraguayan'),
    ('Peru',                             'PE PER',    'Peruvian'),
    ('Philippines',                      'PH PHL',    'The Philippines|Filipino|Philippine'),
    ('Poland',                           'PL POL',    'Polish|Pole'),
    ('Portugal',                         'PT PRT',    'Portuguese'),
    ('Puerto Rico',                      'PR PRI',    'Puerto Rican'),
    ('Qatar',                            'QA QAT',    'Qatari'),
    ('Republic of the Congo',            'CG COG',    'Congo|Congo-Brazzaville'),
    ('Romania',                          'RO ROU',    'Romanian'),
    ('Russia',                           'RU RUS',    'Russian Federation|Russian'),
    ('Rwanda',                           'RW RWA',    'Rwandan'),
    ('Saudi Arabia',                     'SA SAU',    'Saudi Arabian|Saudi'),
    ('Senegal',                          'SN SEN',    'Senegalese'),
    ('Serbia',                           'RS SRB',    'Serbian|Serb'),
    ('Seychelles',                       'SC SYC',    'Seychellois'),
    ('Sierra Leone',                     'SL SLE',    'Sierra Leonean'),
    ('Singapore',                        'SG SGP',    'Singaporean'),
    ('Slovakia',                         'SK SVK',    'Slovak'),
    ('Slovenia',                         'SI SVN',    'Slovenian|Slovene'),
    ('Somalia',                          'SO SOM',    'Somali'),
    ('South Africa',                     'ZA ZAF',    'South African'),
    ('South Korea',                      'KR KOR',    'Republic of Korea|Korea|South Korean|Korean'),
    ('South Sudan',                      'SS SSD',    'South Sudanese'),
    ('Spain',                            'ES ESP',    'Spanish|Spaniard'),
    ('Sri Lanka',                        'LK LKA',    'Sri Lankan'),
    ('Sudan',                            'SD SDN',    'Sudanese'),
    ('Sweden',                           'SE SWE',    'Swedish|Swede'),
    ('Switzerland',                      'CH CHE',    'Swiss'),
    ('Syria',                            'SY SYR',    'Syrian Arab Republic|Syrian'),
    ('Taiwan',                           'TW TWN',    'Taiwanese'),
    ('Tajikistan',                       'TJ TJK',    'Tajik'),
    ('Tanzania',                         'TZ TZA',    'Tanzanian'),
    ('Thailand',                         'TH THA',    'Thai'),
    ('Trinidad and Tobago',              'TT TTO',    'Trinidadian|Tobagonian'),
    ('Tunisia',                          'TN TUN',    'Tunisian'),
    ('Turkey',                           'TR TUR',    'Turkiye|Türkiye|Turkish|Turk'),
    ('Turkmenistan',                     'TM TKM',    'Turkmen'),
    ('Uganda',                           'UG UGA',    'Ugandan'),
    ('Ukraine',                          'UA UKR',    'Ukrainian'),
    ('United Arab Emirates',             'AE ARE',    'UAE|Emirates|Emirati'),
    ('United Kingdom',                   'GB GBR',    'UK|Great Britain|England|Scotland|Wales|Northern Ireland|British|Briton|Welsh|Scottish|English'),
    ('United States',                    'US USA',    'U.S.|U.S.A.|United States of America|USA|American'),
    ('Uruguay',                          'UY URY',    'Uruguayan'),
    ('Uzbekistan',                       'UZ UZB',    'Uzbek'),
    ('Venezuela',                        'VE VEN',    'Venezuelan'),
    ('Vietnam',                          'VN VNM',    'Viet Nam|Vietnamese'),
    ('Yemen',                            'YE YEM',    'Yemeni'),
    ('Zambia',                           'ZM ZMB',    'Zambian'),
    ('Zimbabwe',                         'ZW ZWE',    'Zimbabwean'),
    # small states and territories the table lacked (territories count as their own country)
    ('Antigua and Barbuda',              'AG ATG',    'Antiguan'),
    ('Saint Kitts and Nevis',            'KN KNA',    'St Kitts and Nevis|St. Kitts and Nevis'),
    ('Saint Lucia',                      'LC LCA',    'St Lucia|St. Lucia|Saint Lucian'),
    ('Saint Vincent and the Grenadines', 'VC VCT',    'St Vincent and the Grenadines|St. Vincent and the Grenadines'),
    ('Timor-Leste',                      'TL TLS',    'Timor Leste|East Timor|Timorese'),
    ('Holy See',                         'VA VAT',    'Vatican|Vatican City|Vatican City State'),
    ('San Marino',                       'SM SMR',    'Sammarinese'),
    ('Samoa',                            'WS WSM',    'Samoan'),
    ('Tonga',                            'TO TON',    'Tongan'),
    ('Vanuatu',                          'VU VUT',    ''),
    ('Solomon Islands',                  'SB SLB',    ''),
    ('Kiribati',                         'KI KIR',    ''),
    ('Nauru',                            'NR NRU',    ''),
    ('Tuvalu',                           'TV TUV',    ''),
    ('Palau',                            'PW PLW',    ''),
    ('Marshall Islands',                 'MH MHL',    ''),
    ('Micronesia',                       'FM FSM',    'Federated States of Micronesia|Micronesia, Federated States of'),
    ('Sao Tome and Principe',            'ST STP',    ''),
    ('Dominica',                         'DM DMA',    ''),
    ('Grenada',                          'GD GRD',    'Grenadian'),
    ('Bhutan',                           'BT BTN',    'Bhutanese'),
    ('Comoros',                          'KM COM',    ''),
    ('Djibouti',                         'DJ DJI',    ''),
    ('Lesotho',                          'LS LSO',    ''),
    ('Guinea-Bissau',                    'GW GNB',    'Guinea Bissau'),
    ('Equatorial Guinea',                'GQ GNQ',    ''),
    ('Western Sahara',                   'EH ESH',    ''),
    ('Falkland Islands',                 'FK FLK',    ''),
    ('Reunion',                          'RE REU',    ''),
    ('Martinique',                       'MQ MTQ',    ''),
    ('Guadeloupe',                       'GP GLP',    ''),
    ('French Guiana',                    'GF GUF',    ''),
    ('Mayotte',                          'YT MYT',    ''),
    ('Sint Maarten',                     'SX SXM',    ''),
    ('Cook Islands',                     'CK COK',    ''),
    ('Aruba',                            'AW ABW',    ''),
    ('Greenland',                        'GL GRL',    ''),
    ('Turks and Caicos Islands',         'TC TCA',    ''),
    ('Anguilla',                         'AI AIA',    ''),
    ('Montserrat',                       'MS MSR',    ''),
    ('US Virgin Islands',                'VI VIR',    'U.S. Virgin Islands|Virgin Islands, U.S.'),
    ('Guam',                             'GU GUM',    ''),
    ('American Samoa',                   'AS ASM',    ''),
    ('New Caledonia',                    'NC NCL',    ''),
    ('French Polynesia',                 'PF PYF',    ''),
    ('Faroe Islands',                    'FO FRO',    ''),
]

# Territories: a place string that names one of these and its parent state belongs to the
# territory ("Hong Kong, China"), which POLICY counts as its own country.
TERRITORIES = frozenset([
    'Hong Kong', 'Macao', 'Taiwan', 'Puerto Rico', 'Jersey', 'Guernsey', 'Isle of Man', 'Gibraltar',
    'Bermuda', 'Cayman Islands', 'British Virgin Islands', 'US Virgin Islands', 'Northern Mariana Islands',
    'Guam', 'American Samoa', 'Greenland', 'Faroe Islands', 'Aruba', 'Curacao', 'New Caledonia',
    'French Polynesia', 'Anguilla', 'Montserrat', 'Turks and Caicos Islands', 'Western Sahara',
    'Falkland Islands', 'Reunion', 'Martinique', 'Guadeloupe', 'French Guiana', 'Mayotte', 'Sint Maarten',
    'Cook Islands', 'Kosovo', 'Palestine',
])

# Words that only describe a state's form: "Iran, Islamic Republic of", "Kingdom of Saudi
# Arabia", "Republic of Turkey".
_FORM_WORDS = re.compile(
    r"\b(republic|kingdom|state|states|province|federation|federal|people s|peoples|people|islamic|"
    r"democratic|plurinational|bolivarian|united|arab|socialist|commonwealth|principality|"
    r"sultanate|of|the)\b"
)
_FORM_PREFIX = re.compile(
    r"^(?:the )?(?:(?:islamic|federal|democratic|socialist|people s|peoples|united|arab) )*"
    r"(?:republic|kingdom|state|commonwealth|federation|principality|sultanate|emirate) of (?:the )?"
)

UNMAPPED = "?"


def is_unmapped(k):
    return bool(k) and k.startswith(UNMAPPED)

# POLICY.md principle 5: ""International" and "Europe" are not countries."  Regions and
# continents are not countries either, so they never tie an entity to a place.
NOT_COUNTRIES = frozenset(
    norm.fold(x)
    for x in [
        "international",
        "europe",
        "european union",
        "eu",
        "africa",
        "asia",
        "north america",
        "south america",
        "latin america",
        "central america",
        "middle east",
        "caribbean",
        "oceania",
        "worldwide",
        "global",
        "unknown",
        "n/a",
        "na",
        "none",
        "various",
        "multiple",
    ]
)

# "NA" reaches us as a placeholder for a missing value far more often than as Namibia's
# code, and reading it as a country could invent a country difference.  NOT_COUNTRIES
# already covers it; this is the note that the omission is deliberate.
_AMBIGUOUS_CODES = frozenset(["na"])

_LOOKUP = {}


def _add(key, text):
    folded = norm.fold(text)
    if not folded or folded in NOT_COUNTRIES:
        return
    if len(folded) <= 3 and folded in _AMBIGUOUS_CODES:
        return
    _LOOKUP.setdefault(folded, key)
    # also index a punctuation-free form, so "U.S.A." and "Cote d Ivoire" both land
    bare = " ".join(norm.words(text))
    if bare and bare != folded:
        _LOOKUP.setdefault(bare, key)


for _key, _codes, _extras in _ROWS:
    _add(_key, _key)
    for _code in _codes.split():
        _add(_key, _code)
    # Extra names and nationality adjectives, each a whole string: splitting them on
    # spaces would index "United" on its own and make "United Kingdom" a United States.
    for _extra in _extras.split("|"):
        _add(_key, _extra)

KNOWN_NAMES = sorted({k for k, _c, _e in _ROWS})


def key(text):
    """One country key for a country name, code or nationality.  None when it is not a
    country at all (a region, a placeholder, or empty)."""
    if not text:
        return None
    folded = norm.fold(text)
    if not folded or folded in NOT_COUNTRIES:
        return None
    if folded in _LOOKUP:
        return _LOOKUP[folded]
    bare = " ".join(norm.words(text))
    if bare in _LOOKUP:
        return _LOOKUP[bare]
    if bare in NOT_COUNTRIES:
        return None
    if not bare or not re.search(r"[a-z]", bare):
        return None
    stripped = _FORM_PREFIX.sub("", bare)
    if stripped != bare and stripped in _LOOKUP:
        return _LOOKUP[stripped]
    # Unknown to the table: an UNMAPPED key.  It equals only itself, and it never counts
    # as a difference (see the module docstring).
    return UNMAPPED + bare


def key_from_place(text):
    """A country key from a place that may name a city and region first.

    Tries the whole string, then its last comma-separated piece, which is how hit
    addresses and places of birth name their country.
    """
    if not text:
        return None
    whole = norm.fold(norm.drop_brackets(text))
    if whole in _LOOKUP:
        return _LOOKUP[whole]
    cleaned = norm.drop_brackets(text or "").strip().strip(".,;")
    pieces = [p.strip() for p in cleaned.split(",") if p.strip()]
    # a trailing postcode is not the country: "..., Lagos, Nigeria, 100001"
    while len(pieces) > 1 and any(ch.isdigit() for ch in pieces[-1]):
        pieces.pop()
    if not pieces:
        return None
    found = [_known(p) for p in pieces]
    # "Hong Kong, China": the territory is the place, not its parent state
    for k in found:
        if k in TERRITORIES:
            return k
    # "Iran, Islamic Republic of": the other pieces only describe the state's form
    if found[0] and all(not _FORM_WORDS.sub("", " ".join(norm.words(p))).strip() for p in pieces[1:]):
        return found[0]
    # "Sassari, Sassari, Italy": the country is named last
    if found[-1]:
        return found[-1]
    # Nothing recognisable: key() gives None for "not a country" or an UNMAPPED key, never
    # a bare string that would differ from every real country.
    return key(pieces[-1])


def _known(text):
    """A known country key for one piece of text, or None."""
    k = key(text)
    return k if k and not is_unmapped(k) else None


def mentioned_in(text, keys=None):
    """Which countries a free-text sentence names.

    Only full country names and multi-word demonyms are looked for, never two-letter
    codes, so that "as" or "co" inside a sentence cannot be read as a country.
    """
    if not text:
        return []
    folded = norm.fold(text)
    found = []
    for name, target in _NAME_PATTERNS:
        if target in found:
            continue
        if keys is not None and target not in keys:
            continue
        if name.search(folded):
            found.append(target)
    return found


def _name_patterns():
    out = []
    seen = set()
    for folded, target in _LOOKUP.items():
        if len(folded) < 4:
            continue  # too short to look for inside a sentence
        if folded in seen:
            continue
        seen.add(folded)
        out.append((re.compile(r"(?<![a-z])%s(?![a-z])" % re.escape(folded)), target))
    # longest first, so "united states" is found before "united"
    out.sort(key=lambda pair: -len(pair[0].pattern))
    return out


_NAME_PATTERNS = _name_patterns()


def display(keys):
    """Country keys as the reason text should list them: sorted, comma separated."""
    shown = []
    for k in sorted(set(k for k in keys if k)):
        shown.append("%s (an unrecognised place)" % k[len(UNMAPPED):] if is_unmapped(k) else k)
    return ", ".join(shown)

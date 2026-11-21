"""Table definitions: which tables exist, how to recognise them, how to shape them.

The data room holds one JSON Lines file per table.  A table is recognised by its
filename and, failing that, by the fields its records carry, so a renamed file in the
unseen set is not a total failure.
"""

ALERTS = "alerts"
HITS = "hits"
CUSTOMERS = "customers"
ACCOUNTS = "accounts"
ONBOARDING = "onboarding"
KYC_CHECKS = "kyc_checks"
NOTES = "notes"
SEARCH_RESULTS = "search_results"
PRACTICE_LABELS = "practice_labels"


class Table(object):
    """How to recognise one table and how to normalise its records."""

    def __init__(self, name, required, multi=(), flatten=None, aliases=None):
        self.name = name
        self.required = frozenset(required)
        self.multi = frozenset(multi)
        # nested object -> {key inside it: field name we use}
        self.flatten = dict(flatten or {})
        # field name as written in the file -> field name we use
        self.aliases = dict(aliases or {})

    def matches(self, fields):
        return self.required <= fields

    def __repr__(self):
        return "Table(%s)" % self.name


# Ordered most-specific first, so onboarding is not mistaken for accounts, whose required
# fields are a subset of onboarding's.
TABLES = [
    Table(ONBOARDING, required=["account_id", "customer_id", "kyc_applicant_id"]),
    Table(
        ALERTS,
        required=["alert_id", "hit_ids"],
        multi=["hit_ids"],
        # The screened details arrive nested: {"customer": {"name": ..., "dob": ...}}.
        flatten={
            "customer": {
                "name": "customer_name",
                "entity_type": "entity_type",
                "dob": "dob",
                "country": "country",
                "city": "city",
            }
        },
    ),
    Table(
        HITS,
        required=["hit_id", "alert_id", "name"],
        multi=[
            "aliases",
            "dobs",
            "nationality",
            "citizenship",
            "countries",
            "addresses",
            "identifiers",
            "categories",
            "subcategories",
            "relationships",
            "sources",
            "source_urls",
        ],
    ),
    Table(CUSTOMERS, required=["record_id", "full_name", "email"]),
    Table(KYC_CHECKS, required=["check_id", "applicant_id", "result"]),
    Table(NOTES, required=["note_id", "requester_email", "text"]),
    Table(SEARCH_RESULTS, required=["result_id", "query", "snippet"]),
    Table(
        PRACTICE_LABELS,
        required=["hit_id", "decision"],
        multi=["reason_codes", "customer_record_ids", "evidence", "path"],
        aliases={
            "reason_code": "reason_codes",
            "customer_record_id": "customer_record_ids",
            "reason": "reference_reason",
        },
    ),
    Table(ACCOUNTS, required=["account_id", "customer_id"]),
]

TABLES_BY_NAME = {t.name: t for t in TABLES}

# Filename stems that name a table.  Checked before the field signatures.
FILENAME_HINTS = [
    ("practice", PRACTICE_LABELS),
    ("label", PRACTICE_LABELS),
    ("onboarding", ONBOARDING),
    ("alert", ALERTS),
    ("hit", HITS),
    ("customer", CUSTOMERS),
    ("account", ACCOUNTS),
    ("kyc", KYC_CHECKS),
    ("note", NOTES),
    ("search", SEARCH_RESULTS),
]

DECISIONS = ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")

# POLICY.md's reason-code table, and which decision each code belongs to.
REASON_CODES = {
    "TEMPORAL_IMPOSSIBILITY": "DIFFERENT_ENTITY",
    "DOB_MISMATCH": "DIFFERENT_ENTITY",
    "LOCATION_MISMATCH": "DIFFERENT_ENTITY",
    "NAME_MISMATCH_VERIFIED": "DIFFERENT_ENTITY",
    "ENTITY_TYPE_MISMATCH": "DIFFERENT_ENTITY",
    "DECEASED": "DIFFERENT_ENTITY",
    "NAME_DOB_LOCATION_MATCH": "SAME_ENTITY",
    "NAME_DOB_MATCH": "SAME_ENTITY",
    "NAME_LOCATION_MATCH": "SAME_ENTITY",
    "INSUFFICIENT_DATA": "REVIEW",
    "AMBIGUOUS_CUSTOMER_RECORD": "REVIEW",
}

# Fixed order so a hit that satisfies several codes always reports the same one
# (decision log D14).  POLICY.md accepts any applicable code; reproducibility is scored.
CODE_ORDER = [
    "ENTITY_TYPE_MISMATCH",
    "DECEASED",
    "TEMPORAL_IMPOSSIBILITY",
    "DOB_MISMATCH",
    "LOCATION_MISMATCH",
    "NAME_MISMATCH_VERIFIED",
    "NAME_DOB_LOCATION_MATCH",
    "NAME_DOB_MATCH",
    "NAME_LOCATION_MATCH",
    "AMBIGUOUS_CUSTOMER_RECORD",
    "INSUFFICIENT_DATA",
]

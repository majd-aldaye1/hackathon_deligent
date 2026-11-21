"""Read the data folder into tables and indexes.

Reads only the folder it is given, one JSON Lines file per table.  Records are normalised
to a single shape — plain strings for scalars, lists of strings for the multi-valued
fields — so nothing downstream has to care that the provider writes `null` for an absent
value, nests the screened customer details inside an object, or sends numbers as numbers.
"""

import json
import os
import re
from collections import defaultdict

from . import model

DATA_SUFFIXES = (".jsonl", ".ndjson", ".json")


class DataError(Exception):
    pass


# --------------------------------------------------------------------------- reading


def _read_records(path):
    """JSON Lines, or a single JSON array for a folder that ships one."""
    with open(path, "r", encoding="utf-8") as fh:
        head = fh.read(64).lstrip()
        fh.seek(0)
        if head.startswith("["):
            data = json.load(fh)
            return [r for r in data if isinstance(r, dict)]
        out = []
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                out.append(record)
    return out


# ------------------------------------------------------------------- identify + clean


def _identify(path, records):
    """Which table is this file?  The filename first, then the fields it carries."""
    if not records:
        return None
    stem = re.sub(r"[^a-z]", "", os.path.basename(path).lower())
    fields = set()
    for record in records[:50]:
        fields |= set(record)
    candidates = [t for t in model.TABLES if t.matches(fields)]
    if not candidates:
        return None
    for hint, name in model.FILENAME_HINTS:
        if hint in stem:
            for table in candidates:
                if table.name == name:
                    return table
    # No usable filename: the most specific signature wins.  TABLES is ordered that way.
    return candidates[0]


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(t for t in (_as_text(v) for v in value) if t)
    if isinstance(value, dict):
        # A hit's `details` is {"pep": "...", "sanctions": "..."}; keep it readable and
        # keep the keys, which name the kind of listing the text describes.
        return "\n".join(
            "%s: %s" % (key, _as_text(value[key])) for key in sorted(value) if _as_text(value[key])
        )
    return str(value)


def _as_list(value):
    """A multi-valued field, given as a list or as a "; "-joined string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [_as_text(v) for v in value]
    elif isinstance(value, str):
        items = [p.strip() for p in value.split(";")]
    else:
        items = [_as_text(value)]
    return [i for i in items if i]


def _clean(table, records):
    out = []
    for raw in records:
        record = {}
        for key, value in raw.items():
            key = table.aliases.get(key, key)
            if key in table.flatten:
                mapping = table.flatten[key]
                nested = value if isinstance(value, dict) else {}
                for inner, target in mapping.items():
                    record[target] = _as_text(nested.get(inner))
                continue
            if key in table.multi:
                record[key] = _as_list(value)
            else:
                record[key] = _as_text(value)
        for mapping in table.flatten.values():
            for target in mapping.values():
                record.setdefault(target, "")
        for key in table.multi:
            record.setdefault(key, [])
        out.append(record)
    return out


# -------------------------------------------------------------------------- the data

REQUIRED_TABLES = (
    model.ALERTS,
    model.HITS,
    model.CUSTOMERS,
    model.ACCOUNTS,
    model.ONBOARDING,
    model.KYC_CHECKS,
)


class Dataset(object):
    """Every table in the folder, plus the indexes the resolver and gatherer need."""

    def __init__(self, folder):
        self.folder = folder
        self.tables = {name: [] for name in model.TABLES_BY_NAME}
        self.files = {}
        self.policy_text = ""
        self.name_variants_raw = None
        self._name_index = None
        self._load()
        self._index()

    # -- loading

    def _load(self):
        if not os.path.isdir(self.folder):
            raise DataError("not a folder: %s" % self.folder)
        for entry in sorted(os.listdir(self.folder)):
            path = os.path.join(self.folder, entry)
            if not os.path.isfile(path):
                continue
            low = entry.lower()
            if low.endswith(".md"):
                with open(path, encoding="utf-8") as fh:
                    self.policy_text += fh.read()
                continue
            if "name_variant" in low and low.endswith(".json"):
                with open(path, encoding="utf-8") as fh:
                    self.name_variants_raw = json.load(fh)
                continue
            if not low.endswith(DATA_SUFFIXES):
                continue
            try:
                records = _read_records(path)
            except (ValueError, UnicodeDecodeError):
                continue
            table = _identify(path, records)
            if table is None:
                continue
            self.tables[table.name].extend(_clean(table, records))
            self.files.setdefault(table.name, []).append(entry)
        missing = [name for name in REQUIRED_TABLES if not self.tables[name]]
        if missing:
            raise DataError(
                "no file in %s holds these tables: %s" % (self.folder, ", ".join(missing))
            )

    # -- indexes

    def _index(self):
        self.alerts = self.tables[model.ALERTS]
        self.hits = self.tables[model.HITS]
        self.customers = self.tables[model.CUSTOMERS]
        self.accounts = self.tables[model.ACCOUNTS]
        self.onboarding = self.tables[model.ONBOARDING]
        self.kyc_checks = self.tables[model.KYC_CHECKS]
        self.notes = self.tables[model.NOTES]
        self.search_results = self.tables[model.SEARCH_RESULTS]
        self.practice_labels = self.tables[model.PRACTICE_LABELS]

        self.alert_by_id = {a["alert_id"]: a for a in self.alerts}
        self.hit_by_id = {h["hit_id"]: h for h in self.hits}
        self.hits_by_alert = _group(self.hits, "alert_id")

        self.customer_by_id = {c["record_id"]: c for c in self.customers}
        self.customers_by_email = _group(self.customers, "email", lower=True)

        self.accounts_by_id = _group(self.accounts, "account_id")
        self.accounts_by_login = _group(self.accounts, "login_handle")
        self.accounts_by_customer = _group(self.accounts, "customer_id")

        self.onboarding_by_account_customer = {}
        for row in self.onboarding:
            key = (row.get("account_id", ""), row.get("customer_id", ""))
            self.onboarding_by_account_customer.setdefault(key, []).append(row)
        self.onboarding_by_customer = _group(self.onboarding, "customer_id")

        self.kyc_by_applicant = _group(self.kyc_checks, "applicant_id")
        self.notes_by_email = _group(self.notes, "requester_email", lower=True)
        self.search_by_query = _group(self.search_results, "query", lower=True)

    # -- blocking index, built on demand so the tokeniser stays in system/names.py

    def name_index(self, tokenize):
        """token -> sorted list of customer record_ids whose names contain that token."""
        if self._name_index is None:
            index = defaultdict(set)
            for cust in self.customers:
                company = cust.get("entity_type", "") == "Company"
                for field in ("full_name", "preferred_name", "login_name"):
                    for token in tokenize(cust.get(field, ""), company):
                        index[token].add(cust["record_id"])
            self._name_index = {k: sorted(v) for k, v in index.items()}
        return self._name_index

    def counts(self):
        return {name: len(rows) for name, rows in sorted(self.tables.items())}


def _group(rows, key, lower=False):
    out = defaultdict(list)
    for row in rows:
        value = row.get(key, "")
        if not value:
            continue
        out[value.lower() if lower else value].append(row)
    return dict(out)


def load(folder):
    return Dataset(folder)

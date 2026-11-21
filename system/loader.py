"""Read a data folder into tables and indexes.

Reads only the folder it is given.  Accepts JSON Lines (the format the brief specifies)
and CSV (the format of the read-only workbook export we developed against), and decides
what each file is from the fields its records carry rather than from its filename.
"""

import csv
import json
import os
import re
from collections import defaultdict

from . import model

csv.field_size_limit(1 << 30)

DATA_SUFFIXES = (".jsonl", ".ndjson", ".json", ".csv", ".tsv")


class DataError(Exception):
    pass


# --------------------------------------------------------------------------- reading


def _read_jsonl(path):
    with open(path, "r", encoding="utf-8") as fh:
        first = fh.read(1)
        while first and first.isspace():
            first = fh.read(1)
        fh.seek(0)
        if first == "[":  # a single JSON array, not JSON Lines
            data = json.load(fh)
            return [r for r in data if isinstance(r, dict)]
        out = []
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _read_sep(path, delimiter):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=delimiter))
    # The workbook export puts prose above the header on some tabs, so take the first
    # row that looks like a header: several non-empty cells, all distinct.
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row]
        named = [c for c in cells if c]
        if len(named) >= 2 and len(set(named)) == len(named):
            header = cells
            body = rows[i + 1 :]
            break
    else:
        return []
    out = []
    for row in body:
        if not any(c.strip() for c in row):
            continue
        rec = {}
        for j, key in enumerate(header):
            if key:
                rec[key] = row[j] if j < len(row) else ""
        out.append(rec)
    return out


def _read_records(path):
    low = path.lower()
    if low.endswith(".tsv"):
        return _read_sep(path, "\t")
    if low.endswith(".csv"):
        return _read_sep(path, ",")
    return _read_jsonl(path)


# ------------------------------------------------------------------- identify + clean


def _identify(path, records):
    """Which table is this file?  Decided by fields, with the filename only as a tie-break."""
    if not records:
        return None
    fields = set()
    for rec in records[:50]:
        fields |= set(rec)
    candidates = [t for t in model.TABLES if t.matches(fields)]
    if not candidates:
        return None
    if len(candidates) > 1:
        stem = re.sub(r"[^a-z]", "", os.path.basename(path).lower())
        for hint, name in model.FILENAME_HINTS:
            if hint in stem:
                for t in candidates:
                    if t.name == name:
                        return t
        # Otherwise the most specific match wins; TABLES is ordered that way already.
        candidates.sort(key=lambda t: -len(t.required))
    return candidates[0]


def _split_multi(value):
    """A multi-valued field, given as a list or as a "; "-joined string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value]
    elif isinstance(value, str):
        items = [p.strip() for p in value.split(";")]
    else:
        items = [str(value).strip()]
    return [i for i in items if i]


def _clean(table, records):
    """One shape for every record: strings for scalars, lists for multi-valued fields."""
    out = []
    for raw in records:
        rec = {}
        for key, value in raw.items():
            key = table.aliases.get(key, key)
            if key in table.multi:
                rec[key] = _split_multi(value)
            elif value is None:
                rec[key] = ""
            elif isinstance(value, (list, tuple)):
                rec[key] = "; ".join(str(v).strip() for v in value if str(v).strip())
            elif isinstance(value, bool):
                rec[key] = "true" if value else "false"
            elif isinstance(value, str):
                rec[key] = value.strip()
            else:
                rec[key] = str(value)
        for key in table.multi:
            rec.setdefault(key, [])
        out.append(rec)
    return out


# -------------------------------------------------------------------------- the data


class Dataset:
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
            if low.endswith(".md") or low == "policy":
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
        missing = [
            n
            for n in (
                model.ALERTS,
                model.HITS,
                model.CUSTOMERS,
                model.ACCOUNTS,
                model.ONBOARDING,
                model.KYC_CHECKS,
            )
            if not self.tables[n]
        ]
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

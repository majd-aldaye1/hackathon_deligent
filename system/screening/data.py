"""Load the data room (dev/*.jsonl, the source of truth) or the CSV browse export, and index it."""
from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import text as T

csv.field_size_limit(10**9)

TABLES = {
    "alerts": ["alert"],
    "hits": ["hit"],
    "customers": ["customer"],
    "accounts": ["account"],
    "onboarding": ["onboard"],
    "kyc": ["kyc"],
    "notes": ["note"],
    "search": ["search"],
    "labels": ["label", "practice"],
}


def _table_for(fname: str) -> str | None:
    f = re.sub(r"[^a-z]", "", os.path.basename(fname).lower())
    for t, keys in TABLES.items():
        if any(k in f for k in keys):
            # "hits" also appears in words like "start here"? guard a few collisions
            if t == "hits" and ("search" in f or "practice" in f or "label" in f):
                continue
            if t == "accounts" and "onboard" in f:
                continue
            return t
    return None


def as_list(v) -> list:
    """Multi-valued fields: JSON arrays, or '; '-joined strings in the CSV export."""
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                out.append(x)
            elif x is not None and str(x).strip():
                out.append(x if not isinstance(x, str) else x.strip())
        return out
    if isinstance(v, dict):
        return [v]
    s = str(v).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(";") if p.strip()]


def s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def _read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _parse_variants_json(obj):
    groups, forms = [], []

    containers = {"groups", "variants", "given_names", "given_name_variants", "names", "name_variants",
                  "name_groups", "variant_groups", "given", "first_names", "data", "items"}

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k.lower())
        elif isinstance(o, list):
            if o and all(isinstance(x, str) for x in o):
                if "legal" in key or "form" in key or "compan" in key:
                    forms.extend(o)
                elif key and key.isalpha() and key not in containers:
                    groups.append([key] + o)   # {"muhammad": ["mohammed", ...]}
                else:
                    groups.append(o)
            elif o and all(isinstance(x, str) for x in o if not isinstance(x, list)) and len(o) == 1 and isinstance(o[0], str):
                groups.append(o)
            else:
                for x in o:
                    walk(x, key)
        elif isinstance(o, str) and ("legal" in key or "form" in key):
            forms.extend(w.strip() for w in o.split(","))

    walk(obj)
    return groups or None, forms or None


_SCREENED_KEYS = {
    "customer_name": ("name", "customer_name", "full_name", "screened_name"),
    "entity_type": ("entity_type", "type"),
    "dob": ("dob", "date_of_birth", "birth_date"),
    "country": ("country",),
    "city": ("city",),
}


def flatten_screened(alert: dict) -> dict:
    """The data room nests the customer as screened under `customer` ({name, entity_type, dob,
    country, city}); the CSV export has them as top-level columns. Expose both the same way."""
    nested = None
    for key in ("customer", "screened", "screened_customer", "subject"):
        if isinstance(alert.get(key), dict):
            nested = alert[key]
            break
    if nested is None:
        return alert
    for flat, options in _SCREENED_KEYS.items():
        if s(alert.get(flat)):
            continue
        for o in options:
            if s(nested.get(o)):
                alert[flat] = nested[o]
                break
    return alert


@dataclass
class Dataset:
    alerts: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    customers: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    onboarding: list = field(default_factory=list)
    kyc: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    search: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    source: str = ""

    def build(self):
        for a in self.alerts:
            flatten_screened(a)
        self.hit_by_id = {s(h.get("hit_id")): h for h in self.hits}
        self.alert_by_id = {s(a.get("alert_id")): a for a in self.alerts}
        self.cust_by_id = {s(c.get("record_id")): c for c in self.customers}
        self.cust_by_email = defaultdict(list)
        self.cust_by_login = defaultdict(list)
        for c in self.customers:
            e = s(c.get("email")).lower()
            if e:
                self.cust_by_email[e].append(s(c.get("record_id")))
            ln = s(c.get("login_name")).lower()
            if ln:
                self.cust_by_login[ln].append(s(c.get("record_id")))
        self.acc_by_id = defaultdict(list)
        self.acc_by_login = defaultdict(list)
        self.acc_by_cust = defaultdict(list)
        for a in self.accounts:
            self.acc_by_id[s(a.get("account_id"))].append(a)
            lh = s(a.get("login_handle")).lower()
            if lh:
                self.acc_by_login[lh].append(a)
            self.acc_by_cust[s(a.get("customer_id"))].append(a)
        self.onb_by_cust = defaultdict(list)
        for o in self.onboarding:
            self.onb_by_cust[s(o.get("customer_id"))].append(o)
        self.kyc_by_app = defaultdict(list)
        for k in self.kyc:
            self.kyc_by_app[s(k.get("applicant_id"))].append(k)
        self.notes_by_email = defaultdict(list)
        for n in self.notes:
            self.notes_by_email[s(n.get("requester_email")).lower()].append(n)
        self.search_by_query = defaultdict(list)
        for r in self.search:
            self.search_by_query[s(r.get("query")).lower().strip()].append(r)
        return self


def load(path: str) -> Dataset:
    """path: a dir containing dev/*.jsonl (or *.jsonl directly), or the CSV browse export."""
    if not os.path.isdir(path):
        raise SystemExit(f"data folder not found: {path}")
    ds = Dataset(source=path)
    files = []
    for root, _dirs, fnames in os.walk(path):
        for fn in fnames:
            files.append(os.path.join(root, fn))
    jsonl = [f for f in files if f.lower().endswith((".jsonl", ".ndjson"))]
    use = jsonl if jsonl else [f for f in files if f.lower().endswith(".csv")]
    for f in sorted(use):
        t = _table_for(f)
        if not t:
            continue
        rows = _read_jsonl(f) if f.lower().endswith((".jsonl", ".ndjson")) else _read_csv(f)
        getattr(ds, t).extend(rows)
    # name variants
    variants = [f for f in files if os.path.basename(f).lower() == "name_variants.json"]
    if variants:
        with open(variants[0], encoding="utf-8") as fh:
            g, fms = _parse_variants_json(json.load(fh))
        # Merge with the built-in groups (the dev set's name_variants.json) rather than replace them,
        # so a file layout the generic parser only partly understands can never lose a variant.
        T.configure_names((g or []) + [[w.strip() for w in grp.split(",")] for grp in T.DEFAULT_VARIANT_GROUPS],
                          (fms or []) + [w.strip() for w in T.DEFAULT_LEGAL_FORMS.split(",")])
    if not ds.alerts or not ds.hits:
        raise SystemExit(f"no alerts or hits found in {path}: expected alerts.jsonl and hits.jsonl "
                         f"(or the Alerts/Hits CSV export)")
    return ds.build()

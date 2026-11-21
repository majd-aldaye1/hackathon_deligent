#!/usr/bin/env python3
"""Re-derive every count in plan.md section 3 from a data folder.

A format change in the unseen set — a renamed field, a different separator, a new date
format — shows up here as a changed number instead of as a silently wrong decision.

    tools/audit.py dev

The small helpers in here are deliberately local: this is a diagnostic, and the
normalisation that decisions depend on lives in system/.  tests/ asserts the two agree.
"""

import collections
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import loader, model  # noqa: E402

LISTING_PHRASES = [
    "a sanctioned individual",
    "a politically exposed person",
    "the subject of enforcement action",
    "named in adverse media",
    "a state-owned enterprise official",
    "named on a watchlist",
]
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
DATED_REPORT = re.compile(r"^\s*According to .*?;\s*(%s)\s+(\d{1,2}),\s*(\d{4})\s*:" % MONTHS)
AGE_CUES = re.compile(
    r"\baged\s+(\d{1,3})\b"
    r"|\bage\s+of\s+(\d{1,3})\b"
    r"|\b(\d{1,3})[-\s]year[-\s]old\b"
    r"|\bwas\s+(\d{1,3})\b"
    r"|\bthen\s+(\d{1,3})\b"
    r"|,\s*(\d{1,3})\s*,"
)
DATE_FORMATS = [
    ("YYYY-MM-DD", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("DD/MM/YYYY", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
    ("D Month YYYY", re.compile(r"^\d{1,2} (%s) \d{4}$" % MONTHS)),
    ("Month D, YYYY", re.compile(r"^(%s) \d{1,2}, \d{4}$" % MONTHS)),
    ("Month YYYY", re.compile(r"^(%s) \d{4}$" % MONTHS)),
    ("YYYY-MM", re.compile(r"^\d{4}-\d{2}$")),
    ("YYYY", re.compile(r"^\d{4}$")),
]
PLACEHOLDERS = {
    "na", "n/a", "n.a.", "test", "unknown", "none", "nil", "tbd", "dummy", "sample",
    "placeholder",
}


def date_format(value):
    value = (value or "").strip()
    if not value:
        return "EMPTY"
    for name, pattern in DATE_FORMATS:
        if pattern.match(value):
            return name
    return "UNPARSED"


def strip_accents(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c))


def query_key(name):
    """The search-results key: accents and punctuation out, single letters dropped,
    duplicates kept, sorted, space-joined (decision log D11)."""
    words = re.sub(r"[^A-Za-z ]", " ", strip_accents(name)).split()
    return " ".join(sorted(w.lower() for w in words if len(w) > 1))


def is_placeholder(word):
    w = word.lower().strip(".")
    return w in PLACEHOLDERS or bool(re.fullmatch(r"[\d/.]+", w)) or bool(re.fullmatch(r"x{2,}", w))


def head(title):
    print()
    print("== %s" % title)


def main(argv):
    folder = argv[1] if len(argv) > 1 else "dev"
    data = loader.load(folder)

    head("3.1 tables")
    for name, count in data.counts().items():
        if not count:
            continue
        rows = data.tables[name]
        fields = sorted({k for r in rows[:200] for k in r})
        print("  %-16s %7d rows  %s" % (name, count, ", ".join(fields)))
        print("      files: %s" % ", ".join(data.files.get(name, [])))

    head("3.2 joins")
    print("  accounts: %d ids, %s customers per id"
          % (len(data.accounts_by_id),
             dict(collections.Counter(len({a['customer_id'] for a in v})
                                      for v in data.accounts_by_id.values()))))
    print("  login_handle unique: %s"
          % all(len(v) == 1 for v in data.accounts_by_login.values()))
    print("  customer email unique: %s"
          % all(len(v) == 1 for v in data.customers_by_email.values()))
    for field, index, label in (
        ("account_ref", data.accounts_by_id, "Accounts.account_id"),
        ("login_handle", data.accounts_by_login, "Accounts.login_handle"),
        ("email", data.customers_by_email, "Customers.email"),
    ):
        used = [a for a in data.alerts if a.get(field)]
        key = (lambda v: v.lower()) if field == "email" else (lambda v: v)
        misses = [a["alert_id"] for a in used if key(a[field]) not in index]
        print("  %-13s %3d alerts -> %-24s misses %d" % (field, len(used), label, len(misses)))
    print("  onboarding rows %d, distinct (account_id, customer_id) %d"
          % (len(data.onboarding), len(data.onboarding_by_account_customer)))
    ob_accounts = collections.defaultdict(set)
    for row in data.onboarding:
        ob_accounts[row["account_id"]].add(row["customer_id"])
    print("  onboarding accounts mapping to >1 customer: %d"
          % sum(1 for v in ob_accounts.values() if len(v) > 1))
    applicants = {r["kyc_applicant_id"] for r in data.onboarding if r.get("kyc_applicant_id")}
    print("  applicant ids on onboarding %d, present in kyc_checks %d"
          % (len(applicants), len(applicants & set(data.kyc_by_applicant))))
    print("  kyc result: %s" % dict(collections.Counter(k["result"] for k in data.kyc_checks)))
    no_approved = 0
    for cust in data.customers:
        apps = [r["kyc_applicant_id"] for r in data.onboarding_by_customer.get(cust["record_id"], [])]
        if not any(k["result"] == "approved"
                   for a in apps for k in data.kyc_by_applicant.get(a, [])):
            no_approved += 1
    print("  customers with no approved provider check: %d of %d" % (no_approved, len(data.customers)))

    head("3.3 alerts")
    links = collections.Counter(
        tuple(f for f in ("account_ref", "login_handle", "email") if a.get(f)) or ("none",)
        for a in data.alerts
    )
    print("  link types: %s" % dict(links))
    for label, subset in (
        ("linked  ", [a for a in data.alerts if any(a.get(f) for f in ("account_ref", "login_handle", "email"))]),
        ("unlinked", [a for a in data.alerts if not any(a.get(f) for f in ("account_ref", "login_handle", "email"))]),
    ):
        combos = collections.Counter(
            tuple(f for f in ("dob", "country", "city") if a.get(f)) for a in subset
        )
        print("  %s %3d alerts, screened fields present: %s" % (label, len(subset), dict(combos)))
    print("  entity_type: %s" % dict(collections.Counter(a["entity_type"] for a in data.alerts)))
    pairs = collections.Counter(
        (data.alert_by_id[h["alert_id"]]["entity_type"], h["entity_type"]) for h in data.hits
    )
    print("  alert type x hit type: %s" % dict(pairs))
    print("  hits listed on alerts: %d, hit rows: %d"
          % (sum(len(a["hit_ids"]) for a in data.alerts), len(data.hits)))
    odd = [a["city"] for a in data.alerts if a.get("city") and re.search(r"[,/]", a["city"])]
    print("  screened cities that are not one city: %d %s" % (len(odd), odd[:4]))

    head("3.4 hits")
    fill = []
    for field in ("aliases", "dobs", "place_of_birth", "life_status", "deceased_date",
                  "nationality", "citizenship", "countries", "addresses", "identifiers",
                  "categories", "primary_category", "profile_notes"):
        n = sum(1 for h in data.hits if h.get(field))
        fill.append("%s %d (%.0f%%)" % (field, n, 100.0 * n / len(data.hits)))
    print("  populated: %s" % ", ".join(fill))
    dob_shapes = collections.Counter()
    for h in data.hits:
        for value in h["dobs"]:
            dob_shapes[date_format(value)] += 1
    print("  dobs value formats: %s" % dict(dob_shapes))
    print("  life_status: %s" % dict(collections.Counter(h["life_status"] for h in data.hits)))
    deceased = [h for h in data.hits if h["life_status"] == "Deceased" or h["deceased_date"]]
    print("  deceased hits %d, of which with a date %d"
          % (len(deceased), sum(1 for h in deceased if h["deceased_date"])))
    loose = sum(1 for h in data.hits if "According to" in h["profile_notes"])
    strict_hits, strict_lines = 0, 0
    for h in data.hits:
        found = [ln for ln in h["profile_notes"].splitlines() if DATED_REPORT.match(ln)]
        if found:
            strict_hits += 1
            strict_lines += len(found)
    print("  'According to' anywhere: %d hits; strict dated-report form: %d hits, %d lines"
          % (loose, strict_hits, strict_lines))
    candidates = [
        h for h in data.hits
        if not h["dobs"] and h["profile_notes"].strip()
        and "\n" not in h["profile_notes"].split("\n\n")[0].strip()
        and len(h["profile_notes"].split("\n\n")[0]) < 250
        and not h["profile_notes"].lstrip().lower().startswith("according")
    ]
    born = sum(1 for h in candidates if re.search(r"\bwas born (in|on)\b", h["profile_notes"]))
    aged = sum(1 for h in candidates if AGE_CUES.search(h["profile_notes"].split("\n\n")[0]))
    print("  no dobs + one-line first paragraph: %d (explicit 'was born' %d, age cue %d)"
          % (len(candidates), born, aged))

    head("3.5 search results")
    print("  distinct queries %d, results %d" % (len(data.search_by_query), len(data.search_results)))
    individuals = [h for h in data.hits if h["entity_type"] != "Company"]
    companies = [h for h in data.hits if h["entity_type"] == "Company"]
    hit_rate = sum(1 for h in individuals if query_key(h["name"]) in data.search_by_query)
    comp_rate = sum(1 for h in companies if query_key(h["name"]) in data.search_by_query)
    print("  individual hits whose query key exists: %d of %d" % (hit_rate, len(individuals)))
    print("  company hits whose query key exists:    %d of %d" % (comp_rate, len(companies)))
    phrase_counts = collections.Counter()
    anchored = []
    for row in data.search_results:
        text = row["title"] + " " + row["snippet"]
        found = [p for p in LISTING_PHRASES if p in text]
        phrase_counts[len(found)] += 1
        if len(found) == 1:
            anchored.append(row)
    print("  listing phrases per result: %s" % dict(phrase_counts))
    one_age = one_date = 0
    for row in anchored:
        ages = re.findall(r"(?<![\d-])(\d{1,3})(?![\d])", row["snippet"])
        years = set(re.findall(r"(?:%s)\s+(\d{4})" % MONTHS, row["snippet"]))
        one_age += len(ages) == 1
        one_date += len(years) == 1
    print("  anchored results %d: exactly one age %d, exactly one Month YYYY %d"
          % (len(anchored), one_age, one_date))

    head("3.6 bank-side quirks")
    shapes = collections.Counter()
    for cust in data.customers:
        shapes[date_format(cust.get("dob"))] += 1
    for check in data.kyc_checks:
        shapes[date_format(check.get("verified_dob"))] += 1
    for alert in data.alerts:
        shapes[date_format(alert.get("dob"))] += 1
    total = sum(shapes.values())
    print("  date strings %d, formats %s" % (total, dict(shapes)))
    if shapes.get("UNPARSED"):
        print("  !! %d date strings match none of the seven formats" % shapes["UNPARSED"])
    slash_first = [
        int(m.group(1))
        for c in data.customers
        for m in [re.match(r"^(\d{1,2})/(\d{1,2})/", c.get("dob", ""))]
        if m
    ]
    print("  DD/MM/YYYY day-first: %d values with first component > 12"
          % sum(1 for v in slash_first if v > 12))
    print("  customers with a login_name: %d"
          % sum(1 for c in data.customers if c.get("login_name")))
    vocab = {c.get("nationality", "") for c in data.customers}
    vocab |= {c.get("residence_country", "") for c in data.customers}
    vocab |= {k.get("document_country", "") for k in data.kyc_checks}
    vocab |= {a.get("country", "") for a in data.alerts}
    print("  distinct bank-side country strings: %d" % len({v for v in vocab if v}))
    hit_vocab = set()
    for h in data.hits:
        for field in ("countries", "nationality", "citizenship"):
            hit_vocab |= set(h[field])
        if h.get("place_of_birth"):
            hit_vocab.add(h["place_of_birth"])
    print("  distinct hit-side country strings: %d (incl. 'International' %s, 'Europe' %s)"
          % (len(hit_vocab), "International" in hit_vocab, "Europe" in hit_vocab))
    ph = collections.Counter()
    ph_records = set()
    for cust in data.customers:
        for field in ("full_name", "preferred_name", "login_name"):
            for word in re.split(r"[\s,]+", cust.get(field, "")):
                if word and is_placeholder(word):
                    ph[word.upper()] += 1
                    ph_records.add(cust["record_id"])
    print("  placeholder name tokens: %s across %d customers"
          % (dict(ph.most_common()), len(ph_records)))
    phone_dob = collections.defaultdict(set)
    phones = collections.defaultdict(set)
    for cust in data.customers:
        if not cust.get("phone"):
            continue
        phones[cust["phone"]].add(cust["record_id"])
        if date_format(cust.get("dob")) in ("YYYY-MM-DD", "DD/MM/YYYY", "D Month YYYY", "Month D, YYYY"):
            phone_dob[(cust["phone"], _iso(cust["dob"]))].add(cust["record_id"])
    merge_groups = [v for v in phone_dob.values() if len(v) > 1]
    print("  phone + full DOB groups >1: %d (max size %d); shared phones overall: %d"
          % (len(merge_groups), max((len(g) for g in merge_groups), default=0),
             sum(1 for v in phones.values() if len(v) > 1)))
    docs = collections.defaultdict(set)
    for cust in data.customers:
        for row in data.onboarding_by_customer.get(cust["record_id"], []):
            for check in data.kyc_by_applicant.get(row["kyc_applicant_id"], []):
                if check["result"] == "approved" and check.get("document_number"):
                    docs[check["document_number"]].add(cust["record_id"])
    print("  approved document-number groups >1: %d" % sum(1 for v in docs.values() if len(v) > 1))
    print("  note channels: %s" % dict(collections.Counter(n["channel"] for n in data.notes)))
    names = sorted({v for v in vocab if v and len(v) > 2}, key=len, reverse=True)
    country_re = re.compile(r"\b(%s)\b" % "|".join(re.escape(n) for n in names))
    per_count = collections.Counter()
    for note in data.notes:
        if note["channel"] == "kyc":
            continue
        per_count[len(set(country_re.findall(note["text"])))] += 1
    print("  non-kyc notes by distinct countries mentioned: %s" % dict(sorted(per_count.items())))
    print()
    return 0


def _iso(value):
    """Just enough date normalisation for the merge-group count."""
    value = value.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if m:
        return m.group(0)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
    months = {n: i + 1 for i, n in enumerate(MONTHS.split("|"))}
    m = re.match(r"^(\d{1,2}) (\w+) (\d{4})$", value)
    if m and m.group(2) in months:
        return "%s-%02d-%02d" % (m.group(3), months[m.group(2)], int(m.group(1)))
    m = re.match(r"^(\w+) (\d{1,2}), (\d{4})$", value)
    if m and m.group(1) in months:
        return "%s-%02d-%02d" % (m.group(3), months[m.group(1)], int(m.group(2)))
    return value


if __name__ == "__main__":
    sys.exit(main(sys.argv))

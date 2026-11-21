#!/usr/bin/env python3
"""Build a dev/ folder of JSON Lines from the read-only workbook CSV export.

The brief's data room holds dev/*.jsonl; all we were given is the CSV browse export
(see plan.md section 2).  This writes the folder the system is specified to read, so we
develop against the real format.  Multi-valued fields become JSON lists; everything else
stays the string the provider wrote.  The Policy tab becomes POLICY.md and
name_variants.json.

    tools/csv_to_jsonl.py dataset dev
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system import loader, model  # noqa: E402

OUT_NAMES = {
    model.ALERTS: "alerts.jsonl",
    model.HITS: "hits.jsonl",
    model.CUSTOMERS: "customers.jsonl",
    model.ACCOUNTS: "accounts.jsonl",
    model.ONBOARDING: "onboarding.jsonl",
    model.KYC_CHECKS: "kyc_checks.jsonl",
    model.NOTES: "notes.jsonl",
    model.SEARCH_RESULTS: "search_results.jsonl",
    model.PRACTICE_LABELS: "practice_labels.jsonl",
}

# Column order as the workbook has it, so the JSONL reads like the source.
FIELD_ORDER = {
    model.ALERTS: [
        "alert_id", "screened_at", "customer_name", "entity_type", "dob", "country",
        "city", "account_ref", "login_handle", "email", "hit_count", "hit_ids",
    ],
    model.HITS: [
        "hit_id", "alert_id", "match_score", "entity_type", "name", "aliases", "gender",
        "dobs", "place_of_birth", "life_status", "deceased_date", "nationality",
        "citizenship", "countries", "addresses", "identifiers", "categories",
        "primary_category", "position_or_allegation", "details", "relationships",
        "profile_notes", "sources", "source_urls",
    ],
}


def write_jsonl(path, table, rows):
    order = FIELD_ORDER.get(table)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            if order:
                keys = [k for k in order if k in row] + [k for k in row if k not in order]
            else:
                keys = list(row)
            fh.write(json.dumps({k: row[k] for k in keys}, ensure_ascii=False) + "\n")


def extract_policy(src_folder, out_folder):
    """Pull POLICY.md and name_variants.json out of the Policy tab."""
    path = None
    for entry in sorted(os.listdir(src_folder)):
        if re.sub(r"[^a-z]", "", entry.lower()).startswith("policy"):
            path = os.path.join(src_folder, entry)
            break
    if path is None:
        return False
    rows = loader._read_sep(path, ",") if path.lower().endswith(".csv") else []
    # The tab has no real header: re-read it as raw cells.
    import csv as _csv

    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(_csv.reader(fh))
    lines = ["\t".join(c for c in row) for row in rows]
    text = "\n".join(lines)

    marker = "name_variants.json"
    head, _, tail = text.partition(marker)
    with open(os.path.join(out_folder, "POLICY.md"), "w", encoding="utf-8") as fh:
        fh.write(head.rstrip() + "\n")

    groups, legal = [], []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("company legal forms"):
            legal = [p.strip().lower() for p in line.split(":", 1)[1].split(",") if p.strip()]
            continue
        if "," in line and not line.endswith("."):
            parts = [p.strip().lower() for p in line.split(",") if p.strip()]
            if len(parts) >= 2 and all(re.fullmatch(r"[a-z'’-]+", p) for p in parts):
                groups.append(parts)
    payload = {"given_name_groups": groups, "company_legal_forms": legal}
    with open(os.path.join(out_folder, "name_variants.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return True


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, out = argv[1], argv[2]
    os.makedirs(out, exist_ok=True)
    data = loader.load(src)
    for table, rows in sorted(data.tables.items()):
        if not rows:
            continue
        write_jsonl(os.path.join(out, OUT_NAMES[table]), table, rows)
        print("%-18s %7d rows -> %s" % (table, len(rows), OUT_NAMES[table]))
    if extract_policy(src, out):
        payload = json.load(open(os.path.join(out, "name_variants.json")))
        print(
            "policy             POLICY.md + name_variants.json "
            "(%d name groups, %d legal forms)"
            % (len(payload["given_name_groups"]), len(payload["company_legal_forms"]))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

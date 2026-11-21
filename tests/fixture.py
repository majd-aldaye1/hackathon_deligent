"""Build a small Dataset in a temporary folder, so unit tests exercise the real loader."""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from system import loader  # noqa: E402

FILENAMES = {
    "alerts": "alerts.jsonl",
    "hits": "hits.jsonl",
    "customers": "customers.jsonl",
    "accounts": "accounts.jsonl",
    "onboarding": "onboarding.jsonl",
    "kyc_checks": "kyc_checks.jsonl",
    "notes": "notes.jsonl",
    "search_results": "search_results.jsonl",
    "practice_labels": "practice_labels.jsonl",
}

_PLACEHOLDER = {
    "alerts": {"alert_id": "A-0", "screened_at": "2026-01-01",
               "customer": {"name": "Nobody", "entity_type": "Individual"}, "hit_ids": []},
    "hits": {"hit_id": "H-0", "alert_id": "A-0", "name": "Nobody"},
    "customers": {"record_id": "CUS-0", "full_name": "Nobody", "email": "nobody@example.test"},
    "accounts": {"account_id": "ACC-0", "customer_id": "CUS-0"},
    "onboarding": {"account_id": "ACC-0", "customer_id": "CUS-0", "kyc_applicant_id": "APP-0"},
    "kyc_checks": {"check_id": "KYC-0", "applicant_id": "APP-0", "result": "rejected"},
}


class Folder(object):
    """A throwaway data folder.  Use as a context manager or call `close()`."""

    def __init__(self, **tables):
        self.path = tempfile.mkdtemp(prefix="sponl-fix-")
        rows = dict(tables)
        for table, placeholder in _PLACEHOLDER.items():
            rows.setdefault(table, [placeholder])
        for table, records in rows.items():
            with open(os.path.join(self.path, FILENAMES[table]), "w", encoding="utf-8") as fh:
                for record in records:
                    fh.write(json.dumps(record) + "\n")
        self.data = loader.load(self.path)

    def __enter__(self):
        return self.data

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)


def alert(alert_id="A-1", name="", entity_type="Individual", dob=None, country=None,
          city=None, account_ref=None, login_handle=None, email=None, hit_ids=(),
          screened_at="2026-11-06"):
    return {
        "alert_id": alert_id,
        "screened_at": screened_at,
        "customer": {
            "name": name,
            "entity_type": entity_type,
            "dob": dob,
            "country": country,
            "city": city,
        },
        "account_ref": account_ref,
        "login_handle": login_handle,
        "email": email,
        "hit_ids": list(hit_ids),
    }


def customer(record_id, full_name="", **kwargs):
    row = {
        "record_id": record_id,
        "entity_type": "Individual",
        "full_name": full_name,
        "preferred_name": None,
        "login_name": None,
        "dob": None,
        "nationality": None,
        "residence_country": None,
        "city": None,
        "address": None,
        "email": "%s@example.test" % record_id.lower(),
        "phone": None,
    }
    row.update(kwargs)
    return row


def account(account_id, customer_id, login_handle=None, phone=None):
    return {
        "account_id": account_id,
        "customer_id": customer_id,
        "login_handle": login_handle,
        "phone": phone,
        "opened_at": "2021-01-01",
        "status": "active",
    }


def onboarding(account_id, customer_id, kyc_applicant_id):
    return {
        "account_id": account_id,
        "customer_id": customer_id,
        "kyc_applicant_id": kyc_applicant_id,
        "onboarded_at": "2021-01-01",
    }


def check(check_id, applicant_id, result="approved", verified_name=None, verified_dob=None,
          document_number=None, document_country=None, checked_at="2024-01-01"):
    return {
        "check_id": check_id,
        "applicant_id": applicant_id,
        "provider": "Onfido",
        "verified_name": verified_name,
        "verified_dob": verified_dob,
        "document_type": "passport",
        "document_number": document_number,
        "document_country": document_country,
        "result": result,
        "checked_at": checked_at,
    }


def note(note_id, email, text, channel="email", created_at="2026-01-01"):
    return {
        "note_id": note_id,
        "requester_email": email,
        "created_at": created_at,
        "channel": channel,
        "text": text,
    }

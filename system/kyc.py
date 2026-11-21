"""The KYC chain: a customer record to the identity checks that belong to it.

POLICY.md principle 4: "The most recent *approved* identity check of the person is the
most reliable source for their legal name, date of birth and document country ...
Rejected or expired checks are not evidence."

The join runs customer -> accounts -> onboarding on **both** `account_id` and
`customer_id` -> `kyc_applicant_id` -> kyc_checks.  Joining on `account_id` alone would
hand a joint holder the other holder's identity check.
"""

from . import dates

APPROVED = "approved"


def applicant_ids(data, record_id):
    """The KYC applicant ids reachable from one customer record, in a stable order."""
    out = []
    for account in sorted(
        data.accounts_by_customer.get(record_id, ()), key=lambda a: a.get("account_id", "")
    ):
        key = (account.get("account_id", ""), record_id)
        for row in data.onboarding_by_account_customer.get(key, ()):
            applicant = row.get("kyc_applicant_id", "")
            if applicant and applicant not in out:
                out.append(applicant)
    return out


def checks(data, record_id):
    """Every identity check reachable from one customer record, newest first.

    Ordered by `checked_at` descending, then by `check_id`, so "the most recent" never
    depends on file order.
    """
    out = []
    for applicant in applicant_ids(data, record_id):
        out.extend(data.kyc_by_applicant.get(applicant, ()))
    return sorted(out, key=_recency_key, reverse=True)


def approved_checks(data, record_id):
    """Only the approved ones: "Rejected or expired checks are not evidence." """
    return [c for c in checks(data, record_id) if c.get("result", "") == APPROVED]


def latest_approved(data, record_id):
    found = approved_checks(data, record_id)
    return found[0] if found else None


def _recency_key(check):
    date = dates.parse(check.get("checked_at"))
    return (date.key() if date else (0, 0, 0), check.get("check_id", ""))


def recency_key(check):
    return _recency_key(check)


def document_numbers(data, record_id):
    """Document numbers on this record's approved checks, used to merge records."""
    out = []
    for check in approved_checks(data, record_id):
        number = check.get("document_number", "")
        if number and number not in out:
            out.append(number)
    return out

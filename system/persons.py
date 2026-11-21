"""Grouping customer records into persons.

POLICY.md principle 3: "Records that share a phone number and the same full date of birth
belong to the same person, and so do records whose approved identity checks carry the same
document number; a record linked to one of them in either way belongs to that person too.
All their facts count.  Sharing a phone or an address alone does not: family members often
do."

So: union on (phone, full date of birth) and on approved document number, transitively,
and on nothing else.
"""

from collections import defaultdict

from . import dates, kyc


class Persons(object):
    """Which customer records belong to the same person."""

    def __init__(self, data):
        self._parent = {}
        self._members = None
        self._reason = {}
        self._build(data)

    # -- union-find

    def _find(self, item):
        root = item
        while self._parent.get(root, root) != root:
            root = self._parent[root]
        while self._parent.get(item, item) != item:
            self._parent[item], item = root, self._parent[item]
        return root

    def _union(self, left, right, reason):
        a, b = self._find(left), self._find(right)
        if a == b:
            return
        # The lower id becomes the root, so the representative never depends on the
        # order the file happened to be read in.
        if b < a:
            a, b = b, a
        self._parent[b] = a
        self._reason.setdefault(frozenset((left, right)), reason)

    # -- building

    def _build(self, data):
        for cust in data.customers:
            self._parent.setdefault(cust["record_id"], cust["record_id"])

        # a shared phone *and* the same full date of birth
        by_phone_dob = defaultdict(list)
        for cust in data.customers:
            phone = cust.get("phone", "")
            dob = dates.parse(cust.get("dob"))
            if not phone or not dates.is_complete(dob):
                continue
            by_phone_dob[(phone, dob.iso())].append(cust["record_id"])
        for key in sorted(by_phone_dob):
            group = sorted(by_phone_dob[key])
            for other in group[1:]:
                self._union(group[0], other, "same phone and full date of birth")

        # the same document number on approved identity checks
        by_document = defaultdict(list)
        for cust in data.customers:
            for number in kyc.document_numbers(data, cust["record_id"]):
                by_document[number].append(cust["record_id"])
        for key in sorted(by_document):
            group = sorted(set(by_document[key]))
            for other in group[1:]:
                self._union(group[0], other, "same document number on approved checks")

    # -- queries

    def _build_members(self):
        members = defaultdict(set)
        for record_id in self._parent:
            members[self._find(record_id)].add(record_id)
        self._members = {root: tuple(sorted(group)) for root, group in members.items()}

    def person_of(self, record_id):
        """Every record of the person this record belongs to, as a sorted tuple."""
        if record_id not in self._parent:
            return (record_id,)
        if self._members is None:
            self._build_members()
        return self._members[self._find(record_id)]

    def representative(self, record_id):
        """The id we report as `customer_record_id`: the lowest of the person's records.

        POLICY principle 3: "When one person has several records, any of them is accepted."
        """
        return self.person_of(record_id)[0]

    def persons_of(self, record_ids):
        """The distinct persons a set of records belongs to, in a stable order."""
        out = []
        for record_id in sorted(record_ids):
            group = self.person_of(record_id)
            if group not in out:
                out.append(group)
        return sorted(out)

    def merged_groups(self):
        """Every person made of more than one record."""
        if self._members is None:
            self._build_members()
        return sorted(group for group in set(self._members.values()) if len(group) > 1)

    def merge_reason(self, left, right):
        return self._reason.get(frozenset((left, right)))

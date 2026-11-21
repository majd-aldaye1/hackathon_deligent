"""Step 11: the same input, and equivalent input, decide the same way.

The brief scores five runs on the unseen set giving the same decision and reason code every
time.  The unseen set is also a *different file*, so a dependence on the order rows happen
to sit in would show up there and nowhere else — these tests cover both.

`tools/repeat.py` is the end-to-end version, driving the executable five times.
"""

import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import decide, loader, name_variants, persons, resolve  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")


def signature(decisions):
    return [
        (d.hit_id, d.decision, d.reason_code, d.customer_record_id, d.reason, tuple(d.evidence))
        for d in decisions
    ]


def by_hit(decisions):
    return {s[0]: s[1:] for s in signature(decisions)}


class TestOrderIndependenceOnAFixture(unittest.TestCase):
    """Two people fit, so every tie-break in the resolver is exercised."""

    ALERT = fixture.alert(name="Juan Gonzalez", dob="1970", country="Panama", hit_ids=["H-1"])
    HIT = {
        "hit_id": "H-1", "alert_id": "A-1", "entity_type": "Individual",
        "name": "Gonzalez, Juan", "dobs": [], "categories": ["PEP"],
        "primary_category": "PEP", "countries": ["Panama"],
    }

    def _decide(self, customers):
        with fixture.Folder(alerts=[self.ALERT], hits=[self.HIT], customers=customers) as data:
            return by_hit(decide.build(data).decide_all())

    def test_the_order_of_the_customer_rows_does_not_matter(self):
        rows = [
            fixture.customer("CUS-A", "Juan Gonzalez", dob="1970-03-01",
                             residence_country="Panama"),
            fixture.customer("CUS-B", "Juan Gonzalez", dob="1970-09-09",
                             residence_country="Panama"),
            fixture.customer("CUS-C", "Juan Gonzalez", dob="1970-05-05",
                             residence_country="Panama"),
        ]
        first = self._decide(rows)
        for seed in range(4):
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(self._decide(shuffled), first, "seed %d" % seed)

    def test_the_reported_record_is_the_same_whichever_row_comes_first(self):
        rows = [
            fixture.customer("CUS-Z", "Juan Gonzalez", dob="1970-03-01", phone="+1 1",
                             residence_country="Panama"),
            fixture.customer("CUS-A", "Juan Gonzalez", dob="1970-03-01", phone="+1 1",
                             residence_country="Panama"),
        ]
        forwards = self._decide(rows)
        backwards = self._decide(list(reversed(rows)))
        self.assertEqual(forwards, backwards)
        self.assertEqual(forwards["H-1"][2], "CUS-A")  # the lowest id, either way


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestOnTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        cls.variants = (
            name_variants.from_raw(cls.data.name_variants_raw)
            if cls.data.name_variants_raw else None
        )
        cls.baseline = decide.build(cls.data, cls.variants).decide_all()

    def test_the_same_data_decides_the_same_way_twice(self):
        again = decide.build(self.data, self.variants).decide_all()
        self.assertEqual(signature(self.baseline), signature(again))

    def test_reordering_every_table_changes_no_decision(self):
        rng = random.Random(20261121)
        for name in sorted(self.data.tables):
            rng.shuffle(self.data.tables[name])
        self.data._index()
        self.data._name_index = None
        try:
            shuffled = decide.build(self.data, self.variants).decide_all()
            self.assertEqual(len(shuffled), len(self.baseline))
            self.assertEqual(by_hit(shuffled), by_hit(self.baseline))
        finally:
            # Leave the dataset as the other tests in this class expect to find it.
            self.data.tables = loader.load(FOLDER).tables
            self.data._index()
            self.data._name_index = None

    def test_the_output_follows_the_hits_file_order(self):
        self.assertEqual(
            [d.hit_id for d in self.baseline], [h["hit_id"] for h in self.data.hits]
        )

    def test_person_grouping_does_not_depend_on_row_order(self):
        first = persons.Persons(self.data).merged_groups()
        rng = random.Random(7)
        shuffled = list(self.data.customers)
        rng.shuffle(shuffled)
        original = self.data.tables["customers"]
        try:
            self.data.tables["customers"] = shuffled
            self.data._index()
            self.assertEqual(persons.Persons(self.data).merged_groups(), first)
        finally:
            self.data.tables["customers"] = original
            self.data._index()

    def test_resolution_does_not_depend_on_row_order(self):
        index = persons.Persons(self.data)
        before = {}
        for alert in self.data.alerts:
            screened = resolve.Screened(alert)
            before[alert["alert_id"]] = resolve.resolve_customer(
                self.data, index, screened, self.variants
            ).record_ids
        rng = random.Random(11)
        shuffled = list(self.data.accounts)
        rng.shuffle(shuffled)
        original = self.data.tables["accounts"]
        try:
            self.data.tables["accounts"] = shuffled
            self.data._index()
            rebuilt = persons.Persons(self.data)
            after = {}
            for alert in self.data.alerts:
                screened = resolve.Screened(alert)
                after[alert["alert_id"]] = resolve.resolve_customer(
                    self.data, rebuilt, screened, self.variants
                ).record_ids
            self.assertEqual(after, before)
        finally:
            self.data.tables["accounts"] = original
            self.data._index()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Step 7: one decision per hit, and what happens when several people fit.

POLICY.md principle 3: "If more than one person fits an alert, decide the hit for each; if
they all lead to the same decision, give it, otherwise the decision is `REVIEW` with
`AMBIGUOUS_CUSTOMER_RECORD`.  Either way `customer_record_id` is `AMBIGUOUS`."
"""

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixture  # noqa: E402
from system import decide, loader, model, name_variants  # noqa: E402

FOLDER = os.path.join(ROOT, "dev")
OUTPUT = os.path.join(ROOT, "output", "dev.jsonl")


def hit_row(hit_id="H-1", alert_id="A-1", **kwargs):
    row = {
        "hit_id": hit_id,
        "alert_id": alert_id,
        "entity_type": "Individual",
        "name": "Lovelace, Ada",
        "aliases": [],
        "dobs": [],
        "countries": [],
        "addresses": [],
        "categories": ["PEP"],
        "primary_category": "PEP",
        "profile_notes": "",
        "deceased_date": None,
    }
    row.update(kwargs)
    return row


def run(alerts, hits, customers, **extra):
    tables = {"alerts": alerts, "hits": hits, "customers": customers}
    tables.update(extra)
    folder = fixture.Folder(**tables)
    try:
        engine = decide.build(folder.data)
        return {d.hit_id: d for d in engine.decide_all()}
    finally:
        folder.close()


class TestOutputShape(unittest.TestCase):
    def test_the_seven_fields(self):
        out = run(
            [fixture.alert(name="Ada Lovelace", dob="1815-12-10", hit_ids=["H-1"])],
            [hit_row(dobs=["1815-12-10"])],
            [fixture.customer("CUS-A", "Ada Lovelace", dob="1815-12-10")],
        )
        row = out["H-1"].to_json()
        self.assertEqual(sorted(row), sorted(
            ["hit_id", "alert_id", "decision", "reason_code", "customer_record_id",
             "reason", "evidence"]
        ))
        self.assertEqual(row["alert_id"], "A-1")
        self.assertIn(row["decision"], model.DECISIONS)
        self.assertEqual(model.REASON_CODES[row["reason_code"]], row["decision"])


class TestNoCustomer(unittest.TestCase):
    def test_a_hit_with_no_customer_is_reviewed_and_cites_nothing(self):
        out = run(
            [fixture.alert(name="Nobody At All", dob="1900-01-01", country="Spain",
                           hit_ids=["H-1"])],
            [hit_row(countries=["Spain"])],
            [fixture.customer("CUS-A", "Ada Lovelace")],
        )
        decision = out["H-1"]
        self.assertEqual(decision.decision, "REVIEW")
        self.assertEqual(decision.reason_code, "INSUFFICIENT_DATA")
        self.assertIsNone(decision.customer_record_id)
        self.assertEqual(decision.evidence, [])
        self.assertIn("No customer record", decision.reason)

    def test_the_screened_details_never_clear_a_hit(self):
        # Decision log D6: without a customer, the screened details only locate.
        out = run(
            [fixture.alert(name="Nobody At All", dob="1900-01-01", country="Spain",
                           hit_ids=["H-1"])],
            [hit_row(countries=["Japan"], dobs=["1980"])],
            [fixture.customer("CUS-A", "Ada Lovelace")],
        )
        self.assertEqual(out["H-1"].decision, "REVIEW")


class TestSeveralPeopleFit(unittest.TestCase):
    ALERT = [fixture.alert(name="Juan Gonzalez", dob="1970", country="Panama",
                           hit_ids=["H-1"])]

    def _customers(self, **overrides):
        base = [
            fixture.customer("CUS-A", "Juan Gonzalez", dob="1970-03-01",
                             residence_country="Panama"),
            fixture.customer("CUS-B", "Juan Gonzalez", dob="1970-09-09",
                             residence_country="Panama"),
        ]
        for record in base:
            record.update(overrides.get(record["record_id"], {}))
        return base

    def test_agreeing_people_give_the_shared_answer_with_ambiguous_as_the_record(self):
        out = run(self.ALERT, [hit_row(countries=["Panama"])], self._customers())
        decision = out["H-1"]
        self.assertEqual(decision.decision, "REVIEW")
        self.assertEqual(decision.reason_code, "INSUFFICIENT_DATA")
        self.assertEqual(decision.customer_record_id, "AMBIGUOUS")
        self.assertIn("Two people", decision.reason)

    def test_disagreeing_people_give_ambiguous_customer_record(self):
        # One matches the hit's date of birth, the other contradicts it.
        out = run(
            self.ALERT,
            [hit_row(countries=["Panama"], dobs=["1970-03-01"])],
            self._customers(),
        )
        decision = out["H-1"]
        self.assertEqual(decision.decision, "REVIEW")
        self.assertEqual(decision.reason_code, "AMBIGUOUS_CUSTOMER_RECORD")
        self.assertEqual(decision.customer_record_id, "AMBIGUOUS")
        self.assertIn("different answers", decision.reason)

    def test_the_evidence_is_the_union_across_the_people(self):
        out = run(self.ALERT, [hit_row(countries=["Panama"])], self._customers())
        self.assertEqual(out["H-1"].evidence, ["CUS-A", "CUS-B"])

    def test_one_person_with_two_records_is_not_ambiguous(self):
        customers = [
            fixture.customer("CUS-A", "Juan Gonzalez", dob="1970-03-01", phone="+1 1",
                             residence_country="Panama"),
            fixture.customer("CUS-B", "Juan Gonzalez", dob="1970-03-01", phone="+1 1",
                             residence_country="Panama"),
        ]
        out = run(self.ALERT, [hit_row(countries=["Panama"])], customers)
        self.assertEqual(out["H-1"].customer_record_id, "CUS-A")


class TestFailSafe(unittest.TestCase):
    def test_a_hit_that_raises_becomes_a_review_and_never_a_clear(self):
        out = run(
            [fixture.alert(name="Ada Lovelace", hit_ids=["H-1"])],
            [hit_row()],
            [fixture.customer("CUS-A", "Ada Lovelace")],
        )
        engine = None
        folder = fixture.Folder(
            alerts=[fixture.alert(name="Ada Lovelace", hit_ids=["H-1"])],
            hits=[hit_row()],
            customers=[fixture.customer("CUS-A", "Ada Lovelace")],
        )
        try:
            engine = decide.build(folder.data)

            def explode(*args, **kwargs):
                raise RuntimeError("boom")

            engine._decide = explode
            decision = engine.decide(folder.data.hits[0])
        finally:
            folder.close()
        self.assertEqual(decision.decision, "REVIEW")
        self.assertEqual(decision.reason_code, "INSUFFICIENT_DATA")
        self.assertIsNone(decision.customer_record_id)
        self.assertEqual(decision.evidence, [])
        self.assertIn("could not complete", decision.reason)
        self.assertTrue(decision.note)
        self.assertEqual(out["H-1"].decision, "REVIEW")


@unittest.skipUnless(os.path.isdir(FOLDER), "development data not present")
class TestAgainstTheDevelopmentSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = loader.load(FOLDER)
        variants = (
            name_variants.from_raw(cls.data.name_variants_raw)
            if cls.data.name_variants_raw else None
        )
        start = time.time()
        cls.engine = decide.build(cls.data, variants)
        cls.decisions = cls.engine.decide_all()
        cls.seconds = time.time() - start
        cls.by_hit = {d.hit_id: d for d in cls.decisions}

    def test_one_decision_per_hit_in_file_order(self):
        self.assertEqual(len(self.decisions), 819)
        self.assertEqual([d.hit_id for d in self.decisions], [h["hit_id"] for h in self.data.hits])

    def test_nothing_crashed(self):
        crashed = [d.hit_id for d in self.decisions if d.note]
        self.assertEqual(crashed, [])

    def test_every_reason_code_belongs_to_its_decision(self):
        for decision in self.decisions:
            self.assertEqual(
                model.REASON_CODES[decision.reason_code], decision.decision, decision.hit_id
            )

    def test_every_evidence_id_is_a_record_and_never_a_hit(self):
        known = set(self.data.customer_by_id)
        known |= {c["check_id"] for c in self.data.kyc_checks}
        known |= {n["note_id"] for n in self.data.notes}
        known |= {r["result_id"] for r in self.data.search_results}
        for decision in self.decisions:
            for item in decision.evidence:
                self.assertIn(item, known, "%s cites %s" % (decision.hit_id, item))
                self.assertFalse(item.startswith("H-"), item)

    def test_every_customer_record_id_is_a_record_or_ambiguous_or_none(self):
        for decision in self.decisions:
            value = decision.customer_record_id
            if value is None or value == decide.AMBIGUOUS:
                continue
            self.assertIn(value, self.data.customer_by_id, decision.hit_id)

    def test_a_clear_always_cites_something(self):
        for decision in self.decisions:
            if decision.decision == "DIFFERENT_ENTITY":
                self.assertTrue(decision.evidence, decision.hit_id)

    def test_the_practice_labels_cost_nothing(self):
        cost = {
            ("DIFFERENT_ENTITY", "DIFFERENT_ENTITY"): 0, ("DIFFERENT_ENTITY", "SAME_ENTITY"): 3,
            ("DIFFERENT_ENTITY", "REVIEW"): 3, ("SAME_ENTITY", "DIFFERENT_ENTITY"): 60,
            ("SAME_ENTITY", "SAME_ENTITY"): 0, ("SAME_ENTITY", "REVIEW"): 2,
            ("REVIEW", "DIFFERENT_ENTITY"): 60, ("REVIEW", "SAME_ENTITY"): 2,
            ("REVIEW", "REVIEW"): 0,
        }
        total = 0
        unsafe = []
        for label in self.data.practice_labels:
            decision = self.by_hit[label["hit_id"]]
            total += cost[(label["decision"], decision.decision)]
            if decision.decision == "DIFFERENT_ENTITY" and label["decision"] != "DIFFERENT_ENTITY":
                unsafe.append(label["hit_id"])
        self.assertEqual(unsafe, [])
        self.assertEqual(total, 0)

    def test_every_practice_label_gets_an_accepted_code_and_record(self):
        for label in self.data.practice_labels:
            decision = self.by_hit[label["hit_id"]]
            self.assertIn(decision.reason_code, label["reason_codes"], label["hit_id"])
            self.assertIn(
                decision.customer_record_id, label["customer_record_ids"], label["hit_id"]
            )

    def test_every_practice_label_gets_exactly_the_evidence_it_expects(self):
        for label in self.data.practice_labels:
            decision = self.by_hit[label["hit_id"]]
            self.assertEqual(
                sorted(decision.evidence), sorted(label["evidence"]), label["hit_id"]
            )

    def test_the_whole_run_is_quick(self):
        # The brief allows 30 minutes for about 550 hits.
        self.assertLess(self.seconds, 120.0)

    def test_running_twice_gives_identical_decisions(self):
        again = decide.build(self.data).decide_all()
        self.assertEqual(
            [(d.hit_id, d.decision, d.reason_code, d.customer_record_id, tuple(d.evidence))
             for d in self.decisions],
            [(d.hit_id, d.decision, d.reason_code, d.customer_record_id, tuple(d.evidence))
             for d in again],
        )

    @unittest.skipUnless(os.path.isfile(OUTPUT), "output/dev.jsonl not written yet")
    def test_the_committed_output_matches_what_the_engine_produces_now(self):
        with open(OUTPUT, encoding="utf-8") as fh:
            written = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(written, [d.to_json() for d in self.decisions])


if __name__ == "__main__":
    unittest.main(verbosity=2)

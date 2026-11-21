"""One decision per hit: resolve, gather, evaluate, write it down.

POLICY.md principle 3: "If more than one person fits an alert, decide the hit for each; if
they all lead to the same decision, give it, otherwise the decision is `REVIEW` with
`AMBIGUOUS_CUSTOMER_RECORD`.  Either way `customer_record_id` is `AMBIGUOUS`."

Any hit that raises becomes `REVIEW` / `INSUFFICIENT_DATA` with an honest reason.  A crash
must never become a clear, and must never stop the run.
"""

import traceback

from . import customer_facts, hit_facts, reasons, resolve, rules
from .model import CODE_ORDER

AMBIGUOUS = "AMBIGUOUS"


class Decision(object):
    """The output line for one hit."""

    __slots__ = ("hit_id", "alert_id", "decision", "reason_code", "customer_record_id",
                 "reason", "evidence", "note")

    def __init__(self, hit_id, alert_id, decision, reason_code, customer_record_id,
                 reason, evidence, note=""):
        self.hit_id = hit_id
        self.alert_id = alert_id
        self.decision = decision
        self.reason_code = reason_code
        self.customer_record_id = customer_record_id
        self.reason = reason
        self.evidence = list(evidence)
        self.note = note

    def to_json(self):
        return {
            "hit_id": self.hit_id,
            "alert_id": self.alert_id,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "customer_record_id": self.customer_record_id,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }

    def __repr__(self):
        return "Decision(%s, %s, %s)" % (self.hit_id, self.decision, self.reason_code)


class Engine(object):
    """Holds the indexes and the per-alert work so repeated hits cost nothing twice."""

    def __init__(self, data, persons_index, variants=None):
        self.data = data
        self.persons = persons_index
        self.variants = variants
        self._screened = {}
        self._resolution = {}
        self._sheets = {}

    def screened(self, alert_id):
        if alert_id not in self._screened:
            self._screened[alert_id] = resolve.Screened(self.data.alert_by_id[alert_id])
        return self._screened[alert_id]

    def resolution(self, alert_id):
        if alert_id not in self._resolution:
            self._resolution[alert_id] = resolve.resolve_customer(
                self.data, self.persons, self.screened(alert_id), self.variants
            )
        return self._resolution[alert_id]

    def sheet(self, person):
        if person not in self._sheets:
            self._sheets[person] = customer_facts.gather(self.data, person, self.variants)
        return self._sheets[person]

    # -- the decision

    def decide(self, hit):
        hit_id = hit.get("hit_id", "")
        alert_id = hit.get("alert_id", "")
        try:
            return self._decide(hit, hit_id, alert_id)
        except Exception:  # never crash, never clear
            return Decision(
                hit_id=hit_id,
                alert_id=alert_id,
                decision="REVIEW",
                reason_code="INSUFFICIENT_DATA",
                customer_record_id=None,
                reason=(
                    "The system could not complete its checks on this hit, so nothing about it "
                    "has been established and it is left for a person to review."
                ),
                evidence=[],
                note=traceback.format_exc(limit=3),
            )

    def _decide(self, hit, hit_id, alert_id):
        screened = self.screened(alert_id)
        resolution = self.resolution(alert_id)
        facts = hit_facts.gather(self.data, hit, self.variants)

        if not resolution.found:
            return Decision(
                hit_id=hit_id,
                alert_id=alert_id,
                decision="REVIEW",
                reason_code="INSUFFICIENT_DATA",
                customer_record_id=None,
                reason=reasons.for_no_customer(screened, facts),
                evidence=[],
            )

        verdicts = []
        for person in resolution.persons:
            sheet = self.sheet(person)
            verdicts.append(rules.evaluate(sheet, facts, screened, self.variants))

        record_id = resolution.customer_record_id()
        decisions = {v.decision for v in verdicts}

        if len(decisions) > 1:
            # "otherwise the decision is REVIEW with AMBIGUOUS_CUSTOMER_RECORD"
            evidence = sorted({s for v in verdicts for s in v.sources()})
            return Decision(
                hit_id=hit_id,
                alert_id=alert_id,
                decision="REVIEW",
                reason_code="AMBIGUOUS_CUSTOMER_RECORD",
                customer_record_id=AMBIGUOUS,
                reason=reasons.for_ambiguous(verdicts, facts, resolution.persons),
                evidence=evidence,
            )

        # They agree.  Report the first code in the fixed order that any of them found,
        # and cite every record that took them there.
        chosen = min(verdicts, key=lambda v: CODE_ORDER.index(v.code))
        evidence = sorted({s for v in verdicts for s in v.sources()})
        reason = self._reason_for(chosen, facts)
        if len(verdicts) > 1:
            reason = reasons.with_ambiguity_note(reason, len(verdicts))
        return Decision(
            hit_id=hit_id,
            alert_id=alert_id,
            decision=chosen.decision,
            reason_code=chosen.code,
            customer_record_id=record_id,
            reason=reason,
            evidence=evidence,
        )

    def _reason_for(self, verdict, facts):
        if verdict.decision == "DIFFERENT_ENTITY":
            return reasons.for_contradiction(verdict.findings, facts, verdict.context)
        if verdict.decision == "SAME_ENTITY":
            return reasons.for_agreement(verdict.code, verdict.findings[0].detail)
        return reasons.for_review(verdict.review_detail)

    def decide_all(self):
        """Every hit, in the order the hits file lists them."""
        return [self.decide(hit) for hit in self.data.hits]


def build(data, variants=None):
    from . import persons

    return Engine(data, persons.Persons(data), variants)

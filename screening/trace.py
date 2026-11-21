"""Build the evidence-trail JSON the analyst UI renders."""
from __future__ import annotations

from collections import defaultdict

from . import text as T
from .data import as_list, s

ALERT_FIELDS = ["alert_id", "screened_at", "customer_name", "entity_type", "dob", "country", "city",
                "account_ref", "login_handle", "email"]
HIT_FIELDS = ["match_score", "entity_type", "name", "aliases", "gender", "dobs", "place_of_birth", "life_status",
              "deceased_date", "nationality", "citizenship", "countries", "addresses", "identifiers", "categories",
              "primary_category", "position_or_allegation", "profile_notes", "sources"]


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    return str(v)


def alert_outcome(decisions):
    if any(d == "SAME_ENTITY" for d in decisions):
        return "ESCALATED"
    if decisions and all(d == "DIFFERENT_ENTITY" for d in decisions):
        return "CLEARED"
    return "REVIEW"


def build_trace(eng, results):
    ds = eng.ds
    labels = {s(l.get("hit_id")): l for l in ds.labels}
    by_alert = defaultdict(list)
    for r in results:
        by_alert[r["alert_id"]].append(r)
    records = {}

    def add_record(rid):
        if not rid or rid in records or rid == "AMBIGUOUS":
            return
        if rid in ds.cust_by_id:
            records[rid] = dict(ds.cust_by_id[rid], _table="Customers")
            return
        if rid.startswith("KYC-"):
            for k in ds.kyc:
                if s(k.get("check_id")) == rid:
                    records[rid] = dict(k, _table="KYC checks")
                    return
        if rid.startswith("NOTE-"):
            for n in ds.notes:
                if s(n.get("note_id")) == rid:
                    records[rid] = dict(n, _table="Notes")
                    return
        if rid.startswith("SR-"):
            for x in ds.search:
                if s(x.get("result_id")) == rid:
                    records[rid] = dict(x, _table="Search results")
                    return

    # fast lookups for KYC / notes / search ids
    kyc_by_id = {s(k.get("check_id")): k for k in ds.kyc}
    note_by_id = {s(n.get("note_id")): n for n in ds.notes}
    sr_by_id = {s(x.get("result_id")): x for x in ds.search}

    def add(rid):
        if not rid or rid in records or rid == "AMBIGUOUS":
            return
        if rid in ds.cust_by_id:
            records[rid] = dict(ds.cust_by_id[rid], _table="Customers")
        elif rid in kyc_by_id:
            records[rid] = dict(kyc_by_id[rid], _table="KYC checks")
        elif rid in note_by_id:
            records[rid] = dict(note_by_id[rid], _table="Notes")
        elif rid in sr_by_id:
            records[rid] = dict(sr_by_id[rid], _table="Search results")

    alerts_out = []
    for a in ds.alerts:
        aid = s(a.get("alert_id"))
        rs = by_alert.get(aid, [])
        people = []
        seen = set()
        for r in rs:
            for x in r.get("persons", []):
                p = x["person"]
                if p.primary in seen:
                    continue
                seen.add(p.primary)
                for rid in p.records:
                    add(rid)
                v = p.verified
                if v:
                    add(v.id)
                for c, srcs in p.countries.items():
                    for sid in srcs:
                        add(sid)
                people.append({
                    "primary": p.primary, "records": p.records, "entity_type": p.entity_type,
                    "names": list(dict.fromkeys(n for n, _ in p.record_names)),
                    "verified": None if not v else {"id": v.id, "name": v.name, "dob": T.fmt_date(v.dob) if v.dob else None,
                                                    "country": v.country, "date": T.fmt_date(v.date), "kind": v.kind},
                    "dob": T.fmt_date(p.dob) if p.dob else None, "dob_src": p.dob_src,
                    "countries": p.countries,
                    "checks": [{"id": c.id, "date": T.fmt_date(c.date), "name": c.name, "kind": c.kind} for c in p.approved_checks],
                })
        hits_out = []
        for r in rs:
            hit = ds.hit_by_id[r["hit_id"]]
            hf = r["hit_facts"]
            for e in r["evidence"]:
                add(e)
            for sid in hf.search_used:
                add(sid)
            lab = labels.get(r["hit_id"])
            label = None
            if lab:
                codes = [s(c) for c in as_list(lab.get("reason_codes"))]
                custs = [s(c) for c in as_list(lab.get("customer_record_ids"))]
                ok = (s(lab.get("decision")) == r["decision"] and r["reason_code"] in codes and
                      ((r["customer_record_id"] in custs) if custs else r["customer_record_id"] is None))
                label = {"decision": s(lab.get("decision")), "codes": codes, "customers": custs,
                         "reason": s(lab.get("reference_reason")), "match": ok}
            per = []
            for x in r.get("persons", []):
                per.append({"customer": x["person"].primary, "decision": x["decision"], "reason_code": x["reason_code"],
                            "explanation": x["explanation"], "signals": x.get("signals"), "evidence": x["evidence"]})
            hits_out.append({
                "hit_id": r["hit_id"], "decision": r["decision"], "reason_code": r["reason_code"],
                "all_codes": r.get("all_codes", [r["reason_code"]]),
                "customer_record_id": r["customer_record_id"], "evidence": r["evidence"],
                "explanation": r["explanation"], "per_person": per, "label": label,
                "hit": {k: hit.get(k) for k in HIT_FIELDS},
                "facts": {"names": hf.names, "dobs": [{"date": T.fmt_date(d), "origin": o, "src": sid} for d, o, sid in hf.dobs],
                          "dob_origin": hf.dob_origin, "countries": sorted(hf.countries), "listing": hf.listing,
                          "earliest_report": T.fmt_date(hf.earliest_report) if hf.earliest_report else None,
                          "report_line": hf.report_line, "deceased": T.fmt_date(hf.deceased) if hf.deceased else None,
                          "search_used": hf.search_used},
            })
        alerts_out.append({
            "alert_id": aid, "screened": {k: a.get(k) for k in ALERT_FIELDS},
            "path": rs[0]["path"] if rs else [], "people": people, "hits": hits_out,
            "outcome": alert_outcome([h["decision"] for h in hits_out]),
            "has_label": any(h["label"] for h in hits_out),
        })
    return _jsonable({"source": ds.source, "alerts": alerts_out, "records": records,
                      "counts": {"alerts": len(ds.alerts), "hits": len(results), "customers": len(ds.customers)}})

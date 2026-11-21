#!/usr/bin/env python3
"""Score decisions against the practice labels.

    python3 evaluate.py --data dataset [--verbose]
"""
import argparse
import sys
from collections import Counter

from screening.data import load, as_list, s
from screening.engine import Engine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    ds = load(args.data)
    eng = Engine(ds)
    labels = ds.labels
    by_alert = {}
    for lab in labels:
        by_alert.setdefault(s(lab.get("alert_id")), []).append(lab)
    res = {}
    for aid in by_alert:
        for r in eng.decide_alert(ds.alert_by_id[aid]):
            res[r["hit_id"]] = r
    n = len(labels)
    dec_ok = code_ok = cust_ok = 0
    ev_p = ev_r = 0.0
    worst = 0
    conf = Counter()
    for lab in labels:
        hid = s(lab.get("hit_id"))
        r = res.get(hid)
        gold = s(lab.get("decision"))
        codes = [s(c) for c in as_list(lab.get("reason_codes"))]
        custs = [s(c) for c in as_list(lab.get("customer_record_ids"))]
        gold_ev = set(s(e) for e in as_list(lab.get("evidence")))
        if r is None:
            print("MISSING", hid)
            continue
        conf[(gold, r["decision"])] += 1
        d_ok = r["decision"] == gold
        c_ok = r["reason_code"] in codes
        cr = r["customer_record_id"]
        cu_ok = (cr in custs) if custs else (cr is None)
        if gold == "SAME_ENTITY" and r["decision"] == "DIFFERENT_ENTITY":
            worst += 1
        ev = set(r["evidence"])
        p = len(ev & gold_ev) / len(ev) if ev else (1.0 if not gold_ev else 0.0)
        rc = len(ev & gold_ev) / len(gold_ev) if gold_ev else 1.0
        dec_ok += d_ok
        code_ok += d_ok and c_ok
        cust_ok += cu_ok
        ev_p += p
        ev_r += rc
        if args.verbose or not (d_ok and c_ok and cu_ok) or (p < 1 or rc < 1):
            flag = "OK " if (d_ok and c_ok and cu_ok) else "BAD"
            print(f"{flag} {hid} gold={gold}/{codes} cust={custs} ev={sorted(gold_ev)}")
            print(f"     got={r['decision']}/{r['reason_code']} cust={cr} ev={sorted(ev)}")
            if not (d_ok and c_ok and cu_ok):
                print(f"     ref: {s(lab.get('reference_reason'))}")
                print(f"     our: {r['explanation']}")
                print(f"     path: {' | '.join(r['path'])}")
    print()
    print(f"decision accuracy  {dec_ok}/{n}")
    print(f"decision+code      {code_ok}/{n}")
    print(f"customer record    {cust_ok}/{n}")
    print(f"evidence precision {ev_p / n:.3f}  recall {ev_r / n:.3f}")
    print(f"SAME cleared as DIFFERENT (worst error): {worst}")
    print("confusion (gold, got):", dict(conf))


if __name__ == "__main__":
    main()

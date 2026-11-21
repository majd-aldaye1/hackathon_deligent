# Namesake: is the hit the customer?

Track 2 (sanctions screening) of the Grok Bot × Diligent London Financial Crime Hackathon.

For every screening hit, Namesake decides `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`. Each decision comes with one reason code, the records it rests on, and the customer record it resolved. It follows Diligent's screening SOP (`POLICY.md`) as deterministic rules, so every decision can be traced and explained, and an analyst can audit it in the console.

| On the 50 practice labels | |
|---|---|
| Decision | **50 / 50** |
| Decision + reason code | **50 / 50** |
| Customer record | **50 / 50** |
| Evidence precision / recall | **1.00 / 1.00** |
| Customer cleared when it was a true match (the worst error) | **0** |

The whole development set (440 alerts, 819 hits, 72k customers) runs in about 2 seconds. It uses only the Python standard library and needs no installs.

## Run it

```bash
# 1. decide every hit (reads dev/*.jsonl from the data room, or the CSV browse export)
python3 run.py --data dataset                  # → out/decisions.jsonl, out/decisions.csv, out/trace.json
python3 run.py --data /path/to/unseen          # the unseen set, same format

# 2. score against the practice labels
python3 evaluate.py --data dataset

# 3. open the analyst console
python3 serve.py                               # → http://localhost:8000
```

Each line of `out/decisions.jsonl` looks like this:

```json
{"hit_id": "H-582410", "alert_id": "A-145983", "decision": "SAME_ENTITY",
 "reason_code": "NAME_DOB_LOCATION_MATCH", "customer_record_id": "CUS-377745",
 "evidence": ["CUS-377745", "NOTE-14E25A"],
 "explanation": "The customer's date of birth 1968-03-05 (NOTE-14E25A) agrees with the hit's 1967 or 1968. ..."}
```

`customer_record_id` is `null` when no record fits, and `AMBIGUOUS` when several people fit.

## How it decides (SOP principle → code)

| SOP | What Namesake does | Where |
|---|---|---|
| 2. Know the customer | Follows `account_ref`, `login_handle` or `email`. Joint accounts are split by the screened details. With no link, it searches all 72k records by name (fuzzy, variant-aware index), date of birth, country and city. | `Engine.resolve`, `Engine.fits` |
| 3. One person, one picture | Union-find over records that share a phone and the full date of birth, or a document number on an approved check. If several people fit, each is decided and the results combined (`AMBIGUOUS_CUSTOMER_RECORD` when they disagree). | `Engine._build_people`, `decide_alert` |
| 4. Verified beats declared | Uses the latest approved check, from the KYC provider table or from onboarding notes (about 100 phrasings, parsed generically). Rejected and expired checks are ignored. | `Engine.person`, `parse_kyc_note` |
| 5. The hit's facts | Date of birth from the `dobs` field, the first paragraph of the profile notes ("aged 30 in Nov 1998" gives 1967/1968), or search results that match the listing kind and a country tied to the hit. Dated reports come from "According to …; Month D, YYYY:" lines. | `hit_facts`, `profile_note_dobs`, `snippet_about_hit` |
| 6. Clear only on a contradiction | Checks type, date of death, time (report year minus birth year is under 16, or a company incorporated after the report), date of birth (all hit dates more than 1 year off, or the month or day differs), verified name, and location. A country difference alone never clears a hit whose name and date of birth agree. | `_decide_one` |
| 7. Confirm only on agreement | A person is confirmed on name + date of birth; a company on name + country. | `_decide_one` |
| 8. Names | Folds case, accents and punctuation; drops brackets, initials, placeholders and legal forms. Parts match if identical, if `name_variants.json` lists them together, if written together or apart, or within the length-based edit distance. Names agree on 2+ matching parts, or when every part of the shorter name matches. | `screening/text.py` |
| 9. Cite | Evidence is the sources of the facts behind the decision: country sources, the date-of-birth source, and search results used for the hit's date of birth. | `_decide_one` |

When in doubt it returns `REVIEW`. Every rule that clears a hit errs towards not clearing; for example, the age rule uses the oldest the customer could have been.

## Analyst console

`serve.py` serves `ui/index.html`, a single-file console with no dependencies:

- an alert queue with filters (cleared, escalated or review; reason code; practice-labelled only);
- an outcome banner per alert;
- the step-by-step customer resolution path;
- the merged person card: records, verified identity, and countries with their sources;
- a per-hit table comparing customer and hit (type, name, date of birth, location, earliest report, date of death);
- a drawer that opens the raw record behind any ID you click.

Keys: `j`/`k` to move, `/` to search.

## Layout

```
screening/text.py    names (principle 8), dates, countries
screening/data.py    JSONL/CSV loader and indexes
screening/engine.py  resolution, facts, decisions
screening/trace.py   evidence trail for the UI
run.py  evaluate.py  serve.py  ui/index.html
```

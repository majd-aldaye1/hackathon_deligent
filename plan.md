# Same Person or Not? — implementation plan

## 1. Summary

For each of the ~550 unseen hits we decide `DIFFERENT_ENTITY` / `SAME_ENTITY` / `REVIEW` on
identity alone. The system resolves the **customer** behind the alert (link → records → person
merge → verified picture), gathers the **hit's** facts (fields, profile notes, anchored search
results), and then runs a **pure, deterministic rules engine** that implements POLICY.md's
principles 6–8. Every fact carries the record IDs it came from, so `evidence` falls out of the
facts the firing rule used, and `reason` is a template filled from those same facts. Because a
false clear costs 60 against 3 for an unnecessary review, a clear is emitted only when a POLICY
contradiction fires on facts that are actually present; any unknown fact blocks a clear, and any
exception yields `REVIEW` / `INSUFFICIENT_DATA`. The LLM (OpenRouter, optional) only reads free
text and only as a fallback behind regex, with verbatim-quote grounding; it never decides.

```
 Alerts ─┐
Accounts │  1. Customer resolver        customer fact sheet
Onboard. ├─► link → candidate records ─► (name, DOBs, countries,  ─┐
KYC      │    → person merge (union-find) verified legal name,     │
Customers│    → verified picture          each with source_ids)    │
Notes   ─┘                                                         ├─► 3. Rules engine ─► decision
                                                                   │      (contradictions first,
 Hits ───┐  2. Hit fact gatherer        hit fact sheet             │       then agreement, else
Search ──┴─► fields, profile notes,  ─► (names/aliases, type, ────┘        REVIEW) + reason_code
             dated reports, death,      DOBs, countries, death,            + evidence + reason
             anchored search results    earliest dated report)
```

---

## 2. The data room

`dev/` holds the real development set: one JSON Lines file per table, plus `POLICY.md` and
`name_variants.json`. It is **gitignored and never committed** — the brief forbids it, and the
earlier CSV browse export has been deleted from the working tree and untracked (it is still in
history at `2a4c291`, which only a history rewrite would remove; say the word).

The system reads this folder and nothing else. `system/run <data_folder> <output_file>`.

### 2.1 What the real format turned out to be

Verified against `dev/` directly. Two shapes differ from the workbook export and would have broken
a loader written to the CSV column names:

| | Real JSON Lines |
|---|---|
| **Alerts** | The screened details are **nested**: `{"alert_id", "screened_at", "customer": {"name", "entity_type", "dob", "country", "city"}, "account_ref", "login_handle", "email", "hit_ids": [...]}`. There is **no** `customer_name`, `entity_type`, `dob`, `country`, `city` at the top level and **no** `hit_count`. The loader flattens `customer` into those five fields. |
| **Hits** | `details` is an **object** keyed by listing kind (`{"pep": "..."}`), `relationships` is a list, `match_score` is a number, and there are five fields the export did not show: `first_name` (357), `middle_name` (95), `last_name` (357), `best_matching_name` (474) and `subcategories`. |
| **Practice labels** | `reason_codes`, `customer_record_ids`, `evidence` and **`path`** are all lists. |
| **Everywhere** | Absent values are `null`, not `""`. |

`name_variants.json` is `{"description": str, "groups": [[...]] (55), "company_legal_forms": [...] (30)}`.

**`POLICY.md` is substantively identical** to the text recovered from the Policy tab — same nine
principles, same reason-code table, word for word. Nothing in sections 3–5 below needed revising,
and **every count in section 3 reproduces exactly on the real folder**, including the dated-report
counts, so the workbook's 32 000-character truncation never bit.

There is **no `validate.py`** in the data room, so `tools/score.py` (step 8) implements the format
check and the published cost matrix.

### 2.2 How the loader protects against the unseen set

- Each file is identified by **its filename, then by the fields its records carry**, so a renamed
  file is not a total failure.
- Every multi-valued field is accepted as a JSON list **or** a `"; "`-joined string; every scalar
  as a string, number, `null` or nested object.
- `tools/audit.py` re-derives every count in section 3, so a format change shows up as a changed
  number rather than as a silently wrong decision.

---

## 3. Data findings

### 3.1 Shape

| Table | Rows | Key fields |
|---|---|---|
| Alerts | 440 | `alert_id, screened_at, customer{name, entity_type, dob, country, city}, account_ref, login_handle, email, hit_ids` |
| Hits | 819 | `hit_id, alert_id, match_score, entity_type, name, first_name, middle_name, last_name, best_matching_name, aliases, gender, dobs, place_of_birth, life_status, deceased_date, nationality, citizenship, countries, addresses, identifiers, categories, subcategories, primary_category, position_or_allegation, details, relationships, profile_notes, sources, source_urls` |
| Customers | 72 265 | `record_id, entity_type, full_name, preferred_name, login_name, dob, nationality, residence_country, city, address, email, phone, occupation, employer, registration_number, onboarded_at, status, last_kyc_refresh` |
| Accounts | 86 659 | `account_id, customer_id, login_handle, phone, opened_at, status` |
| Onboarding | 72 265 | `account_id, customer_id, kyc_applicant_id, onboarded_at` |
| KYC checks | 54 488 | `check_id, applicant_id, provider, verified_name, verified_dob, document_type, document_number, document_country, result, checked_at` |
| Notes | 31 895 | `note_id, requester_email, created_at, channel, text` |
| Search results | 16 882 | `result_id, query, title, snippet, source` |
| Practice labels | 50 | `hit_id, alert_id, decision, reason_codes, customer_record_ids, evidence, reference_reason, path` |

### 3.2 Joins (all measured, zero dangling links)

- `Alerts.account_ref` → `Accounts.account_id`: 170 alerts, **0 misses**. 52 accounts have **two**
  customer_ids (joint holders) → 58 of those 170 alerts resolve to 2 people.
- `Alerts.login_handle` → `Accounts.login_handle`: 70 alerts, 0 misses, handle is globally unique → always 1 customer.
- `Alerts.email` → `Customers.email`: 54 alerts, 0 misses, email unique → always 1 customer.
- No link: **146 alerts (33 %), 262 hits** — must be resolved by screened attributes.
- `Onboarding` is keyed uniquely on `(account_id, customer_id)`; every customer has exactly one
  onboarding row; no account maps to two customers in Onboarding (so the **both-key join matters**:
  joining on `account_id` alone would attach a joint holder's applicant to the wrong person).
- `Onboarding.kyc_applicant_id` → `KYC checks.applicant_id`: 72 265 distinct applicant ids, only
  **49 574 appear in KYC checks**. So **22 691 customers (31 %) have no provider check at all** — their
  verified picture, if any, exists only as a `channel="kyc"` note.
- `KYC.result` ∈ `{approved: 49 574, rejected: 2 481, expired: 2 433}`. Every applicant that appears
  has exactly one approved check (plus at most one rejected/expired). 1–2 checks per applicant.
- `Customers.email` → `Notes.requester_email`.

### 3.3 Alert shape

- Link types: `account_ref` 170 · `login_handle` 70 · `email` 54 · none 146. Never more than one link field.
- Linked alerts carry **either nothing else or just `dob`** (188 bare / 106 with dob).
- Unlinked alerts **always** carry `dob` **and** `country`, and 76/146 also carry `city`.
- `entity_type`: 395 Individual / 45 Company. Alert type vs hit type: 701 Ind/Ind, 117 Co/Co, and
  exactly **one** Company-alert / Individual-hit pair (`A-41F2A9` "Stadtwerke München GmbH" vs
  `H-5EEC5A` "Mun Chen") — the only `ENTITY_TYPE_MISMATCH` in dev.
- `hit_count` 1–15; 344 alerts have a single hit.
- `Alerts.city` is not always a city: `"United Kingdom"`, `"Savannah, GA"`,
  `"Cherry Hill, NJ / Wilmington, DE"`, `"Beirut, Lebanon"`, `"Norway"` all occur.

### 3.4 Hits

- `dobs` populated on only **152 / 819** (19 %). Formats: `YYYY` (240 values), `YYYY-MM-DD` (50),
  `YYYY-MM` (3); several per hit, `"; "`-joined, e.g. `"1996; 1997"`, `"1985-01-17; 1982-08-28; …"`.
- `life_status`: 351 Alive, 6 Deceased, 462 blank. `deceased_date` on only 4 (two Deceased hits have
  no date → cannot clear on `DECEASED`). One is partial: `"2022-03"`.
- Country-bearing fields: `countries` 58 %, `addresses` 83 %, `nationality` 13 %, `citizenship` 14 %,
  `place_of_birth` 8 %. `addresses` entries end in `"… , Country [Business]"` / `[Residency]` /
  `[PEP]` → strip the bracket tag, then take the last comma-part. `place_of_birth` is
  `"City, Region, Country"` → also last part. `"International"` (8) and `"Europe"` (4) must be dropped.
  Territories appear and must stay distinct: `Northern Mariana Islands`, `Macao Special Administrative
  Region of China`, `Puerto Rico`, `Jersey`, `British Virgin Islands`, `Kosovo`.
- `primary_category` blank on 345/819 → fall back to the first of `categories`.
- **Dated reports:** 273 hits contain `"According to"` and 807 lines begin with it, but only **215
  hits / 640 lines** match the strict form `According to …; <Month D, YYYY>: …`. Excluded by the
  strict form, as POLICY requires: `"According to … FIA …; June 2014: …"` (month-year only),
  `"According to United States -The System for Award Management (SAM):"` (no date), and **13 lines
  across 11 hits that put a `;` where the form has a `:`** (`"…; October 10, 2024; On October 10 …"`)
  — 5 of those hits have no other dated report (see D22).
- **DOB clue in the first paragraph:** 393 hits have notes but no `dobs`; of those, **68** have a
  first paragraph that is one short line. Two families:
  - explicit — `"Yahaya Abubakar Abdullahi was born in 1952."`, `"… was born on 17 July 1939."`
  - age-at-date, **every wording unique** — `"…, aged 30, in November 1998."`,
    `"November 1998 saw …, a 30-year-old, face charges."`,
    `"When investigators conducted questioning of … in January 2023, he was 46."`,
    `"Investigators questioned … in January 2025, when he reached the age of 38."`,
    `"At the time … faced charges in March 1999, he was 24."`,
    `"… was 25 when taken into custody during February 1986."`,
    `"Questioning of … occurred in June 2006, at which point he was 27."`,
    `"<Month YYYY> marked the date …, then NN, was placed under charge."`
  - decoys in the same slot: `"On June 14, 2024, OFAC added Tor Fredrik Vejdeland to its SDN List."`
    (date, no age), `"Associated with Sanctioned Entity: DAD, KARIM - Entity ID: 13938136"` (big
    number, no date). So an age **cue** is required, not just "a small number".

### 3.5 Search results

- 1 758 distinct `query` values, 16 882 results, 2–54 per query.
- **Query normalisation solved:** strip accents and punctuation, lowercase, **drop single-letter
  tokens**, **keep duplicates**, sort the remaining words alphabetically, join with one space.
  Under that rule **every one of the 702 individual hits** maps to an existing query. Evidence:
  28 hits only match once single letters are dropped (`"Paul P Griffin"` → `griffin paul`), and 6 hits
  break if duplicates are de-duplicated. Companies (117 hits) have **no** search results at all, so
  legal-form handling in the query key is moot.
- Listing phrases: each of the six POLICY phrases occurs verbatim, and **never two in one result**.
  6 679 results carry exactly one phrase; **10 203 (60 %) carry none** — those are the namesake noise
  and can never anchor.
- Countries in snippets appear as names *and* demonyms (`"Brazilian authorities"`,
  `"a Netherlands resident"`, `"within Cote D'Ivoire"`), so the anchor's country test needs the
  demonym table.
- Age + date extraction is **fully deterministic**: in all 6 679 anchored snippets there is exactly
  one standalone 1–3 digit number (the age), and in 6 674 exactly one `Month YYYY`; the other 5 have a
  bare year plus a separate month (`"A 2006 news report … that July."`) and still parse off the year.
  **No LLM needed for search results.**

### 3.6 Bank-side quirks

- **Dates come in 7 formats** and `Customers.dob` / `KYC.verified_dob` / `Alerts.dob` mix them freely:
  `YYYY-MM-DD` · `DD/MM/YYYY` · `D Month YYYY` · `Month D, YYYY` · `YYYY` · `YYYY-MM` ·
  `Month YYYY`. With those seven, **0 of 126 753 date strings fail to parse**.
  `DD/MM/YYYY` is day-first: 6 348 values have a first component > 12 and none has a second > 12.
  `Month YYYY` is rare but decisive — `A-C21BD3` only resolves because `CUS-401918.dob` is
  `"February 1968"` and matches the screened `"1968-02"`.
- `Customers.login_name` is **empty in all 72 265 rows**; the login name that matters is
  `Accounts.login_handle`. Read `login_name` anyway in case the unseen set populates it.
- Countries arrive as names, **ISO-2 codes** (`US, GB, DE, NG, BD, …`) and **demonyms**
  (`American, British, Nigerian, Bangladeshi, Dutch, …`) — 120 distinct bank-side strings.
- **Placeholders** actually present in customer names: `N/a` (104), `0000` (100), `Xxx` (67),
  `Test` (26), `NA` (7), `Unknown` (1) — 179 customers, e.g. `"Paweł N/a N/a"`, `"Sani 0000 0000"`,
  `"0000 Barajas"`, `"Martin Xxx Xxx"`. After dropping them these have **fewer than two real parts** →
  per principle 8 they can be neither confirmed nor cleared on name.
- **Person merging is real but small:** 116 pairs share phone + full DOB, 7 pairs share an approved
  document number; max group size 2. **164 phone values are shared** overall, so ~48 shared-phone
  groups must *not* merge (the family-member trap).
- Notes: `channel` ∈ `kyc` (22 575) · `phone` (5 091) · `app` (2 146) · `email` (2 083).
  - `kyc` notes record **approved** verifications only (no rejection/expiry wording exists in dev),
    in ~13 sentence templates × provider × document × country, with the subject's name in **CAPS**
    and the DOB in any of the four full-date formats. They appear **exactly for the 31 % of customers
    with no provider check** — in dev a customer never has both, so there is no precedence conflict.
  - **Places lived is deterministic:** of the 9 320 non-`kyc` notes, 3 067 mention a country and
    **every single one is a residence/employment statement**; **none mentions two countries**; the
    other 6 253 are generic support notes with no country at all. Wording is unique per note
    (1 546 skeletons / 1 591 notes) but the *country name* is literal, so a country-vocabulary scan
    gets them all. The LLM is a genuine fallback here, not the primary path.

### 3.7 Practice labels — what they teach

Distribution: **28 DIFFERENT_ENTITY · 12 SAME_ENTITY · 10 REVIEW**, over 46 distinct alerts.

| reason_code (as the first listed) | count |
|---|---|
| `LOCATION_MISMATCH` | 17 |
| `DOB_MISMATCH` | 7 |
| `NAME_MISMATCH_VERIFIED` | 3 |
| `TEMPORAL_IMPOSSIBILITY` | 1 |
| `NAME_DOB_LOCATION_MATCH` (+ `NAME_DOB_MATCH`) | 8 |
| `NAME_LOCATION_MATCH` | 4 |
| `INSUFFICIENT_DATA` | 10 |

`DECEASED`, `ENTITY_TYPE_MISMATCH` and `AMBIGUOUS_CUSTOMER_RECORD` **never appear** — they must still
be built (dev has 6 Deceased hits and 1 type mismatch; the unseen set will exercise them).

Link paths used: `account_ref` 22 · `login_handle` 11 · `email` 5 · unlinked 12 (of which 2 ambiguous).

Decisive learnings:

1. **`reason_codes` is a set of acceptable answers**, in a fixed order
   (`TEMPORAL_IMPOSSIBILITY`, `DOB_MISMATCH`, `LOCATION_MISMATCH`, `NAME_MISMATCH_VERIFIED`), and the
   reference `reason` states the sentences in that same order. `SAME_ENTITY` lists
   `NAME_DOB_LOCATION_MATCH; NAME_DOB_MATCH` together.
2. **`customer_record_ids` is also a set** — all records of the resolved person are accepted
   (`"CUS-775419; CUS-138588"`).
3. **`evidence` is tight**: only the records that supplied the deciding facts.
   `H-2808BE` → `KYC-20EE17` **alone** (the verified name decided it; the customer record is *not*
   cited). `H-D861DA` → `NOTE-8548C1` alone. `H-622EDD` → `NOTE-CA9BBC; SR-A88751` (customer DOB +
   the search result that gave the hit's DOB). `LOCATION_MISMATCH` cites every record that supplied
   a customer country (`CUS-562751; KYC-63356F; NOTE-2EF1F0`). Hit IDs are **never** evidence.
4. For `REVIEW`/`SAME` the cited country source is the one that **matches**: `H-FF3096` →
   `NOTE-10AEAB` only — the customer record says Australia, the note says the customer lived in the
   United States, the hit is United States, so only the note is cited.
5. **Both ambiguous cases decided to the same answer**, so the code is `INSUFFICIENT_DATA`, not
   `AMBIGUOUS_CUSTOMER_RECORD`, while `customer_record_id` is still `"AMBIGUOUS"`.
6. Reason text is formulaic — the templates in §5.4 are lifted from the reference reasons.
7. `H-CF173B`: hit `John Whitfield` vs verified `Jonathan Reyes Whitfield` **is** a name mismatch —
   `john`/`jonathan` is 4 edits, is not a `name_variants` group, and `Whitfield` alone is one part.
   Confirms "≥2 parts, shorter part's length sets the threshold" literally.

### 3.8 Resolver prototype (already measured)

A throwaway prototype of the unlinked resolver (blocking index on name parts → principle-8 name
agreement → DOB equal in shared parts → screened country as nationality **or** residence → screened
city in city **or** address) over all 146 unlinked alerts: **100 alerts → 1 record, 28 → 2, 6 → 3,
1 → 4, 1 → 5, 2 → 6, 8 → 0 records**, in 2 s for the whole file including loading 72 k customers.
Against the 12 unlinked practice labels it reproduced the expected record set in **12/12** once
`Month YYYY` parsing was added (two apparent misses were a merged second record and the `Month YYYY`
bug). The 8 zero-candidate alerts look like genuine "customer not in the system of record" cases
(e.g. `A-ADCA3F` "Farah Damji" — four namesakes, none matching DOB **and** country **and** city) →
`customer_record_id = null`, no clearing, `REVIEW`.

---

## 4. Decision log

| # | Decision | Options | Chosen | Evidence | Date |
|---|---|---|---|---|---|
| D1 | Input format | — | **JSON Lines from the given folder** | the data room ships `dev/*.jsonl`; confirmed against the real folder | 2026-11-21 |
| D2 | File discovery | fixed filenames / sniff by field names | **filename first, then field signature** | the real filenames are `alerts.jsonl` … `practice_labels.jsonl`; the signature fallback costs ~20 lines and removes a total-failure mode if the unseen set renames a file | 2026-11-21 |
| D3 | Field shapes | assume one encoding / accept several | **accept several**: multi-valued fields as a list or a `"; "` string; scalars as string, number, `null` or nested object; the alert's `customer` object flattened | the real folder uses lists, `null` and a nested `customer`; accepting more costs nothing | 2026-11-21 |
| D4 | **Q1** screening date | `Alerts.screened_at` / note dates / today | **`Alerts.screened_at`** | only date on the alert; 2026-10..11 values; `DECEASED` needs "before the customer was screened" | 2026-11-21 |
| D5 | **Q2** "expired" check | `result` value / an expiry date / vs screening date | **`result` field**: use `result == "approved"`; `rejected`/`expired` are not evidence | `result` ∈ {approved, rejected, expired}; there is no expiry-date column | 2026-11-21 |
| D6 | **Q3** no customer found | screened details may clear / only locate | **only locate** — never clear; `customer_record_id = null`, `REVIEW`/`INSUFFICIENT_DATA` | POLICY principle 2 frames screened details as the *search key*; principle 9 says `null` if none found; clearing on the screened name alone would risk the 60-cost error | 2026-11-21 |
| D7 | **Q4** no approved KYC | declared facts may clear / may not | **declared `dob`/countries may clear** (DOB, location, temporal); **`NAME_MISMATCH_VERIFIED` requires a verified legal name** and never fires on a declared name | principle 6 "Location" names "residence and nationality on all their records"; principle 6 "Name" says *verified* legal name "even if the name on their record does" agree | 2026-11-21 |
| D8 | **Q5** `customer_record_id` | first / lowest / AMBIGUOUS rules | **one person → the lowest record_id of that person** (any is accepted); **>1 person → `"AMBIGUOUS"`**; **none → `null`** | labels accept any of a person's records (`CUS-775419; CUS-138588`); both multi-person labels use `"AMBIGUOUS"` | 2026-11-21 |
| D9 | **Q5** evidence rule | everything looked at / only deciding facts | **union of `source_ids` of the facts the firing codes used**; for an agreeing country only the matching sources; hit ids never cited | `H-2808BE` → `KYC-20EE17` alone; `H-FF3096` → `NOTE-10AEAB` alone (see §3.7.3–4) | 2026-11-21 |
| D10 | **Q5** multi-person same answer | `AMBIGUOUS_CUSTOMER_RECORD` / the shared decision | **the shared decision + its own code**, `customer_record_id="AMBIGUOUS"`; `AMBIGUOUS_CUSTOMER_RECORD` only when the people disagree | `H-6C7985`, `H-CDEC83` → `REVIEW`/`INSUFFICIENT_DATA` with `AMBIGUOUS`; POLICY principle 3 | 2026-11-21 |
| D11 | **Q6** search `query` key | several normalisations | **combining marks stripped, every other non-ASCII letter dropped (not transliterated), lowercased, single-letter tokens dropped, duplicates kept, sorted, space-joined**; the transliterated spelling is looked up as well | 702/702 individual hits map to a real query; 28 need single-letter dropping, 6 break under de-duplication, and 4 (`"Drozd, Tomasz Paweł"` → `drozd pawe tomasz`) break under transliteration | 2026-11-21 |
| D12 | **Q6** date formats | ISO only / full set | **7 parsers**: `YYYY-MM-DD`, `DD/MM/YYYY` (day-first), `D Month YYYY`, `Month D, YYYY`, `Month YYYY`, `YYYY-MM`, `YYYY` | 0/126 753 unparsed; `A-C21BD3` needs `Month YYYY` | 2026-11-21 |
| D13 | **Q6** placeholders | guess a list / take from data | `na`, `n/a`, `n.a.`, `test`, `unknown`, `xxx`(+runs of x), `none`, `nil`, `tbd`, `dummy`, `sample`, `placeholder`, `not provided`, and any all-digit token | observed: `N/a`, `0000`, `Xxx`, `Test`, `NA`, `Unknown`; POLICY says "digits and the like" | 2026-11-21 |
| D14 | Reason-code order | arbitrary / fixed | **fixed**: `ENTITY_TYPE_MISMATCH` → `DECEASED` → `TEMPORAL_IMPOSSIBILITY` → `DOB_MISMATCH` → `LOCATION_MISMATCH` → `NAME_MISMATCH_VERIFIED`, then `NAME_DOB_LOCATION_MATCH` → `NAME_DOB_MATCH` → `NAME_LOCATION_MATCH`, then `AMBIGUOUS_CUSTOMER_RECORD` → `INSUFFICIENT_DATA` | "any of them is accepted", but reproducibility is 10 % of the score; the label order matches the middle four | 2026-11-21 |
| D15 | Country keys | ISO codes only / full table + identity fallback | **hand-built table** (ISO-2, names, demonyms → one key) **plus identity fallback** for unknown strings (accent-stripped, lowercased) | 120 bank-side + 138 hit-side strings; identity fallback keeps territories distinct and prevents an unmapped string from faking a match *or* a mismatch | 2026-11-21 |
| D16 | Hit DOB from search | always / only when fields and notes give none | **only when `dobs` and the profile notes give none** | POLICY principle 5 priority order | 2026-11-21 |
| D17 | `DECEASED` source | `deceased_date` only / also parse notes | **`deceased_date` only** (partial-aware); `life_status == "Deceased"` without a date cannot clear | POLICY: "gives a date of death"; 2 of 6 Deceased hits have no date | 2026-11-21 |
| D18 | Customer countries from notes | regex country scan / LLM first | **regex scan of non-`kyc` notes for a country-vocabulary name; LLM only when the scan finds none** | 3 067/3 067 country-mentioning non-kyc notes are residence statements, none names two countries | 2026-11-21 |
| D19 | KYC note vs provider check | note only as fallback / merge both | **merge both, use the most recent approved** | POLICY principle 4 ("whether … by the KYC provider or only in a note"); in dev the two never co-occur, so either reading scores the same, and merging is the faithful one | 2026-11-21 |
| D20 | LLM scope | also name/anchoring/decisions | **only** (a) hit first-paragraph DOB clues, (b) customer-note places lived and note-recorded KYC results; grounded by verbatim quote; `--no-llm` and auto-fallback | brief §5; regex already covers search results 100 % and places-lived 100 % on dev | 2026-11-21 |
| D21 | Entity type comparison | alert type vs hit / customer type vs hit | **resolved customer's `entity_type` vs hit's**; with no customer, no type rule | POLICY principle 6 "one is a person and the other a company" is about the customer; the single dev case (`A-41F2A9`) resolves to a Company customer vs an Individual hit either way | 2026-11-21 |
| D22 | Dated-report punctuation | accept `;` after the date / require `:` | **require `:`** — exactly the form POLICY gives | POLICY: "exactly the English lines … of the form"; 13 lines across 11 hits use `;`. Dropping a report can only move the *earliest* report later, which makes the customer older and a `TEMPORAL_IMPOSSIBILITY` clear less likely — the safe direction against the 60-cost error | 2026-11-21 |
| D23 | Branch | `main` / `dev` | **`dev`** — all work and commits land there | `origin/main` holds a separate complete submission (`4c8e5cd`, `442a9f9`); the user chose to keep this build on `dev` and leave `main` untouched | 2026-11-21 |
| D24 | A customer name with one real part | may agree / require two matched parts | **may agree**, exactly as principle 8 says ("every part of the shorter name matches") | `preferred_name` is often a bare given name, so this widens the unlinked search. Requiring two matched parts moves ambiguity only 27 → 26 but **loses the customer on 7 unlinked alerts**, and 30 alerts screen a name with fewer than two parts anyway. Extra persons can only make principle 3's unanimity *harder*, so they make clearing less likely, not more — the safe direction | 2026-11-21 |
| D25 | A verified field the newest check omits | leave it unknown / fall back to an older approved check | **fall back to the most recent approved check that states it** | POLICY names "the most recent approved identity check" as the source for all three fields, but 1 850 provider checks carry no `verified_dob` and 8 note-recorded ones carry no country. An older *approved* check is still verified evidence, and leaving the field unknown would silently demote the customer to their declared data | 2026-11-21 |

---

## 5. Implementation steps

Status key: `[ ]` not started · `[x]` done. Every step ends with its acceptance test green and a commit.

### Step 1 — Repo skeleton, loader, indexes, audit script — **[x] done**
- **Goal.** A `system/` package that loads the data folder into typed records with O(1) indexes,
  plus a `tools/audit.py` that reprints section 3's counts so a format change is caught immediately.
- **Files.** `system/model.py`, `system/loader.py`, `tools/audit.py`, `tests/test_loader.py`, `.gitignore`.
- **Notes.** Identify files by name then by field signature (D2); normalise every multi-valued field
  to a list of strings and every scalar to a string (D3); flatten the alert's nested `customer`
  object. Indexes: accounts by `account_id`, `login_handle`, `customer_id`; customers by `record_id`,
  `email`; onboarding by `(account_id, customer_id)` **and** by `customer_id`; kyc by `applicant_id`;
  notes by `requester_email`; search results by `query`; hits by `alert_id`. The blocking index is
  built on demand through `Dataset.name_index(tokenize)`, so the loader holds no name logic.
- **Acceptance — met.** `tools/audit.py dev` reproduces every count in sections 3.1–3.6.
  `python3 -m unittest discover -s tests` → **155 tests pass**, of which 22 cover the loader:
  all nine tables identified from files named `table_01.jsonl` … `table_09.jsonl`; accounts not
  confused with onboarding; the nested `customer` object flattened (including `null` → `""`);
  list fields preserved; a `details` object rendered as readable text that keeps its keys; numbers
  stringified; label aliases (`reason_code` → `reason_codes`) and the list-valued `path`; a JSON
  array file read as well as JSON Lines; and on the real folder — exact row counts, one file per
  table, screened details present on all 440 alerts, every alert carrying at most one link, no
  dangling link, `hit_ids` covering all 819 hits exactly once, and every label pointing at a real
  hit and alert. Whole-folder load: **2.1 s** (budget 10 s).
- **Findings.**
  - The real shapes are in section 2.1. Writing the loader against the CSV column names would have
    failed outright on alerts, whose screened details are nested.
  - `onboarding` has to be tested before `accounts`, because `{account_id, customer_id}` is a subset
    of onboarding's required fields.
  - **0 of 127 193** date strings in the folder fall outside the seven formats of D12.
  - `best_matching_name` and `first/middle/last_name` are extra hit names worth feeding to the name
    comparison: more candidate names make agreement easier, which makes a `NAME_MISMATCH_VERIFIED`
    clear **harder** — the safe direction.
  - The audit script keeps its own small date and query helpers because it is a diagnostic;
    `tests/test_folder_normalisation.py` asserts the real parsers in `system/` agree with it.

### Step 2 — Normalisation utilities (text, names, countries, partial dates) — **[x] done**
- **Goal.** Principle 8 implemented exactly, plus country keys and partial-aware dates.
- **Files.** `system/norm.py` (accents, brackets, punctuation, placeholders), `system/names.py`,
  `system/countries.py`, `system/dates.py`, `system/name_variants.py` (the 55 groups + 30 legal forms
  inlined, loaded from `name_variants.json` when the data folder has one).
- **Notes.** Name parts: drop bracketed text, strip accents/punctuation, lowercase, drop single letters
  (initials), drop placeholders (D13), drop legal forms for companies, keep each distinct part once.
  Part match: identical · same variant group · joined/split (`abdulsalam` ≡ `abdul`+`salam`, counting as
  one part covering both) · edit distance ≤ 1 for shorter length 4–6, ≤ 2 for ≥ 7, exact below 4 — the
  **shorter** part's length decides. Agreement: ≥ 2 matched parts, or every part of the shorter name
  matched. An individual with < 2 real parts is unusable for name confirm **and** for name clear.
  Dates: `(year, month|None, day|None)`, `year` may be a set of candidates; equality compares only
  parts both sides give. Countries: table (D15) + identity fallback; a helper takes the last
  comma-part after stripping `[tag]` suffixes.
- **Acceptance — met.** `python3 -m unittest discover -s tests` → **155 tests pass** (22 from step 1,
  133 new), in 16 s.
  - `tests/test_names.py` (48): a case per clause of principle 8, each quoting the sentence it tests —
    parts (case/accents/punctuation/brackets/initials/distinct-once/placeholders/legal forms),
    part matching (identical, variant group, <4 identical only, 4–6 one edit, ≥7 two edits, shorter part
    decides, a swap is two edits), joined-or-apart (`Abdulsalam` ≡ `Abdul Salam`, counting once, never
    reused), agreement (≥2 parts, or every part of the shorter name), aliases and nicknames, the
    `<2 real parts` guard, blocking tokens, the query key, and the four `name_variants.json` shapes.
    All ten practice-label name pairs decide correctly, including `john`/`jonathan` → **no**.
  - `tests/test_dates.py` (33): the seven formats, day-first slashes, abbreviated months, non-dates,
    `equal in every part both give`, agreement, contradiction (incl. "exactly one year out is **not** a
    contradiction" and "every hit date must be contradicted"), partial-aware `before`, and
    `max_age_at(2007, 2020-01-08) == 13`.
  - `tests/test_countries.py` (25): ten code/name/demonym groups collapse to one key; territories stay
    separate (Macao≠China, Hong Kong≠China, Puerto Rico≠US, Jersey≠UK, N. Mariana≠US); regions and
    placeholders are not countries; unknown strings equal only themselves; address/place-of-birth tails;
    free-text scanning incl. "a multi-word country is not split" and "two-letter codes are not looked
    for in prose".
  - `tests/test_folder_normalisation.py` (11): over the **whole folder** — all 127 193 date strings
    parse, every hit `dobs` and `deceased_date` parses, every bank-side and hit-side country string maps
    to a known country (**0 unmapped either side**), `International`/`Europe` are dropped and really
    occur, **702/702** individual hits map to an existing search query, **0/117** company hits have any,
    no non-kyc note names two countries and exactly 3 067 name one.
- **Findings.**
  - **D11 refined — the search `query` is built with a plain ASCII filter, not a transliteration.**
    `"Drozd, Tomasz Paweł"` is filed as `drozd pawe tomasz`: the stroked *l* is simply **dropped**. So
    `names.query_key` strips combining marks and then discards every non-ASCII letter, while name
    *comparison* transliterates (`Paweł` → `pawel`) — two different normalisations on purpose.
    `names.query_keys` returns both spellings and the gatherer looks up both, which costs nothing and
    cannot invent a match, since a result must still carry the listing phrase and a hit country.
  - `norm.strip_accents` needs a transliteration table: NFKD cannot decompose `ł ø ß æ đ ı þ`, so
    without it `Paweł` loses a letter instead of becoming `Pawel`.
  - Two bugs the country tests caught: multi-word aliases were being indexed word by word, so
    `"lived in the United Kingdom"` reported **United States** via a stray `united` key — 94 notes were
    affected; and Sweden's `SE` was suppressed as a company legal form, leaving 10 customer records with
    no country. Codes are now indexed only from the code field and aliases only as whole strings; only
    `NA` stays excluded, because it is a missing-value placeholder far more often than Namibia.
  - **257** individual records cannot be decided on name: the placeholder ones (`"Paweł N/a N/a"`,
    `"Sani 0000 0000"`, `"Martin Xxx Xxx"`) and the repeated-word ones (`"Lawal Lawal"`, `"Musa Musa"`,
    `"Abubakar ABUBAKAR"`), which have one part because "each distinct part counts once".
  - Name matching is an exhaustive best-matching over parts (memoised bitmask search, capped at 12
    parts), not a greedy pass, so "at least two parts match" means what it says and no part is counted
    twice.
- **Risks.** Over-generous edit distance manufactures name agreement and blocks a legitimate clear
  (cheap) or manufactures a `SAME` (cheap). Under-generous blocks a `NAME_MISMATCH_VERIFIED` clear.
  Both are low-cost; keep the literal reading.

### Step 3 — Customer resolver: linked alerts — **[x] done**
- **Goal.** `account_ref` / `login_handle` / `email` → candidate customer records, with the screened
  details picking between joint holders.
- **Files.** `system/resolve.py`, `tests/test_resolve_linked.py`
- **Notes.** `account_ref` → `Accounts.account_id` → all `customer_id`s (**52 accounts have two**);
  if > 1, apply the screened-detail fit test to choose; if several still fit, keep them all →
  ambiguity. `login_handle` → accounts; `email` → customers. The fit test is shared with step 4:
  each criterion is `True`, `False`, or **`None` when the alert did not screen on it**, so a detail
  the alert is silent about can neither support nor rule out a record. A link leading to exactly one
  record is **taken as it stands** — POLICY only uses the screened details "to pick between" several.
- **Acceptance — met.** **190 tests pass** (35 new). On the real folder: link kinds are
  170/70/54/146; every link resolves to ≥ 1 record; **58 alerts lead to two records and all 58 are
  `account_ref`**; the screened details separate **every one** of those 58 to exactly one record;
  every linked alert resolves to exactly one record; **all 38 linked practice labels** resolve to an
  accepted `customer_record_id`; resolution is identical across two runs.
- **Findings.**
  - All 58 joint-holder alerts separate on **name and date of birth together** — in every case the
    other holder is a family member with a different given name and a different DOB (`"Abdullahi
    Abubakar Sadiq"` vs `"Hannah Sadiq"`, `"Timothy Pangelinan Villagomez"` vs `"Emily Villagomez"`).
    The name alone separates all 58 as well, so no joint-holder choice rests on one criterion.
  - **No linked alert is ambiguous**, so `AMBIGUOUS_CUSTOMER_RECORD` can only arise from the
    unlinked search (step 4) or from person merging.
  - `Alerts.city` is only ever populated on **unlinked** alerts, so the city criterion does no work
    in this step — but it is built and tested here because the fit test is shared.
  - The city field needed splitting on `,` and `/` into alternatives (`"Cherry Hill, NJ / Wilmington,
    DE"`), with pieces under three letters dropped so a state code cannot match inside an unrelated
    word, and accent folding so screened `"München"` matches the record's `"München"`.

### Step 4 — Customer resolver: unlinked alerts, person merge, ambiguity — **[x] done**
- **Goal.** The 146 unlinked alerts, plus union-find person merging, plus the ambiguity verdict.
- **Files.** `system/kyc.py`, `system/persons.py`, `system/resolve.py`, `tests/fixture.py`,
  `tests/test_persons.py`, `tests/test_resolve_search.py`
- **Notes.** Blocking index on name parts **and their variant-group siblings** over 72 k customers,
  then the step-3 fit test. Merge: same phone **and** same **full** date of birth, **or** the same
  document number on approved checks; union-find for transitivity; the lowest record id is the
  representative, so `customer_record_id` never depends on file order. `system/kyc.py` holds the
  chain customer → accounts → onboarding on **both** keys → applicant → checks, shared with step 5.
- **Acceptance — met.** **228 tests pass** (38 new), 40 s. On the real folder: **every one of the
  440 alerts resolves to at least one person**; resolution paths are 170 `account_ref` / 70
  `login_handle` / 54 `email` / 146 `search`; **27 alerts are ambiguous and all 27 come from the
  search**; **all 50 practice labels** resolve to what they expect — every record the label lists is
  found, the reported `customer_record_id` is one the label accepts, and both ambiguous labels come
  back `AMBIGUOUS` with exactly the records their `path` names (`H-CDEC83`'s three records group into
  **two** persons, as its path says); resolution is identical across two runs; all 440 alerts resolve
  in **4 s**.
- **Findings.**
  - **123 persons hold more than one record** (116 merged by phone + full DOB, 7 by document number,
    no overlap), every one of them a pair. **88 shared-phone pairs are correctly left unmerged** —
    the family-member trap is real and the tests pin it.
  - **Nothing in dev resolves to "no customer".** The 8 alerts my Phase-A prototype could not resolve
    were its own bugs (the missing `Month YYYY` date format and a weaker name matcher). The
    no-customer path is still built and tested, because the unseen set may need it.
  - **D24 — a single-part customer name may agree** (new decision, logged below). `preferred_name` is
    often just a given name (`"Ibrahim"` on `CUS-497550`), and principle 8's "every part of the
    shorter name matches" makes it agree with any `"Ibrahim X"`. Measured both ways: requiring two
    matched parts would reduce ambiguity only from **27 to 26** while **losing the customer entirely
    on 7 unlinked alerts**, and 30 alerts screen a name with fewer than two parts in the first place
    (one-word company names like `"Pescanova"`, `"Binanfx"`). So the literal reading is kept.
  - Every customer in dev reaches **at most one** KYC applicant, and every onboarding row's
    `account_id` really belongs to the customer it names — both asserted, so the both-key join is
    verified rather than assumed.

### Step 5 — Verified customer picture — **[x] done**
- **Goal.** The person's fact sheet: verified legal name, dates of birth, countries, entity type,
  each carrying the record ids it came from.
- **Files.** `system/facts.py`, `system/kyc.py`, `system/notes_regex.py`,
  `system/customer_facts.py`, `tests/test_notes_regex.py`, `tests/test_customer_facts.py`
- **Notes.** `facts.Fact(value, source_ids)` is the unit everything is built from, so step 7's
  `evidence` is assembled from the facts the firing rule used and there is no second evidence
  pathway to keep in step. Approved checks come from the KYC provider **and** from
  `channel="kyc"` notes, merged and ranked by date. Countries = residence + nationality on **every**
  record of the person + the approved document country + places the notes say they lived. Notes are
  reached only through the emails on the person's own records.
- **Acceptance — met.** **294 tests pass** (66 new), 68 s. The verified name, date of birth and
  source id match **every** practice label that names one — 11 records checked by hand, including
  all six note-sourced ones (`NOTE-14E25A`, `NOTE-ADDA81`, `NOTE-302C97`, `NOTE-CB3D0D`,
  `NOTE-8548C1`, `NOTE-CA9BBC`) — and the country list matches **all 11** labels that name one
  (`CUS-364225` → Singapore, United States; `CUS-048448` → Bangladesh, United Kingdom; …).
  Across the 461 persons behind the 440 alerts: every one has a verified name and a verified date of
  birth, 440 of those names are usable for a name clear, none lacks a country, and 162 of the names
  come from a note rather than the provider. 461 fact sheets in 4 s.
- **Findings.**
  - **Note extraction works field by field, not template by template.** 22 567 of the 22 575
    `kyc` notes yield name, date of birth **and** document country; all 22 575 parse as approved
    checks. The 8 that withhold a field say "a national ID **dated** 1952-01-21" or
    "document provided: driving licence (United Kingdom), 23 June 1991" — wording that does not
    actually claim a birth date, so the fact stays unknown and the declared record date is used.
    These are the LLM fallback's job in step 10.
  - **A date of birth cannot be found by direction.** These notes carry two dates in either order
    (`"whose 1986-12-10 date of birth was confirmed on 2025-03-10"` and `"lists 06/01/1998 as her
    DOB, is valid as of 2024-08-15"`), so the rule is: the date **nearest** a birth cue wins, and a
    date introduced by "on" or "as of" is never eligible — unless a birth cue introduced it
    (`"born on 27/06/1969"`). Before this, 3 notes handed back the date of the check as the date of
    birth. Now **0 of 22 575** do, and **22 520 agree with the record's declared date**; the **14**
    that differ are the planted "verified beats declared" cases, including the practice labels'.
  - Names in notes are written in capitals, so `subject_name` takes the longest run of
    capitalised-throughout words — tested character by character, not with `[A-Z]`, so `FERNÁNDEZ`
    and `PAWEŁ` count. Label words (`DOB`, `ID`, `NAME`, …) and digit runs are excluded, and a
    one-word run is accepted because `"N/a Gilbert"` and `"Sani 0000 0000"` really are one-part names.
    Every quote is the verbatim span, which may carry punctuation the value drops (`"MD. SAIDUL
    ISLAM"` quoted, `MD SAIDUL ISLAM` as the name) — asserted over all 22 575 notes.
  - Approval cues are **stemmed** (`confirm\w*`, `vett\w*`, `pass\w*`), because the unseen set will
    conjugate them differently; a refusal cue outranks an approval cue. Before stemming, 94 notes
    read as "no check recorded" because they said "confirms" rather than "confirmed".
  - **D25 — a field the newest approved check omits falls back to the newest approved check that
    states it** (new decision, logged below). 1 850 provider checks carry no `verified_dob` at all.
  - **63 of the 461 persons have a verified legal name that agrees with none of their declared
    names** — the population `NAME_MISMATCH_VERIFIED` will be drawn from.

### Step 6 — Hit fact gatherer
- **Goal.** The hit's fact sheet with `source_ids` (the hit itself, and `SR-…` for search-derived facts).
- **Files.** `system/hit_facts.py`, `system/search_anchor.py`
- **Notes.** Names = `name` + `aliases` (strip `(AKA)`-style tags). Countries per §3.4 (drop
  `International`/`Europe`). DOB priority (D16): `dobs` → first paragraph (explicit `born in/on`, then
  the age-cue patterns: `aged NN`, `age of NN`, `NN-year-old`, `NN year old`, `, NN,`, `was NN`,
  `then NN`, `reached the age of NN`; require exactly one `Month YYYY` or one `Month D, YYYY` in the
  paragraph; age at a date → `{Y-age, Y-age-1}`) → anchored search results. Anchoring: the result's
  title+snippet contains the listing phrase of the hit's `primary_category` (else the first of
  `categories`) **and** a country tied to the hit (names and demonyms). Dated reports: strict regex
  `^\s*According to .*?;\s*(Month D, YYYY):` per line → earliest. Death: `deceased_date` (D17).
  Companies: only `dobs` is an incorporation date.
- **Acceptance.** `tests/test_hit_facts.py`: 214 hits have ≥ 1 dated report and the `June 2014` /
  `SAM:` lines are excluded; the strict earliest date of `H-13E1CF` is `2020-01-08`; the four
  deceased dates parse (incl. `2022-03`); `H-D861DA` → `{1976, 1977}`, `H-4AA437` → `{1986, 1987}`,
  `H-582410` → `{1967, 1968}`, `H-EC242D` → `{1967, 1968}`; `H-622EDD` and `H-FC22E2` get
  `{1972, 1973}` from `SR-A88751` / `SR-65C752`; the 10 203 phrase-free results anchor nothing.
- **Risks.** Over-eager first-paragraph parsing invents a DOB and causes a 60-cost clear → require an
  explicit cue, bail out on any ambiguity (two ages, two dates, a multi-line paragraph).

### Step 7 — Rules engine, evidence, reasons
- **Goal.** `(customer_facts, hit_facts) → (decision, reason_code, evidence, reason)`, pure and deterministic.
- **Files.** `system/rules.py`, `system/reasons.py`, `system/decide.py`
- **Notes.** Each rule is a function returning a result carrying the facts it used; evidence = union of
  those facts' `source_ids`, sorted (D9). Order D14. Contradictions: `ENTITY_TYPE_MISMATCH` (D21),
  `DECEASED` (death date < `screened_at`, partial-aware), `TEMPORAL_IMPOSSIBILITY` (customer < 16 at the
  earliest dated report, or company incorporated after it), `DOB_MISMATCH` (**every** hit DOB
  contradicted: birth year > 1 year outside, or same year and a differing month/day both give),
  `NAME_MISMATCH_VERIFIED` (needs a verified legal name with ≥ 2 real parts), `LOCATION_MISMATCH`
  (every customer country differs from every hit country — **except** when name **and** DOB agree,
  which is `REVIEW`). Agreement: person → `NAME_DOB_LOCATION_MATCH` / `NAME_DOB_MATCH`; company →
  `NAME_LOCATION_MATCH` **only**. Else `REVIEW`/`INSUFFICIENT_DATA`. Multi-person per D10.
  Reason templates (from the labels):
  - `"The customer was born in {Y} ({src}), so they were at most {age} when the hit's profile reports activity on {date}."`
  - `"The customer's date of birth is {dob} ({src}) but the hit's {listed date of birth is {d} | profile notes put its birth year at {y1} or {y2} | search results put its birth year at {y1} or {y2}}."`
  - `"The customer is linked only to {A, B} but the hit is linked only to {C}."`
  - `"The customer's verified name is {N} ({src}), which does not match the hit's name {H}."`
  - `"The customer's date of birth {dob} ({src}) agrees with the hit's {y1} or {y2}. Both the customer and the hit are linked to {C}. The customer's name agrees with the hit's name {H}."`
  - `"Both the customer and the hit are linked to {C}. The customer's name agrees with the hit's name {H}. Nothing in the customer's records contradicts the hit, and the date of birth cannot be compared with it, so the hit can be neither cleared nor confirmed."`
  - no-customer: `"No customer record in the system of record fits the alert's screened name {N}, date of birth {d} and country {c}, so the hit cannot be compared with a customer and is left for a person."`
- **Acceptance.** `tests/test_rules.py` has one case per code built from a fabricated fact sheet,
  including the location exception and "unknown ≠ mismatch"; all 50 practice labels re-decided from
  hand-written fact sheets give the label's decision.
- **Risks.** The location exception and the "every DOB" quantifier are the two easiest to get
  backwards — both get a dedicated test.

### Step 8 — `system/run`, end-to-end, first score
- **Goal.** Executable entry point, one JSON line per hit, in hit order; `output/dev.jsonl`.
- **Files.** `system/run` (executable, `#!/usr/bin/env python3`), `system/cli.py`, `tools/score.py`
- **Notes.** `system/run <data_folder> <output_file>`, reads only that folder, stdlib only.
  `--no-llm` flag; per-hit `try/except` → `REVIEW`/`INSUFFICIENT_DATA` with an honest reason (§9).
  `tools/score.py <pred> --labels dev/practice_labels.jsonl` implements the format check and the cost
  matrix, and reports **unsafe clears** (`DIFFERENT_ENTITY` where the truth is not) by name.
- **Acceptance.** 819 lines, format check passes, every `reason_code` belongs to its decision, every
  evidence id exists in the data; practice cost recorded; **unsafe clears = 0**; runtime < 2 min.
- **Risks.** `output/dev.jsonl` must always be regenerated, never edited.

### Step 9 — Error analysis on the practice labels
- **Goal.** Drive practice cost down by implementing principles more faithfully, never by special-casing.
- **Files.** `tools/explain.py` (one hit → full fact sheets + rule trace), fixes across `system/`
- **Notes.** Also settle the evidence variant (cite the name source in `REVIEW`/`SAME` or not, §3.7.4)
  by scoring both against the labels and logging the winner here.
- **Acceptance.** Every remaining practice disagreement has a one-line written explanation; unsafe clears still 0.
- **Risks.** Over-fitting 50 labels. Any change must be justified by a POLICY sentence, quoted in the commit.

### Step 10 — LLM fallback extractor
- **Goal.** Recover facts regex misses, without ever lowering precision.
- **Files.** `system/llm.py`, `system/llm_prompts.py`
- **Notes.** OpenRouter, `OPENROUTER_API_KEY`; two targets only (D20). Strict JSON out, including the
  **verbatim quote**; code checks the quote is a substring of the source text and re-parses the value
  **from the quote**; mismatch or regex/LLM disagreement → fact unknown. temperature 0, fixed seed,
  in-run cache keyed by `sha256(text + prompt_version)`, thread pool, timeout + bounded retries,
  any failure → unknown, never crash, never clear on an LLM-only fact that regex contradicts.
  Compare two cheap models on the practice labels; record model, prompt, time and cost in the README.
- **Acceptance.** Score with and without the key: unsafe clears 0 in both, cost not worse with the LLM;
  with no key and with a forced API failure the run completes with identical format.
- **Risks.** Non-determinism → the cache plus temperature 0 plus the quote check; step 11 proves it.

### Step 11 — Determinism, timing, cost
- **Goal.** Byte-identical decisions across 5 runs; comfortable headroom under 30 min.
- **Files.** `tools/repeat.py`
- **Acceptance.** 5 runs on dev → identical `(hit_id, decision, reason_code)` triples (diff empty);
  wall-clock and LLM cost recorded for 819 hits and extrapolated to 550.
- **Risks.** Set/dict iteration order — sort everywhere (§9); `tools/repeat.py` is the proof.

### Step 12 — Safety review of clears
- **Goal.** Convince ourselves the 60-cost error is not happening on unlabelled data.
- **Files.** `tools/review_clears.py`, notes in `plan.md`
- **Notes.** Sample ≥ 30 `DIFFERENT_ENTITY` hits across **all** codes on unlabelled dev hits; read the
  fact sheets by hand; any clear resting on a fact that could be wrong → tighten the rule, not the case.
- **Acceptance.** Every sampled clear traced to a POLICY sentence and present facts; findings written here.

### Step 13 — README and final output
- **Goal.** Deliverables complete.
- **Files.** `system/README.md`, `output/dev.jsonl`, `plan.md`
- **Notes.** Architecture diagram, resolution on both sides, the evidence model, determinism, the LLM's
  two jobs with model/prompt/time/cost, how to run with and without a key, the open assumption from §2,
  and three worked cases (a mismatch, a match, a review).
- **Acceptance.** Fresh clone + `system/run dev out.jsonl` works with no network and no key; format check passes.

---

## 6. Traps checklist

- [ ] `Onboarding` joined on **both** `account_id` **and** `customer_id` — never `account_id` alone (52 joint accounts).
- [ ] `login_handle` resolves **through `Accounts`**, not `Customers.login_name` (which is empty in all 72 265 rows).
- [ ] `rejected` and `expired` KYC checks are **not evidence** (2 481 + 2 433 rows).
- [ ] A shared **phone alone never merges** records — 164 shared phones, only 116 pairs also share a full DOB.
- [ ] A shared **address alone never merges**.
- [ ] Search results are **mostly namesakes** — 60 % carry no listing phrase; anchor on phrase **and** country.
- [ ] `DOB_MISMATCH` needs **every** hit birth date contradicted; one agreeing date blocks it.
- [ ] A country difference **does not clear** a hit whose name **and** DOB agree → `REVIEW`.
- [ ] `NAME_LOCATION_MATCH` is **companies only**.
- [ ] An **unknown fact is never a mismatch** — missing month/day, missing country, missing DOB all stay unknown.
- [ ] **Never read another customer's records** — facts come only from the resolved person's own records.
- [ ] `NAME_MISMATCH_VERIFIED` requires a **verified** legal name (approved check or an approved check written up in a note); a declared name never clears.
- [ ] Individuals with **< 2 real name parts** (placeholders) can be neither confirmed nor cleared on name.
- [ ] `International` and `Europe` are **not countries**; territories are their **own** country.
- [ ] Dated reports are **only** `According to …; <Month D, YYYY>: …` — `June 2014` and `SAM:` lines do not count.
- [ ] `DECEASED` needs an actual **date** of death; `life_status = Deceased` alone cannot clear.
- [ ] Hit IDs are **never** evidence; evidence is bank records and `SR-…` ids only.
- [ ] No dev ids, names or phrasings hard-coded anywhere outside `tests/`.
- [ ] `dev/`, `.env` and caches stay out of commits; the data room is never added to the repo.

# Same Person or Not?

For every screening hit, the system decides `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`, based on
identity alone, as `POLICY.md` sets out. Each decision comes with one reason code, the resolved
customer record, the records it relied on, and a reason of two to four sentences.

```
system/run <data_folder> <output_file> [--no-llm] [--quiet]
```

On the development folder (819 hits): practice cost **0**, **0 unsafe clears**, and `reason_code`,
`customer_record_id` and `evidence` match the label exactly on **50/50**. A run takes **10–20 s**,
five runs are byte-identical, and the output does not change when every table's rows are shuffled.
It uses only the Python standard library.

---

## Running it

```sh
# Regex only: no key, no network, no dependencies (Python 3.8+)
./system/run dev output/dev.jsonl

# With the optional language-model fallback
OPENROUTER_API_KEY=sk-or-... ./system/run dev output/dev.jsonl

# Force regex only, even with a key set
./system/run dev output/dev.jsonl --no-llm
```

- The command runs from any working directory and creates the output directory if it is missing.
- It reads nothing outside `<data_folder>` and writes nothing except `<output_file>`.
- A summary goes to stdout; `--quiet` turns it off.
- Exit codes: `0` on success, `2` with a one-line message if the folder cannot be read.
- If the key is missing, the model module fails to load, or the API times out or refuses, the run
  continues with regex only. On the development folder the key makes no difference at all: a run
  with the key makes **0 calls** and its output is byte-identical to `--no-llm`.

Development tools, none of which the graded run needs:

| | |
|---|---|
| `python3 tools/score.py out.jsonl --data dev` | format check, cost against the practice labels, unsafe clears, field-by-field agreement |
| `python3 tools/explain.py H-XXXXXX` | both fact sheets, every record and what was read from it, which rules fire, the verdict, the label |
| `python3 tools/audit.py dev` | recomputes every count in `plan.md` §3, so a format change shows up as a changed number |
| `python3 tools/ablate.py` | turns off one extractor at a time and lists every decision that moves into a clear |
| `python3 tools/repeat.py [--shuffle]` | five identical runs; `--shuffle` reorders every table's rows first |
| `python3 tools/review_clears.py` | audits all 462 clears and flags structural weaknesses |
| `python3 tools/llm_eval.py` | compares models on reworded text that the regex layer cannot read |
| `python3 -m unittest discover -s tests` | the test suite; needs no key and no network |

---

## Architecture

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

The pipeline has three stages, and only the third makes a decision. Everything it decides from is a
`Fact(value, source_ids)` (`facts.py`), so a decision's evidence is the union of the source ids on
the facts its rule used. There is no separate evidence logic that could drift out of step with it.

| module | job |
|---|---|
| `loader.py`, `model.py` | Finds each table by filename, then by the fields its records carry. Accepts lists or `"; "`-joined strings, `null` or `""`, and the alert's nested `customer` object. Builds the indexes. |
| `norm.py`, `names.py`, `name_variants.py` | Principle 8: name parts, placeholders, legal forms, variant groups, joined or split parts, edit distance set by the shorter part, and best matching over parts. |
| `dates.py` | Seven date formats plus ordinals and spelled-out days. A partial date compares only the parts both sides give. |
| `countries.py` | ISO codes, names and demonyms mapped to one key. Territories stay separate. `International` and `Europe` are dropped. |
| `resolve.py`, `persons.py`, `kyc.py` | Alert → customer records → persons. |
| `customer_facts.py`, `notes_regex.py` | The verified customer picture. |
| `hit_facts.py`, `search_anchor.py` | The hit picture. |
| `rules.py`, `reasons.py`, `decide.py` | Principles 6–7 and 9, plus the multi-person rule from principle 3. |
| `llm.py` | The optional fallback reader (see below). |
| `cli.py`, `run` | The entry point. |

### Resolving the customer (principles 2–4)

- **Link first.** `account_ref` → `Accounts`, which can give two customer ids for a joint account.
  `login_handle` → `Accounts` (not `Customers.login_name`, which is empty). `email` → `Customers`.
  If a link reaches exactly one record, that record is taken. If it reaches several, the screened
  details choose between them. In dev, name and date of birth separate all 58 joint-holder alerts.
- **No link:** a search on the screened details. A blocking index on name parts and their variant
  siblings finds candidates. Each candidate is then tested on name agreement, date of birth agreeing
  in every part both sides give, the screened country as nationality *or* residence, and the screened
  city in city *or* address. A detail the alert does not screen on is `None` and cannot rule a
  record in or out.
- **Person merging.** Two records are one person if they share a phone **and** a full date of birth,
  or if their approved checks share a document number. Union-find makes this transitive. A shared
  phone alone never merges (in dev, 88 shared-phone pairs are family members), and neither does a
  shared address.
- **Several people fit.** Each person is decided separately. If they all reach the same decision, it
  is given with its own code. Otherwise the result is `REVIEW` / `AMBIGUOUS_CUSTOMER_RECORD`. In both
  cases `customer_record_id` is `"AMBIGUOUS"`.
- **One person:** `customer_record_id` is the lowest record id of that person, so it does not depend
  on file order. **No person:** `null` and `REVIEW`. The screened details only locate a customer;
  they never clear a hit.
- **Verified picture.** The chain is customer → accounts → onboarding, joined on **both**
  `account_id` and `customer_id` because a joint account has two holders → applicant → checks. Only
  `approved` checks count. KYC results written up in `channel="kyc"` notes are merged with provider
  checks, and the most recent approved one wins. A field the newest check leaves out comes from the
  newest approved check that does state it.
- **Countries** are the residence and nationality on every record of the person, the approved
  document country, and any country a support note says they lived or worked in. Notes are reached
  only through the emails on the person's own records, never another customer's.

### Gathering the hit (principle 5)

- **Names:** `name`, `best_matching_name`, the joined `first/middle/last`, and `aliases`. More
  candidate names make agreement easier, which makes a name-based clear harder. That is the safe
  direction.
- **Countries:** `countries`, `nationality`, `citizenship`, the last part of each address with its
  `[tag]` removed, and the last part of `place_of_birth`. An address or birthplace whose last part
  is not a recognised country gives no country (guard D below).
- **Date of birth, in priority order:**
  1. The `dobs` field.
  2. A birth or age sentence in the first paragraph of the profile notes. There are 13 age wordings,
     each with a number pattern that rejects digits inside a longer number. A provider's
     `According to …` paragraph never supplies a date of birth.
  3. Anchored search results. A result counts only if it contains the listing phrase for the hit's
     category **and** one of the hit's countries. Its single age and single `Month YYYY` give two
     possible birth years, and its `SR-…` id becomes evidence.

  Companies take only the field.
- **Earliest dated report:** only lines of the strict form `According to …; <Month D, YYYY>: …`.
- **Date of death:** only `deceased_date`. `life_status = Deceased` without a date cannot clear.

### Deciding (principles 6–7, 9)

`rules.py` is a pure function from two fact sheets to a verdict.

1. **Contradictions**, in this fixed order: `ENTITY_TYPE_MISMATCH` → `DECEASED` →
   `TEMPORAL_IMPOSSIBILITY` (under 16 at the earliest dated report) → `DOB_MISMATCH` (**every** hit
   date more than a year from **every** customer date, and verified beats declared) →
   `LOCATION_MISMATCH` (no country shared) → `NAME_MISMATCH_VERIFIED` (a *verified* legal name only,
   never a declared one).
2. **The location exception.** If `LOCATION_MISMATCH` is the only contradiction and both name and
   date of birth agree, the result is `REVIEW`.
3. **Agreement:** `NAME_DOB_LOCATION_MATCH` → `NAME_DOB_MATCH` → `NAME_LOCATION_MATCH`, and the
   last of these applies to companies only.
4. **Otherwise** `REVIEW` / `INSUFFICIENT_DATA`. Any exception inside a hit also becomes
   `REVIEW` / `INSUFFICIENT_DATA`. A crash never becomes a clear, and it never stops the run.

**Unknown is never a mismatch.** A missing month, day, country or date of birth stays unknown. On
top of that rule, four guards come from POLICY's own wording. Every contradiction is stated over
*every* fact of its kind, so a fact the system failed to read makes the set unknown, not smaller:

| guard | when it applies | what it blocks |
|---|---|---|
| A | A support note talks about residence, but no country could be read from it | `LOCATION_MISMATCH` |
| B | There is no verified date of birth, yet an approved check or an unreadable KYC note is on file | `DOB_MISMATCH` |
| C | The hit's first paragraph talks about a birth or an age, but no date could be read | `LOCATION_MISMATCH` (when the name agrees) |
| D | An address or birthplace ends in something that is not a country | that string being used as a country |

`tools/ablate.py` shows why the guards matter. Without them, a failed extractor turns up to 51 hits
into clears, two of them practice labels whose truth is `SAME_ENTITY`. With them, all five ablations
produce **0** new clears, and the guards cost nothing on dev.

### Evidence and reasons

- **Evidence** is `sorted(union(source_ids))` over the facts the reported code used.
  - When a country agrees, only the sources of the *matching* country are cited.
  - A rule that uses only hit facts (`DECEASED`, `ENTITY_TYPE_MISMATCH`) cites the person's own
    records.
  - Hit ids are never cited, because the hit is the subject of the decision. Search results are
    cited by their `SR-…` ids.
- **Reasons** are templates filled from the same facts, with record ids inline. Several match the
  reference reasons word for word. A clear with one contradiction ends with a sentence on what else
  was compared, so every reason has two to four sentences.

### Determinism

- The pipeline has no randomness, and nothing in it depends on dict or row order.
- Output follows the order of the hits file.
- Every tie-break, such as the lowest record id or the fixed code order, is explicit.
- `tools/repeat.py` gives five byte-identical runs. With `--shuffle`, every table's rows are
  reordered, and every one of the 819 hits still decides the same way, reason and evidence included.
- The test suite checks this whole-pipeline property and three narrower ones.

---

## The language model: a fallback that can block a clear but never make one

Patterns read all the free text in dev, so the model has nothing to do there. It exists for the
unseen set, where text may be worded differently. It has exactly **three jobs**, and it is asked
only when the pattern found nothing *and* the text plausibly holds the fact:

1. a birth or age sentence in the first paragraph of a hit's profile;
2. the places lived, from a customer's support note;
3. an identity check written up in a `kyc` note (name, date of birth, document country, result).

- **Grounding.** Every answer must quote the verbatim span it came from. `llm.py` checks that the
  span appears in the source character for character, and that the span really states the claimed
  value. Numbers are matched as whole numbers, so `"3"` does not match inside `"1939"`, and a country
  the model reads must be one the system knows. Anything that fails these checks stays unknown.
- **Provisional facts (D28).** A fact the model recovers is marked provisional. It counts toward the
  set a contradiction is evaluated over, so it can **block** a clear. A rule never fires *on* it, so
  it can never **carry** one. That keeps the model's variability away from the decision where a
  mistake costs 60.
- **Model:** `openai/gpt-4o-mini` over OpenRouter. Override it with `OPENROUTER_MODEL`. The key is
  read from `OPENROUTER_API_KEY` only; `system/` never reads a file for it.
- **Call settings:** `temperature 0`, `top_p 1`, `seed 7`, `response_format: json_object`, a 20 s
  timeout and one retry. Answers are cached for the run, keyed on
  `sha256(prompt version + model + prompt + text)`.
- **How the model was chosen.** `tools/llm_eval.py` ran 18 reworded texts:

  | model | correct | same answers on a second pass |
  |---|---|---|
  | `openai/gpt-4o-mini` | 18/18 | yes |
  | `openai/gpt-oss-20b` | 16/18 | no |
  | `mistralai/mistral-nemo` | 14/18 | yes |

- **Time and cost.**
  - **$0.00** on dev, because no calls are made.
  - About **$0.057 per 1 000 texts** sent. Even if every hit and note in a 550-hit set were
    unreadable, the run would cost about $0.06.
  - The 18-text evaluation took 46 s. A regex-only run is about 14 ms per hit, so 550 hits take
    about 8 s against a 30-minute budget.

---

## Assumptions

These are the points where `POLICY.md` leaves room for interpretation. Each choice below favours
`REVIEW`, which costs 3, over a wrong clear, which costs 60. The full reasoning is in `plan.md` §4.

- **Format of the unseen set.** The system assumes the unseen folder has the same tables as `dev/`,
  though not necessarily the same filenames or encodings. Tables are found by filename and then by
  field signature, and every field accepts more than one encoding. `tools/audit.py` makes a changed
  format visible. If a whole table has a shape the loader does not recognise, the run stops with
  exit code 2 instead of guessing.
- **Screening date** is `Alerts.screened_at` (D4).
- **An "expired" check** is one whose `result` field says so. Rejected and expired checks are never
  evidence (D5).
- **No customer found:** never a clear (D6).
- **No approved check.** Declared dates of birth and countries may still clear. A name clear needs a
  verified legal name (D7).
- **The `customer_record_id` and evidence rules** follow D8–D10.
- **A dated report** must use the colon form exactly. Lines that put a `;` after the date are
  ignored. Ignoring a report can only make a temporal clear less likely (D22).

---

## Three worked cases

All three are practice labels. In each one, the system's output matches the label on decision,
code, record and evidence.

### A clear: `H-2808BE` → `DIFFERENT_ENTITY` / `NAME_MISMATCH_VERIFIED`

1. The alert screens `"RIDWAN AZEEZ"` with `login_handle = ridwana121`. That handle leads to
   `ACC-CE0462` and then to the single customer `CUS-149132`, whose record says `"Ridwan Azeez"`,
   born 2005-09-12, Nigeria.
2. The hit is `"Ridwan, Azeez"` in Nigeria, with no date of birth. On the record alone, the name
   agrees.
3. Following onboarding `APP-95EA5C` to the most recent approved check, `KYC-20EE17`, gives the
   verified legal name `"CHINEDU AZEEZ"`. Only `azeez` matches, and principle 8 needs at least two
   matching parts or every part of the shorter name, so the names do not agree.
4. Principle 6 says the verified name clears the hit "even if the name on their record does" agree.
   No earlier rule fires: the country is shared and there is no hit date to compare.
5. The evidence is **`KYC-20EE17` alone**. That check supplied the deciding fact, so the customer
   record is not cited.

> The customer's verified name is CHINEDU AZEEZ (KYC-20EE17), which does not match the hit's name
> Ridwan, Azeez. The name on the customer's own record does agree with the hit's, but the verified
> legal name outranks it.

### A match: `H-0181BD` → `SAME_ENTITY` / `NAME_DOB_LOCATION_MATCH`

1. The alert's `account_ref ACC-FB5DD0` is a joint account (`CUS-775419` and `CUS-717798`). The
   screened name and date of birth (1985-09-12) fit `CUS-775419`.
2. `CUS-775419` shares a phone and a full date of birth with `CUS-138588`, so the two records are one
   person. `customer_record_id` is the lower id, `CUS-138588`.
3. A `kyc` note, `NOTE-CB2CB8`, records an approved national ID check giving a verified date of
   birth of 1985-09-12. The note's date is written `12/09/1985`, which is read day-first.
4. The hit has no `dobs` and no birth sentence. Search result `SR-590704` contains the hit's listing
   phrase `"a politically exposed person"` and its country, Brazil, so it anchors. Its age and date
   put the birth year at 1985 or 1986.
5. Name, date of birth and country (Brazil, from both records and the note) all agree.
6. The evidence is `CUS-138588, CUS-775419, NOTE-CB2CB8, SR-590704`: the records that supplied
   Brazil, the verified date, and the search result.

> The customer's date of birth 1985-09-12 (NOTE-CB2CB8) agrees with the hit's 1985 or 1986. Both the
> customer and the hit are linked to Brazil. The customer's name agrees with the hit's name COSTA,
> MARCOS ROBERTO.

### A review: `H-FF3096` → `REVIEW` / `INSUFFICIENT_DATA`

1. The alert's email leads to `CUS-459031`, `"Abdul Rahman YASIN"`, born 1965-05-19. Their record and
   their approved note-recorded passport check (`NOTE-588201`) both say **Australia**.
2. The hit is a sanctioned individual in the **United States**, with no date of birth in any form.
3. On the record and passport alone this would be a `LOCATION_MISMATCH` clear. But a support note,
   `NOTE-10AEAB`, says the customer "reported living and working in the United States between 2013
   and 2023", so the countries are shared.
4. The name agrees, and the date of birth cannot be compared. Nothing contradicts the hit and nothing
   confirms it, so the result is `REVIEW`.
5. The evidence is **`NOTE-10AEAB` alone**, because that note supplied the matching country.
6. This is the case guard A protects. If that note were worded so that no country could be read from
   it, the system would refuse to clear the hit, not clear it.

> Both the customer and the hit are linked to United States. The customer's name agrees with the
> hit's name Abdul Rahman Yasin. Nothing in the customer's records contradicts the hit, and the date
> of birth cannot be compared with it, so the hit can be neither cleared nor confirmed.

---

## Results on the development folder

| | |
|---|---|
| format check | ok: 819 lines, every code belongs to its decision, every evidence id is a real record |
| practice cost | **0** across 50 labels |
| unsafe clears | **0** |
| `reason_code` accepted | 50/50 |
| `customer_record_id` accepted | 50/50 |
| `evidence` exactly equal | 50/50 |
| decisions | DIFFERENT 462 (56.4 %) · REVIEW 234 (28.6 %) · SAME 123 (15.0 %) |
| codes | LOCATION_MISMATCH 254, INSUFFICIENT_DATA 219, DOB_MISMATCH 92, NAME_MISMATCH_VERIFIED 89, NAME_DOB_LOCATION_MATCH 80, NAME_LOCATION_MATCH 39, TEMPORAL_IMPOSSIBILITY 22, AMBIGUOUS_CUSTOMER_RECORD 15, DECEASED 4, NAME_DOB_MATCH 4, ENTITY_TYPE_MISMATCH 1 |

Every code in POLICY's table is used, including the three that the practice labels never show.
`output/dev.jsonl` is the committed output of `./system/run dev output/dev.jsonl`. The test suite
checks that a fresh run reproduces it byte for byte.

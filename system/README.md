# Same Person or Not? — the system

For every screening hit the system decides `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`, gives one
reason code, the customer record it resolved, a two-to-four-sentence reason and the IDs of the records
that decided it. It applies the bank's identity SOP (`POLICY.md`) as deterministic rules in plain
Python 3 (standard library only). An optional language model, used only through OpenRouter, can read
free text the patterns miss, but a fact it reads can only *block* a clear, never cause one.

```bash
system/run <data folder> <output file>        # e.g. system/run dev output/dev.jsonl
```

It reads only the data folder and writes one JSON line per hit, in hit order.

| Development set (440 alerts, 819 hits, 72k customer records) | |
|---|---|
| Decisions | 465 `DIFFERENT_ENTITY`, 124 `SAME_ENTITY`, 230 `REVIEW` |
| Practice labels | cost 0, **0 unsafe clears**, reason code 50/50, evidence exact 50/50 |
| Same output every run | identical over repeated runs **and** with every table's rows reordered (`tools/repeat.py --shuffle`) |
| Time per run | about 12 s for 819 hits on a laptop (about 8 s for the unseen set's 550; the brief allows 30 min) |
| Cost per run | $0 on dev: the model has nothing to read there (0 calls). At most about $0.06 per 1,000 unread texts |

## Architecture

```
 alerts ─┐
accounts │  1. resolve the customer          customer fact sheet
onboard. ├─► every link field → records  ─► verified name, DOBs,   ─┐
kyc      │    or a search on the screened    countries (records,    │
customers│    details → merge records into   documents, notes),     │
notes   ─┘    people (union-find)            each with source IDs   ├─► 3. rules ─► decision
                                                                    │   contradictions → clear
 hits ───┐  2. gather the hit's facts        hit fact sheet         │   agreement → confirm
search ──┴─► fields, first paragraph,     ─► names, DOBs, countries,┘   otherwise → REVIEW
             anchored search results,        death, earliest report      + code, evidence, reason
             dated reports
```

| Module | Role |
|---|---|
| `loader.py`, `model.py` | Read the JSONL files, recognised by their columns, not their names; list or `;`-joined values both accepted |
| `norm.py`, `names.py`, `name_variants.py` | SOP principle 8: folding, initials, placeholders, legal forms, variants, written together/apart, edit distance |
| `countries.py`, `dates.py` | Country keys (names, ISO-2/3 codes, demonyms, territories) and partial dates |
| `resolve.py`, `persons.py` | Principles 2–3: links, search, joint holders, merging records into people, ambiguity |
| `customer_facts.py`, `notes_regex.py`, `kyc.py` | Principle 4: verified identity, declared facts, places lived |
| `hit_facts.py`, `search_anchor.py` | Principle 5: the hit's DOBs, countries, death, earliest dated report |
| `rules.py`, `decide.py`, `reasons.py` | Principles 6–9: contradictions, agreement, evidence and reasons |
| `llm.py` | Optional OpenRouter fallback for free text the patterns miss (block-only, grounded) |
| `cli.py`, `run` | The entry point |

## Finding the customer (SOP 2–4)

1. **Follow every link.** `account_ref` and `login_handle` lead through accounts to customer records
   (52 accounts have joint holders), and `email` leads straight to customers. If an alert carries more
   than one link, all of them are followed. The screened name, date of birth, country and city then
   pick between the records.
2. **No link: search.** A blocking index on name parts and their variants finds candidates across all
   72k records. A record fits when one of its names agrees with the screened name, its date of birth
   equals the screened one in every part both give, and the screened country and city match it.
3. **One person, one picture.** Union-find joins records sharing a phone **and** the full date of birth,
   or a document number on an approved check. A shared phone or address alone never merges records.
4. **Verified beats declared.** The latest approved check, from the provider or recorded in an
   onboarding note, gives the legal name, date of birth and document country. Rejected and expired
   checks are ignored. The customer's countries are residence and nationality on every record, every
   approved document country, and every country a support note says they lived in.
5. If several people fit, each is decided. If they agree, that decision stands with
   `customer_record_id = "AMBIGUOUS"`. If they disagree, the hit is `REVIEW` / `AMBIGUOUS_CUSTOMER_RECORD`.

## Finding the listed person (SOP 5)

- **Dates of birth.** These come from the `dobs` field **and** the first paragraph of the profile notes:
  "born on …", a labelled "DOB: …", or an age at a date (aged 45 in March 2019 gives 1973 or 1974). If
  neither gives one, search results are used, but only results that carry the hit's listing phrase and a
  country tied to the hit, because most results are about namesakes. For companies, only `dobs` counts.
- **Earliest dated report.** Only lines of the form `According to …; Month D, YYYY:` count.
- **Countries.** These come from `countries`, `nationality`, `citizenship`, every address and
  `place_of_birth`. A territory is its own country ("Hong Kong, China" means Hong Kong). "International"
  and "Europe" are not countries.

## Deciding (SOP 6–8)

A hit is **cleared only on a contradiction**: person vs company, death before screening, under 16 at
the earliest report (using the oldest the customer could have been), every hit DOB contradicted, the
verified legal name agreeing with none of the hit's names, or no shared country. A country difference
never clears a hit whose name and date of birth agree; that hit is `REVIEW`. It is **confirmed only on
agreement**: a person on name and DOB, a company on name and country. Everything else is `REVIEW`.

### Unknown is never a mismatch (fail closed)

Every clearing rule needs every fact of its kind, so a fact we could not read makes the set unknown,
not smaller:

- A **place the table does not recognise** (for example "Ikeja, Lagos State") is kept as an
  *unrecognised* country. It can agree with the same text on the other side, but `LOCATION_MISMATCH`
  never fires while either side holds one.
- A **support note about where the customer lived** that names no place we recognise blocks
  `LOCATION_MISMATCH`.
- An **identity check we could not read a date of birth from** blocks `DOB_MISMATCH` on a declared date.
- A **first paragraph that talks about a birth we could not read** blocks `LOCATION_MISMATCH` when the
  names agree (the SOP's location exception might apply).
- An **entity type other than person or company** (for example Vessel or Unknown) cannot fire
  `ENTITY_TYPE_MISMATCH`. A hit whose name is only a legal form ("S.R.L.") cannot be cleared on name.
- Age reading accepts only explicit age phrasings. Quantities ("reached 50 million"), ordinals
  ("3rd") and sentence lengths ("sentenced to 28 years") are never read as ages, and a first
  paragraph opening "According to" is the provider's own narrative, not a statement of age.
- A fact the **language model** read is *provisional*: it counts in the set a contradiction
  quantifies over, so it can stop a clear, but no rule fires on it.

`tools/ablate.py` switches each extractor off in turn and checks that no decision moves into
`DIFFERENT_ENTITY`. `tools/review_clears.py` prints a sample of clears on unlabelled hits for a person
to read.

## How evidence is represented

Every fact carries the IDs of the records it came from. A decision cites only the sources of the facts
that decided it: a clear cites the contradicting facts, a confirmation cites the agreeing DOB and
country sources, and a review cites what did agree. Hit IDs are never evidence. The reason is written
from the same facts, so the reason and the evidence always match.

## Keeping runs identical

Without a key there is no model, randomness, network or clock: "now" is the alert's `screened_at`.
Inputs are sorted before use, and the reported `customer_record_id` is the lowest of the person's record
IDs, so nothing depends on file order. `tools/repeat.py --runs 5 --shuffle` runs the system repeatedly
and on a copy with every table reordered, and checks every hit decides the same way. With a key, the
model runs at temperature 0 with a fixed seed and an in-run cache, and because its facts can only block
a clear, a wobble can move a hit between `REVIEW` and a confirmation at most, never into a clear.

## Model and prompts

Optional, and **`openai/gpt-4o-mini` through OpenRouter** (`OPENROUTER_API_KEY`; `--no-llm` turns it
off). It has three jobs, each asked only when the pattern found nothing and the text plausibly holds
the fact: a hit's first-paragraph birth sentence, a support note's places lived, and an identity check
written up in a note. Every answer must quote the verbatim span it read, and the code checks that the
span is in the source and states the value. Settings: temperature 0, top_p 1, seed 7, JSON response
format, a 20 s timeout and one retry. Any failure leaves the fact unknown.

On 18 reworded test texts (`tools/llm_eval.py`) gpt-4o-mini was right on 18/18 and identical on a
second pass; gpt-oss-20b was 16/18 and unstable, and mistral-nemo 14/18. On the development set the model
makes **0 calls**: every note and profile there is read by a pattern, and output with a key is
byte-identical to `--no-llm`.

## Three cases

**Clear mismatch: H-13E1CF → `DIFFERENT_ENTITY` / `TEMPORAL_IMPOSSIBILITY`.** Account `ACC-B3E19A`
leads to `CUS-364225`, which shares its phone and full date of birth with `CUS-851234`, so they are one
person. Approved check `KYC-358C76` verifies a birth date of 2007-08-21. The hit's earliest dated report
is "According to …; January 08, 2020:", when the customer was at most 12, under the SOP's 16. Evidence:
`CUS-364225`, `CUS-851234`, `KYC-358C76`.

**Match: H-582410 → `SAME_ENTITY` / `NAME_DOB_LOCATION_MATCH`.** Account `ACC-C4CA34` has two holders,
and the screened DOB picks `CUS-377745`. Onboarding note `NOTE-14E25A` records an approved check: 1968-03-05,
Spain. The hit's first paragraph says Elvira Velasco Morillo was 30 in November 1998, which gives 1967
or 1968. Name, birth year and Spain agree, and nothing contradicts them. Evidence: `CUS-377745`, `NOTE-14E25A`.

**Left for review: H-FA9F83 → `REVIEW` / `INSUFFICIENT_DATA`.** Account `ACC-08D260` leads to
`CUS-783545`. Check `KYC-80B445` verifies DIANA CIRSTIAN, Moldova. "Cirstian" and "Cristian" are two
edits apart, which is allowed for an 8-letter part, so the names agree, and both are linked to Moldova.
The hit gives no date of birth in its field, profile or matching search results, so it can be neither
cleared nor confirmed. The reason says that the missing fact is the hit's date of birth.

## What it does not do

- It cannot detect forged identity documents: verified data is trusted as verified.
- Free text worded in a way the patterns do not recognise yields no fact, so the hit leans to `REVIEW`
  rather than to a clear.
- A country spelling the table does not know blocks location clears for that hit. Unrecognised places
  should be added to `countries.py` as they appear.

## Other commands

```bash
python3 tools/score.py output/dev.jsonl --data dev --score dev/practice_labels.jsonl   # format + practice score
python3 tools/repeat.py --data dev --runs 5 --shuffle                                   # determinism + reordered input
python3 tools/review_clears.py output/dev.jsonl --data dev                              # read sample clears
python3 tools/explain.py H-582410 --data dev                                             # one hit's fact sheets
python3 tools/llm_eval.py                                                                # model on reworded texts (needs a key)
python3 -m pytest tests                                                                  # 469 tests, no key or network needed
```

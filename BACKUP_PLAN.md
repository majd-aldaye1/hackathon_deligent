# Backup plan: branch `backup` (built on dev step 11)

**What this is.** A backup copy of `dev` at its most recent completed step, **step 11** (`e3dfe29`,
"Step 11: reproducibility, including under a reordered input"), with the plan's last two steps done
and the code-review fixes applied. **It is never merged.** Use it only if the main effort can't be
finished in time. Then you submit *from* it (section 3), without merging it into anything.

---

## 1. Status at a glance

| Step (plan.md §5) | Status on this branch |
|---|---|
| 1–9 loader → guards | done on `dev`, unchanged here apart from the fixes in §2 |
| 10 LLM fallback | done on `dev` (block-only, grounded, gpt-4o-mini via OpenRouter, 0 calls on dev), unchanged |
| 11 Determinism, timing | done on `dev` (`tools/repeat.py --shuffle`), unchanged; re-run here: identical over 3 runs and with every table reordered |
| **12 Safety review of clears** | **done here.** `tools/review_clears.py` prints a sample of clears per code on unlabelled hits; a sample of every code was read, and each rests on a fact that is really there |
| **13 README + final output** | **done here.** `system/README.md` (architecture, both-side resolution, evidence, determinism, model and prompts, time and cost, three worked cases, limits); `output/dev.jsonl` regenerated |

Verification on this branch: **469 tests pass** (no key or network needed); practice labels cost **0**,
**0 unsafe clears**, reason code 50/50, evidence exact 50/50; output format ok; 819 lines; identical
output across runs and under a reordered input.

---

## 2. Review fixes applied, and why

All are "fail closed" fixes: something the system can't read must never become a clear.

| # | Fix | File / function | Why (points at risk) |
|---|---|---|---|
| F1 | Name written apart covers both parts ("Blue Grass" = "Bluegrass") | `names.py` `_covers_shorter` | Principle 8 says a join counts as one part covering both. Without it H-F37DDF was **cleared on name** (possible −60). |
| F2 | A part under 4 letters can't be absorbed into a join by the edit allowance ("ST Logistics" ≠ "Starling Logistics") | `names.py` `_joined_match` | Principle 8: parts under 4 letters must be identical |
| F3 | Equal-length names: "every part of the shorter name" tried both ways | `names.py` `compare_parts` | Makes agreement easier, so a name clear is harder (the safe side) |
| F4 | An unrecognised place becomes an **UNMAPPED** key; `LOCATION_MISMATCH` never fires while either side holds one | `countries.py` `key`, `key_from_place`; `rules.py` `countries_disjoint` | Before, "Ikeja, Lagos State" or "Iran, Islamic Republic of" became a country different from everything, so **a false location clear** (the most common clear: 254 on dev). Step 10 already rejects unknown countries *from the model*; this closes the same gap for structured fields. |
| F5 | Territory beats its parent ("Hong Kong, China" → Hong Kong); official long forms; trailing postcodes skipped; ~45 small states and territories added | `countries.py` | Fewer unrecognised places, so fewer blocked clears; Hong Kong vs China was a false mismatch |
| F6 | Hit DOBs = `dobs` field **plus** first-paragraph births ("every birth date the hit gives") | `hit_facts.py` `gather` | One agreeing date must block a DOB clear. (Step 10's "According to … is provider narrative" rule still applies, so the "Age: 55" record dump in H-4A2E8B is not read; see §4.) |
| F7 | Ages: added "X was 27.", "was 27 at the time", ", at 24,"; removed bare "reached N"; ordinals never ages | `hit_facts.py` `_AGE_CUES`, `_AGE_NUM` | "reached 50 million" and "was 3rd" invented DOBs, so a possible false DOB clear; the missed phrasings cost 4 correct decisions on dev |
| F8 | Labelled DOB in record-style paragraphs ("DOB: 6/20/1955"); an ambiguous slash date keeps only the year | `hit_facts.py` `_DOB_LABEL`, `_labelled_date` | H-2C6B2E was confirmed although the listed DOB contradicts the customer's month |
| F9 | Entity types other than person or company never fire `ENTITY_TYPE_MISMATCH` | `rules.py` `_kind` | "Vessel" / "Unknown" vs Individual would have cleared |
| F10 | A hit with no real name part ("S.R.L.") can't be cleared on name | `rules.py` `name_mismatch_verified` | An empty name "agrees with none", so a trivially false clear |
| F11 | Every link field on an alert is followed, not just the first | `resolve.py` `_links`, `linked_record_ids` | Conflicting links now go through the ambiguity rule instead of silently trusting one |

Decisions that changed against `dev` step 11 (6 of 819):

| Hit | dev step 11 | This branch | Fix |
|---|---|---|---|
| H-F37DDF | DIFFERENT / NAME_MISMATCH_VERIFIED | SAME / NAME_LOCATION_MATCH | F1 |
| H-2C6B2E | SAME / NAME_DOB_LOCATION_MATCH | DIFFERENT / DOB_MISMATCH | F8 |
| H-84E6E6, H-8C46EF, H-7A7ADF | REVIEW | DIFFERENT / DOB_MISMATCH | F7 |
| H-792AF1 | REVIEW | SAME / NAME_DOB_LOCATION_MATCH | F7 |

Regression tests for every fix: `tests/test_backup_fixes.py`. `dev`'s own `tools/repeat.py` was kept
(the backup's simpler version was dropped).

---

## 3. Fast finish (about 30 minutes) if this branch becomes the submission

Every step leaves a valid submission behind, so stop wherever the deadline falls.

1. **(2 min) Regenerate on the real data room.** `output/dev.jsonl` here was produced from a JSONL copy
   of the CSV export, which on `dev` gives the same output as the real data room. Regenerate anyway:
   `env -u OPENROUTER_API_KEY system/run dev output/dev.jsonl`
2. **(3 min) Check.**
   `python3 tools/score.py output/dev.jsonl --data dev --score dev/practice_labels.jsonl` → cost 0,
   unsafe clears 0. `python3 -m pytest -q tests` → all pass.
   `python3 tools/repeat.py --data dev --runs 2 --shuffle` → identical.
3. **(10 min) Read clears.** `python3 tools/review_clears.py output/dev.jsonl --data dev --per-code 5`.
   If a clear rests on something that might be wrong, tighten the rule, never the single case.
4. **(10 min) Submit from a clean public repo**, because the current repo's history contains the dataset:
   ```bash
   mkdir ../submit && cp -r system output ../submit/ && cp README.md ../submit/ && cd ../submit
   git init && git add . && git commit -m "Same Person or Not? submission"
   # create an empty public repo on GitHub, then:
   git remote add origin <new repo URL> && git push -u origin main
   ```
   Check `../submit` contains **no** `dev/`, `dataset/`, `brief.txt`, `.env` or an API key.
5. **(remaining time) Video and pitch.** Lead with the outcome: *X% of false positives cleared
   automatically, 0 unsafe clearances on the practice labels, every decision cites its records, the
   same answer on every run and on reordered input.* Use the three cases in `system/README.md`.

---

## 4. Open question and optional improvements (only if there is time)

| Item | Effort | Why |
|---|---|---|
| **H-4A2E8B (Villagomez).** Listed DOB 1962-09-10; first paragraph is an FBOP record "According to … as of December 13, 2017: … Age: 55". Customer 1962-06-10. Step 10 treats any "According to …" paragraph as provider narrative, so the age is not read and the hit is cleared on the month. Under the other reading (the age is a birth year the hit gives, so 1962 agrees) it would not be cleared. Ask the Diligent team at office hours / #help. | 5 min | The one remaining clear that depends on a policy reading. The age (55 in Dec 2017) is consistent with the listed Sept 1962, so the clear is probably right. |
| City → country table built from `customers` (city, residence_country) so "moved from Lagos" adds Nigeria | 30 min | Such a note only *blocks* a location clear today (safe), so this recovers points, not safety |
| Do not change the model setup | n/a | The model can only block clears, makes 0 calls on dev, and was the only one tested that was right and stable |

---

## 5. How this differs from the `submission` branch

Both score 50/50 on the practice labels. Where they still differ, this branch follows the SOP's wording:
when name and DOB agree but every country differs it says REVIEW, not SAME ("that hit is REVIEW");
"Starling Logistics" vs "ST Logistics" does not agree on name; and an unlinked alert that several
different people fit with different answers goes to REVIEW / AMBIGUOUS_CUSTOMER_RECORD. It also keeps
`dev`'s guards, the block-only model, the reordered-input check and 469 tests. Neither branch was merged
into the other, and this one must not be merged either.

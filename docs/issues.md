# Data/Pipeline Issues

Findings from a data-health pass over `data/juribench_dataset.csv`, `data/juribench_labeled.csv`,
`data/lawma_validation.csv`, and `code/lawma_label.py`. Each entry: what's wrong, why it might not
matter, evidence.

---

## 0. Student must provide the ingestion/fetch code, not just CSVs — PRIORITY: URGENT

There is **no CourtListener fetch/scraping script anywhere in this repo** (`code/` only has
`lawma_label.py`, `validate_classifier.py`, `dataset_stats.py` — grep + glob repo-wide confirm
nothing else). Whatever produced `data/juribench_dataset.csv` was run somewhere else, off the
record, and never checked in. That means:

- We cannot inspect, review, or reproduce how the raw 726 rows were fetched.
- We cannot diagnose the `opinion_text` gap (issue #3 below) without seeing the actual fetch logic.
- We have no way to verify field mapping (`plain_text` vs `html` vs `html_lawbox` vs `html_columbia`
  vs `xml_harvard` — CourtListener has several possible text fields per opinion, populated
  inconsistently by document source/era).
- A CSV with no code behind it is not reproducible, not auditable, and not acceptable as a data
  artifact for a paper going through peer review.

**Action**: student must hand over the actual fetch/ingestion script(s) used to produce
`juribench_dataset.csv` — not just the output CSV. Get serious about this. If the code doesn't
exist because it was never saved, that itself is a problem that needs to be said out loud, not
quietly worked around. No more CSV-only handoffs.

=== 
Σας επισυνάπτω το ενημερωμένο dataset.
Εμπεριέχει 726 δίκες, εκ των οποίων οι 164 είναι Scotus, οι 264 είναι CA5 και οι 298 είναι CA9 και περιλαμβάνει χρονολογίες από 2010 έως 2024. Η αλήθεια είναι ότι δυσκολεύτηκα με το Scotus να βρω αξιοποιήσημα δεδομένα.
Όσον αφορά την ιδεολογία, για το Scotus την πήρα από το Martin-Quinn, για τα CA5-CA9 την πήρα από το JuDJIS και για όσα έλειπαν (~7,8%) την πήρα μέσω GPT-4o. Πέτυχα συνολική κάλυψη ~98%.
Όσον αφορά το issue_text, issue_area και facts, τα οποία μας ενδιαφέρουν, για το Scotus τα πήρα από την βάση δεδομένων SCBD, ενώ για τα CA5-CA9 άφησα κενό για να συμπληρωθούν από το Lawma model.
===


---

## 1. Lawma classifier accuracy below its own gate — LOW priority / questionable finding

**Priority: LOW / questionable**

`lawma_label.py` validates itself on 37 SCOTUS opinions with known SCDB ground truth: **28/37 = 75.7%
accuracy**. `implementation-details.md` / `implementation-details-issue.md` specify a hard gate —
if accuracy < 85%, fall back to (a) collapsing to top-6 SCDB categories, or (b) human-labeling the
circuit subset. The gate isn't wired into the code (lines 208–234 print the accuracy, then
unconditionally label all 562 CA5/CA9 rows regardless of the result) — so 77% of the dataset's
`issue_area` labels rest on a classifier that failed its own pre-registered threshold.

**Why this might be questionable / not urgent**: 37 validation examples is a small sample —
confidence interval on 75.7% is wide, true accuracy could plausibly be closer to 85%. Also,
`issue_area` is used for topic-stratification/confound-control in evaluation, not as a primary
eval axis (jurisdiction/ideology are) — so noisy labels here degrade the *strength* of the
topic-confound defense, not the headline JAS/JPA results themselves. `results_collapsed.csv` in
this same directory suggests the top-6-category collapse fallback may already have been tried
informally — worth checking before treating this as unresolved.

---

## 2. `judge_id` 0% populated — LOW priority / questionable finding

**Priority: LOW / questionable**

`judge_id` is empty for all 726 rows in both `juribench_dataset.csv` and `juribench_labeled.csv`.
On its face this looks like a broken/dead column.

**Why this is likely fine**: `judge_name` is 100% populated and is what the pipeline actually uses
(author-disjoint split logic, JuDJIS lookup in `code-specs/01.data_ingestion.md` and
`implementation-details.md` §1 both key off name, not a numeric ID). `judge_id` may simply be an
unused/reserved column carried over from the CourtListener API schema (which does have a numeric
judge ID field upstream) that was never populated because the pipeline standardized on name-based
matching instead. Not necessarily a bug — flagging only because an entirely-empty column is worth
a second look before the paper ships (either populate it or drop it from the schema).

---

## 3. `opinion_text` missing for 28% of rows (204/726) — PRIORITY: HIGH

Usable corpus after filtering to rows with `opinion_text` = 726 − 204 = **522** (not a huge shortfall
in absolute terms — lines up close to the pipeline's own "full 500" target in
`code-specs/01.data_ingestion.md`). So the corpus-size hit itself is tolerable *if* the gap is
just re-fetched.

**This is not a data-scarcity problem — it looks like a fetch bug**, based on:
- **100% (204/204)** of the missing-`opinion_text` rows *do* have `syllabus` populated — the
  pipeline reached these exact cases on CourtListener, it just failed to pull one specific field.
- Sample of affected cases includes ***Citizens United v. FEC***, *Amgen Inc. v. Connecticut
  Retirement Plans*, *Kaley v. United States* — some of the most famous, most fully-documented
  SCOTUS opinions in existence, trivially available in full text elsewhere. If these are missing
  text here, the opinions aren't "hard to find" — the fetch step is broken for them.
- Missing rate is uneven by court: **CA5 14%, CA9 29%, SCOTUS 49%**. SCOTUS being worst fits a
  plausible root cause: CourtListener stores opinion text under a separate sub-resource per
  opinion, and SCOTUS clusters routinely have multiple opinions (majority + concurrence + dissent)
  where circuit clusters usually have one. A scraper that only grabs the first sub-opinion, or
  checks only one text field instead of falling back across all of CourtListener's possible text
  fields, would produce exactly this pattern.
- Diagnosis is currently blocked by issue #0 — no fetch script in the repo to inspect directly.

**Action**: not "find more opinions" — **backfill full text for these same 204 already-identified
case IDs** from CourtListener, trying all text-field fallbacks (`plain_text`, `html`,
`html_lawbox`, `html_columbia`, `xml_harvard`) and fetching all sub-opinions per cluster, not just
the first. Should be roughly a day of work once the fetch code (issue #0) is in hand — much
cheaper than sourcing new cases.

---

## 4. Sparse jurisdiction × ideology cells (e.g. CA5×Liberal = 4) — PRIORITY: LOW (known limitation, not a bug)

Reclassified after discussion. CA5 skewing Conservative (few Liberal-labeled judges → CA5×Liberal
cell N=4) reflects real-world 5th Circuit judicial-appointment history, not a data pipeline
defect — there's nothing in the data itself to "fix."

**What's still actionable, but as a stats-reporting discipline, not a data-quality fix**: don't
report a classifier accuracy or build a centroid for any (jurisdiction, ideology) cell with N<10
(CA5×Liberal=4 is the clear offender) without flagging it — `implementation-details.md` §8
pre-registers exactly this risk ("if cell has <10 opinions, stratified JAS won't be statistically
reliable"). Handle via cell-count reporting / exclusion in `11.statistics`, not a data fix.

---

## 5. `ideology_source` includes unauthorized third source `gpt4o_fallback` (44 rows, 6%) — PRIORITY: HIGH

`implementation-details.md` §1 is explicit and exclusionary: only JuDJIS (circuit) and Martin-Quinn
(SCOTUS) are acceptable ideology sources; it even names what's *not* acceptable (party-of-appointing-
president proxy). A GPT-4o fallback for ideology labeling isn't mentioned anywhere in that spec.
Ideology is the **primary eval axis** (JPA) — contaminating any of it with an unvalidated LLM guess
is more serious than the issue_area problem (#1), not less, and there's no accuracy/validation
number for this fallback the way there is for Lawma.

**Checked whether issue #3 rescues this (it doesn't)**: cross-referenced the 44 `gpt4o_fallback`
rows against the 204 missing-`opinion_text` rows — **zero overlap**. All 44 `gpt4o_fallback` rows
have full `opinion_text` and are therefore still in the usable corpus. Of the 522 text-complete
rows: 478 have clean JuDJIS/Martin-Quinn ideology, 44 (8.4% of the usable set) still carry the
unauthorized-source label. The two problems are independent — fixing #3 does not clean up #5.

**Action**: identify which 44 judges fell through to `gpt4o_fallback` (likely JuDJIS/MQ name-match
misses — see `implementation-details.md` edge cases on name normalization) and either fix the name
match, drop these 44 rows from ideology-axis experiments, or explicitly validate the fallback
labels against a small human-checked sample before using them.

---

## 6. Ideology coverage (64.1%) is sufficient for the design; SCOTUS class is the real blocker — PRIORITY: MEDIUM (dependency, not a data gap)

After the enrichment fixes (SCDB date-key bug, opinion-text author parse, dedupe), ideology
coverage on the deduped 2234-row corpus is 1433/2234 (64.1%: SCOTUS 190/307, CA5 827/980,
CA9 416/947). Investigated whether this is "not enough" against the actual experimental design
rather than the raw percentage. **It is not a data-quantity problem**:

- Corpus target is ~500 rows (`code-specs/99.trace_matrix.md` A1.1 = 200/200/100) — 1433 labeled
  rows is ample headroom; the question is sampling, not scarcity.
- **E2** (`code-specs/06.classify.md`) is a *pooled* 2-way {Liberal, Conservative} classification
  (single global 2×2 confusion, not per-court). Pool = 139 Liberal / 296 Conservative → ~65 test
  rows at a 15% split. Clears the acc≥0.72 / macro-F1≥0.70 gates comfortably.
- **E3** (`code-specs/07.orthogonality.md:11-14`) gate `G_E3_quadrants` = ≥4 of 6 (court×ideology)
  cells with ≥3 opinions each, Moderate excluded. The spec was deliberately written to tolerate a
  sparse cell ("≥4 of 6, not 6/6", "or analogous with SCOTUS"). Projection (15% test × ~0.60
  E1∩E2-correct) → 5 of 6 cells clear ≥3 → gate PASSES.

**What actually matters, two separable facts:**

1. **SCOTUS `ideology` class is unset** — all 190 SCOTUS rows are score-only
   (`enrich_ideology.py` deliberately left `ideology` blank; MQ-scale threshold decision was
   deferred, see decision below). This is a **hard dependency**: without a SCOTUS class the E3
   grid drops to 3/6 populated cells = gate **FAILS**. Whoever builds the split/eval stage
   (`01.data_ingestion`, `06.classify`, `07.orthogonality`) must set it first. Setting it is pure
   additive re-binning of MQ scores already stored — no new data needed (~65 Liberal / 125
   Conservative by MQ-sign cut, `data/mqscores/justices.csv` `post_mn`).
2. **CA5×Liberal = 13** (→ ~1 eligible after split+classification) is the one genuinely thin
   cell — a real fact about the Fifth Circuit's conservative bench (cross-ref issue #4 above),
   not an extraction bug. The E3 ≥4/6 design already absorbs it; no fix needed.

**Decision (2026-07-10, explicit)**: keep `ideology_score` continuous for all rows at this stage;
defer *all* class-threshold decisions — both the SCOTUS MQ cut and any re-examination of the
circuit ±0.3 threshold — until the split/eval stage is actually built, so the class definition is
locked once rather than guessed now. Do **not** re-threshold circuits to fatten Lib/Cons cells —
a JuDJIS≈0.1 judge genuinely is moderate; changing the cut to improve cell counts would be
construct distortion / researcher-degrees-of-freedom, not a fix.

**Action**: when building the split/eval stage, set SCOTUS `ideology` class (recommended:
MQ-sign at 0 — confirm this is the conventional Martin-Quinn dichotomization before locking it)
before running E2/E3. Leave the circuit ±0.3 threshold as-is unless an external, cited
justification (not cell-count pressure) says otherwise.

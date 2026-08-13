# Ideology/issue_area enrichment pipeline

Two new scripts, run in order, on `data/juribench_dataset.csv` (2485 rows, raw collector output — no ideology/issue_area yet).

## 1. `code/enrich_authors.py`
Backfills `author_str` + `author_cl_id` from CourtListener sub-opinions (fields the collector fetched but discarded). Resumable — reruns skip rows that already have `author_str`.

```
python code/enrich_authors.py
```
Only needed for CA5/CA9 (feeds JuDJIS match in step 2). **UNVERIFIED**: live spot-check showed CL sub-opinions in this date range often have empty `author_str` (`type=010combined`) — check coverage % after running; may need a fallback (constrain text-parsing to the JuDJIS name roster) if near-zero.

## 2. `code/enrich_ideology.py`
Local joins, no network.

- **SCOTUS**: match row → SCDB (`data/scdb/SCDB_2025_01_caseCentered_Citation.csv`) by case_name+date → `majOpinWriter` → Martin-Quinn (`data/mqscores/justices.csv`) `post_mn` for that justice+term → `ideology_score` (`ideology_source=martin_quinn`). Also pulls SCDB `issueArea`→`issue_area` (`issue_area_source=scdb`) and `decisionDirection`. Ideology **class** (Liberal/Mod/Cons) deferred — MQ scale isn't ±0.3-compatible with JuDJIS; only the continuous score is filled for now.
- **CA5/CA9**: `author_str` → JuDJIS (`.../1. circuit score construction/agjudge_full.csv`) via Jaro-Winkler ≥0.92 → `judjis_score` → ±0.3 threshold → `ideology`/`ideology_score` (`ideology_source=judjis`). No GPT-4o fallback (banned, see `code/issues.md` #5) — unmatched rows stay blank.

```
python code/enrich_ideology.py
```

## 3. `code/lawma_label.py` (existing, already fixed for the crash)
Run after step 2. Labels CA5/CA9 `issue_area` via Lawma-70B. SCOTUS is excluded from labeling (uses SCDB ground truth from step 2) and instead becomes the validation set the script checks Lawma's accuracy against.

```
python code/lawma_label.py
```

## Verify
```
python code/dataset_stats.py
```
Check: `ideology_score` coverage > 0%, `ideology_source` contains only `judjis`/`martin_quinn` (never `gpt4o_fallback`), SCOTUS `issue_area_source == scdb`.

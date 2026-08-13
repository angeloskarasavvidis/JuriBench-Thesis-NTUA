# code/

| File | Status | Role | Usage |
|---|---|---|---|
| `dataset_stats.py` | active | Dataset health stats: coverage, distributions, N<10 cell flags, ideology_source health, Lawma gate check. | `python dataset_stats.py --input data/juribench_labeled.csv` |
| `lawma_label.py` | active | Labels CA5/CA9 `issue_area` via Lawma 70B; validates on SCOTUS (SCDB ground truth). Writes `juribench_labeled.csv` + `lawma_validation.csv`. Does not enforce 85% gate (see `issues.md` #1). | `python lawma_label.py` · `--validate-only` · `--model lawma-8b` |
| `validate_classifier.py` | drop pending | GPT-via-OpenRouter `issue_area` classifier, validated on SCOTUS. Predecessor to `lawma_label.py`. | `python validate_classifier.py --model openai/gpt-4o --sample 100` · `--collapse` for 6-class mode |

## Data flow

```
juribench_dataset.csv → lawma_label.py → juribench_labeled.csv + lawma_validation.csv
juribench_dataset.csv / juribench_labeled.csv → dataset_stats.py → stdout
juribench_dataset.csv → validate_classifier.py → stdout (+ optional CSV)
```

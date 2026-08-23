# JuriBench — Διπλωματική (ΕΜΠ)

**Θέμα:** Προσομοίωση & Ανάλυση Δικαστικού/Δικηγορικού Λόγου μέσω Μεγάλων Γλωσσικών Μοντέλων.
**Επιβλέποντες:** Π. Τσανάκας, Μ. Κόνιαρης.

**Task:** δίνω υπόθεση (`facts` + `issue_text` + δικαστήριο) → το μοντέλο παράγει την απόφαση
(σκεπτικό + έκβαση) → αξιολόγηση παραγόμενου vs αυθεντικού με μετρικές.

## Δομή repo

```
JuriBench-Thesis-NTUA/
├── README.md            ← αυτό το αρχείο (τι είναι, πώς τρέχει)
├── ROADMAP.md           ← συνολικό πλάνο διπλωματικής (στάδια 0–6)
├── RUN.md               ← βήμα-βήμα εκτέλεση σε Colab (smoke → full)
├── CLAUDE.md            ← context/μνήμη για τον AI βοηθό (συνέχεια εργασίας)
├── requirements.txt         ← βιβλιοθήκες pipeline δεδομένων (τοπικά)
├── requirements-train.txt   ← βιβλιοθήκες training/eval (Colab/GPU)
├── .env.example         ← υπόδειγμα κλειδιών (αντίγραψε σε .env, ΔΕΝ ανεβαίνει)
├── code/                ← ΟΛΑ τα εκτελέσιμα scripts (flat)
└── docs/                ← σημειώσεις επιβλέποντα (issues, notes)
```

Τα **δεδομένα** και τα **αποτελέσματα** (`data/`, `adapters/`, `preds/`, `results/`)
ΔΕΝ είναι στο git (μεγάλα/τρίτων) — ζουν στο **Google Drive** (δες «Ροή εργασίας»).

## Τα scripts (`code/`) ανά στάδιο

| Στάδιο | Script | Τι κάνει |
|---|---|---|
| 0 · Συλλογή | `juribench_collect.py` | Κατεβάζει γνωμοδοτήσεις από CourtListener (SCOTUS/CA5/CA9) |
| 0 · Καθαρισμός | `dedupe_case_names.py` | Αφαιρεί διπλότυπα («Revisions:») |
| 0 · Author | `enrich_authors.py` | Βρίσκει τον συγγραφέα δικαστή (circuits) |
| 0 · Ideology/Area | `enrich_ideology.py` | SCOTUS→Martin-Quinn · circuits→JuDJIS · SCDB issueArea. **Ποτέ LLM** |
| 0 · Issue area | `lawma_label.py` | issue_area circuits με Lawma-70B (SCOTUS = validation) |
| 0 · Πεδία task | `enrich_case_fields.py` | Παράγει `facts`, `issue_text`, `disposition` (έκβαση) από το opinion |
| 0 · Health | `dataset_stats.py` | Στατιστικά υγείας dataset |
| 0 · Splits | `make_splits.py` | train/val/test **author-disjoint & court-stratified** (JSONL) |
| 1 · Format | `build_finetune.py` | splits → chat messages (variants: `generation`, `predict`) |
| 2 · Train | `train_qlora.py` | QLoRA fine-tuning (auto bf16/fp16, version-robust TRL) |
| 3 · Generate | `generate.py` | Inference στο test → `preds/*.jsonl` |
| 4 · Eval | `evaluate.py` | Έκβαση (acc/F1) + discourse + BERTScore + citation-hallucination |
| 4 · Eval | `eval_judge.py` | LLM-as-judge ποιότητας λόγου (1–5 ανά άξονα) |
| 4 · Eval | `eval_ideology.py` | Ιδεολογική πιστότητα (E2) — **παρκαρισμένο προς το παρόν** |
| 5 · Σύγκριση | `compare_results.py` | Συγκεντρώνει τα `results/*.json` σε πίνακα |
| — | `llm_client.py` | Κοινός βοηθός κλήσεων LLM (OpenAI-compatible) |

## Κανόνες (μη διαπραγματεύσιμοι)

- **Ιδεολογία labels: ΠΟΤΕ LLM.** Μόνο JuDJIS (circuits) + Martin-Quinn (SCOTUS). Ό,τι δεν
  ματσάρει μένει κενό (δες `docs/issues.md` #5). SCOTUS class = πρόσημο MQ (re-binning, όχι νέα δεδομένα).
- Η ιδεολογία είναι **eval-only** άξονας — δεν μπλοκάρει την εκπαίδευση.
- Input (`facts`/`issue_text`) δεν πρέπει να διαρρέει την έκβαση.

## Ροή εργασίας: GitHub (κώδικας) + Drive (δεδομένα) + Colab (εκτέλεση)

- **Κώδικας:** εδώ στο GitHub. Διορθώσεις έρχονται με `git pull`.
- **Δεδομένα & αποτελέσματα:** στο Google Drive.
- **Εκτέλεση:** Google Colab. Στην αρχή κάθε session, ένα setup-κελί κάνει `git clone`
  του κώδικα και «δένει» (symlink) τα `data/`, `adapters/`, `preds/`, `results/` με το Drive.
  Πλήρεις οδηγίες: **RUN.md**.

## Quickstart (smoke)

Δες **RUN.md** → ενότητα C. Επιβεβαιώνει ότι train → generate → evaluate → compare τρέχει
end-to-end σε λεπτά, με μικρά μοντέλα.

## Κατάσταση

Ολοκληρωμένα: data pipeline (2234 υποθέσεις), splits, format, training, generation,
evaluation (outcome/discourse/judge), σύγκριση — **όλα δοκιμασμένα end-to-end**.
Επόμενα: μεγέθυνση dataset (Στάδιο 6) → full runs στα 3 μοντέλα → ανάλυση → συγγραφή.
Λεπτομέρειες: **ROADMAP.md**.

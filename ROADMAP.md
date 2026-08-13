# ROADMAP — Διπλωματική (JuriBench)

**Θέμα:** Προσομοίωση & Ανάλυση Δικαστικού/Δικηγορικού Λόγου μέσω LLMs.
**Task:** δίνω υπόθεση (facts + issue_text + δικαστήριο) → το μοντέλο παράγει την απόφαση
(σκεπτικό + έκβαση) → αξιολόγηση παραγόμενου vs αυθεντικού με μετρικές.

## Φιλοσοφία: smoke-test πρώτα, μετά κλιμάκωση

Δύο ανεξάρτητοι άξονες μεγέθους. Πρώτα επιβεβαιώνουμε ότι ΟΛΟΣ ο αγωγός «τρέχει» στο
μικρό, μετά μεγαλώνουμε:

| Άξονας | Smoke (τώρα) | Full (μετά) |
|---|---|---|
| Μοντέλο | tiny (π.χ. Qwen2.5-1.5B-Instruct) — γρήγορο/φθηνό, μόνο για plumbing | Llama-3.1-8B · Qwen3-8B · SaulLM-7B |
| Dataset | 2234 υποθέσεις (train 1569 / val 330 / test 335) | επέκταση σε αρκετές χιλιάδες |
| Στόχος | «τρέχει χωρίς σφάλματα end-to-end;» | «έχει το πείραμα στατιστική ισχύ;» |

Ο μικρός δρόμος πρέπει να ολοκληρώνεται σε λεπτά, ώστε κάθε αλλαγή να δοκιμάζεται φθηνά.

## Στάδια

**Στάδιο 0 — Data pipeline · ✅ DONE**
collect → dedupe → enrich_authors → enrich_ideology → lawma_label → `juribench_dataset.csv` (2234)
→ `enrich_case_fields.py` → `juribench_cases.csv` (facts/issue_text/disposition, 2234/2234)
→ `make_splits.py` → `data/splits/{train,val,test}.jsonl` (author-disjoint, court-stratified).

**Στάδιο 1 — Formatting · ▶ τώρα**
`build_finetune.py`: splits → chat *messages* JSONL, model-agnostic. Δύο variants:
- `generation`: input → σκεπτικό/opinion + έκβαση
- `predict`: input(facts+issue) → μόνο `disposition` (LJP benchmark, χωρίς opinion στο input)
Παράμετρος `--max-target-chars` (granularity). Κρατά `meta` για joins στην αξιολόγηση.

**Στάδιο 2 — Training (Colab, QLoRA)**
Notebook: (a) smoke run με tiny model σε λίγα steps → σιγουριά ότι φορτώνει/εκπαιδεύεται/σώζει·
(b) full run στα 3 μοντέλα. Αποθήκευση adapters + config ανά μοντέλο.

**Στάδιο 3 — Generation (inference)**
Για κάθε μοντέλο, παραγωγή στο `test` (generation + predict). Έξοδος: `preds/{model}.jsonl`
με το παραγόμενο κείμενο + το προβλεπόμενο `disposition`, ευθυγραμμισμένα με το gold μέσω `id`.

**Στάδιο 4 — Evaluation**
Μετρικές (core → πλήρες):
1. Ορθότητα έκβασης: accuracy + macro-F1 (`disposition`), accuracy `prevailing_party`.
2. Citation-hallucination: εξαγωγή παραπομπών → επαλήθευση με CourtListener citation-lookup API.
3. Ποιότητα λόγου (gen vs authentic): πολυπλοκότητα (Flesch-Kincaid, TTR), ορολογική πυκνότητα,
   συνοχή/θεσμική συνέπεια με LLM-as-judge (ρουμπρίκα 0–5).
4. Ιδεολογική πιστότητα: ideology classifier σε gen vs authentic (agreement/F1).
5. BERTScore/ROUGE-L έναντι πραγματικής γνωμοδότησης (δευτερεύον).
6. Turing-style pairwise (LLM/human judge) win rate.

**Στάδιο 5 — Ανάλυση & σύγκριση**
3 μοντέλα × μετρικές, με breakdown ανά court και ανά ideology (προσοχή σε cells N<10).
Κεντρικό ερώτημα: βοηθά η νομική εξειδίκευση (SaulLM) vs γενικά μοντέλα;

**Στάδιο 6 — Κλιμάκωση dataset**
Αφού «κυλήσουν» όλα, τρέξε ξανά το Στάδιο 0 collector με μεγαλύτερο target/εύρος ετών,
ξανα-splits, και επανάληψη 2–5 στα full μοντέλα.

## Αποφάσεις που εκκρεμούν
- Base models (3) — επιβεβαίωση· tiny model για smoke.
- Target granularity: πλήρες opinion vs σκεπτικό+holding (μέσω `--max-target-chars`).
- Θα μπει η ιδεολογία στο prompt (conditioning) ή μένει eval-only; (προεπιλογή: eval-only).

## Εκκρεμότητες ασφάλειας/καθαριότητας
- Reset του CourtListener token (είχε διαρρεύσει).
- `enrich_case_fields.py` γρ. 170: αφαίρεση του hardcoded OpenRouter key (default "").

## File map (JuriBench/)
```
code/  juribench_collect · dedupe_case_names · enrich_authors · enrich_ideology
       lawma_label · dataset_stats · enrich_case_fields · make_splits
       build_finetune (Στάδιο 1) · [train notebook, generate, evaluate — επόμενα]
data/  juribench_dataset.csv · juribench_cases.csv · splits/ · [finetune/, preds/, results/]
```

# CLAUDE.md — Context για τον AI βοηθό

Αυτό το αρχείο δίνει σε μια νέα session όλη την εικόνα ώστε να συνεχίσει σωστά.

## Τι είναι
Διπλωματική ΕΜΠ (επιβλέποντες Τσανάκας, Κόνιαρης): «Προσομοίωση & Ανάλυση Δικαστικού/
Δικηγορικού Λόγου μέσω LLMs». Repo: `JuriBench-Thesis-NTUA` (private).

## Το task
Δίνεται υπόθεση (`facts` + `issue_text` + δικαστήριο) → μοντέλο παράγει την απόφαση
(σκεπτικό + έκβαση `disposition`) → αξιολόγηση παραγόμενου vs αυθεντικού.
Δεύτερο variant: `predict` (LJP) = μόνο πρόβλεψη έκβασης, χωρίς κείμενο.

## Δεδομένα
- Βάση: το **διορθωμένο dataset του καθηγητή** `data/juribench_dataset.csv` (2234 υποθέσεις:
  SCOTUS 307 / CA5 980 / CA9 947), ήδη enriched (ideology JuDJIS/MQ, issue_area SCDB/Lawma).
- Επέκταση δική μας: `data/juribench_cases.csv` = + `facts`, `issue_text`, `disposition`,
  `prevailing_party` (από `enrich_case_fields.py`, LLM extraction από το opinion).
- Splits: `data/splits/{train,val,test}.jsonl` — **author-disjoint & court-stratified**
  (train 1569 / val 330 / test 335). Format: `data/finetune/{generation,predict}/*.jsonl`.

## Κανόνες (ΜΗΝ τους παραβείς)
- **Ιδεολογία labels: ΠΟΤΕ LLM.** Μόνο JuDJIS + Martin-Quinn. Unmatched → κενό
  (`docs/issues.md` #5, banned gpt4o_fallback). SCOTUS class = πρόσημο MQ (re-binning).
- Ιδεολογία = **eval-only**. Το `eval_ideology.py` είναι **παρκαρισμένο** μέχρι να υπάρχει
  καλό/μεγαλύτερο dataset (απόφαση χρήστη).
- Input δεν διαρρέει την έκβαση.

## Ροή εργασίας
- **Κώδικας** στο GitHub· ο χρήστης τρέχει τα πάντα σε **Google Colab**· **δεδομένα/outputs**
  στο **Google Drive** (`/content/drive/MyDrive/University/Διπλωματική/JuriBench`).
- Colab setup-κελί: `git clone` + symlink `data/adapters/preds/results` → Drive (δες RUN.md).
- **Ο βοηθός επεξεργάζεται τα αρχεία στον Mac** (`~/Desktop/UNIVERSITY/ΕΜΠ/ΔΙΠΛΩΜΑΤΙΚΗ/
  JuriBench`), **ΔΕΝ κάνει push** — ο χρήστης κάνει `git add/commit/push` από Mac, μετά
  `git pull` στο Colab. (Ζήτα έγκριση πριν ενέργειες όταν το ζητά ο χρήστης.)
- Scripts βρίσκουν το root μέσω `Path(__file__).parent.parent` → **κράτα το `code/` flat**
  (μη μετακινείς scripts σε υποφακέλους, σπάει τα data paths & τις εντολές).

## Secrets / env (.env, gitignored)
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` (OpenRouter) — για enrich_case_fields, eval_judge.
- `CL_API_TOKEN` — CourtListener (collector, citation-hallucination).
- HF login μόνο για gated μοντέλο (Llama-3.1). Qwen/SaulLM ανοιχτά.
- Γνωστό εκκρεμές: το `enrich_case_fields.py` γρ.170 έχει hardcoded OpenRouter key (ο χρήστης
  το κρατά προς το παρόν — private repo· να αφαιρεθεί αργότερα → `os.environ.get("LLM_API_KEY","")`).

## Gotchas (λύθηκαν ήδη — μην τα «ξαναανακαλύπτεις»)
- **T4 δεν υποστηρίζει bf16** → `train_qlora.py` επιλέγει μόνο του bf16/fp16.
- **TRL version drift** → `train_qlora.py` ανιχνεύει τα σωστά ονόματα params (max_seq_length/
  max_length, eval_strategy, tokenizer/processing_class).
- **`apply_chat_template` επιστρέφει dict** στη νέα έκδοση → `generate.py` χρησιμοποιεί `return_dict=True`.
- **`subprocess.run` κρύβει output** στο Colab → για ζωντανή έξοδο τρέχε με `!python ...`.
- **QLoRA 8B σε T4 είναι αργό** (~1h/3 epochs) → για tests: `--epochs 1 --batch 4` ή μικρά μοντέλα + `--max-*`.
- Το mount του βοηθού μερικές φορές κάνει deadlock σε μεγάλα/cloud αρχεία· τα zip διαβάζονται.

## Πού είμαστε
Ολόκληρος ο αγωγός (train→generate→evaluate→compare) **δοκιμασμένος end-to-end** με μικρά
μοντέλα (predict). Επόμενο ορόσημο: **Στάδιο 6 — μεγέθυνση dataset** (collector του καθηγητή,
enrich μόνο JuDJIS/MQ), μετά full runs στα 3 μοντέλα (Qwen3-8B / Llama-3.1-8B / SaulLM-7B),
ανάλυση, συγγραφή. Λεπτομερές πλάνο: `ROADMAP.md`.

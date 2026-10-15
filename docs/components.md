# JuriBench — Αναφορά αρχείων

Ανασκόπηση κάθε αρχείου: τι κάνει, πώς το κάνει τεχνικά, και τι πρόβλημα λύνει.

---

## Scripts (`code/`)

### bulk_filter.py
- **Τι κάνει:** Φτιάχνει το dataset από τα CourtListener bulk data (SCOTUS/CA5/CA9, Published, 2015–2024, ≥500 λέξεις, όχι per curiam).
- **Πώς το κάνει (τεχνικά):** Streaming 3 περάσματα (dockets → clusters → opinions) σε bz2 χωρίς αποσυμπίεση των ~350GB· reader με `escapechar='\\'` (Postgres export)· 1 κύρια γνώμη ανά υπόθεση· ίδιες 12 στήλες με τον collector.
- **Πρόβλημα που λύνει:** Χωρίς όριο API (125/μέρα) και χωρίς όριο 1.000/δικαστήριο → 10.997 υποθέσεις.

### split_opinions.py
- **Τι κάνει:** Χωρίζει τις γνώμες κάθε υπόθεσης (αίτημα καθηγητή 2026-10-08): `opinion_text` = majority (`020lead`), `dissent_text` (`040dissent`), `concurrence_text` (`030concurrence`), `combined_only=1` για μόνο `010combined` (κείμενο ως έχει).
- **Πώς το κάνει (τεχνικά):** Streaming των bulk opinions για τα cluster_ids μας, ένωση πολλαπλών με κενή γραμμή· γράφει dump `data/opinions_by_type.jsonl.gz` ώστε τα επόμενα τρεξίματα (`--from-dump`) να γίνονται σε λεπτά· διαβάζει πάντα από `juribench_cases.pre_split.csv`. Default = ακριβώς η οδηγία του καθηγητή· opt-in μόνο με έγκριση: `--text-split`, `--majority-fallback`, `--concur-in-part`.
- **Πρόβλημα που λύνει:** Το παλιό `opinion_text` είχε ενωμένα majority + dissent + concurrence.

### enrich_scdb.py
- **Τι κάνει:** SCOTUS ↔ SCDB (αίτημα καθηγητή 2026-10-08): docket → usCite → όνομα+έτος· συμπληρώνει scdb_id, issue_area, decision_direction, ιδεολογία Martin-Quinn.
- **Πώς το κάνει (τεχνικά):** Streaming bulk clusters (cluster→docket_id) + dockets (docket_number) + προαιρετικά citations (U.S.)· normalization docket (No./Nos., en dash, «Orig.»)· το scdb_id του CourtListener μόνο ως διασταύρωση· idempotent.
- **Πρόβλημα που λύνει:** Το match όνομα+έτος αποτύγχανε σε διαφορετικές γραφές («SEC» vs «SECURITIES AND EXCHANGE COMMISSION», «Revisions: …») → 296 → ~700 / 720.

### completeness_report.py
- **Τι κάνει:** Αναφορά πληρότητας για τον καθηγητή.
- **Πώς το κάνει (τεχνικά):** Πληρότητα ανά πεδίο μόνο όπου εφαρμόζεται (π.χ. decision_direction μόνο SCOTUS), επίπεδα A (generation) / B (LJP) / C–D (πλήρη μεταδεδομένα πριν/μετά Lawma), διάγνωση ελλείψεων, markdown (`--md`).
- **Πρόβλημα που λύνει:** «Πόσα λείπουν / πόσα είναι πλήρη» χωρίς να μεταφερθεί το μεγάλο αρχείο.

### dedupe_case_names.py
- **Τι κάνει:** Αφαιρεί διπλότυπες υποθέσεις.
- **Πώς το κάνει (τεχνικά):** Κλειδί (δικαστήριο, κανονικοποιημένο case_name, ημερομηνία), κρατά την πρώτη εγγραφή.
- **Πρόβλημα που λύνει:** «Revisions»/επανεκδόσεις της ίδιας υπόθεσης μόλυναν το σύνολο.

### enrich_authors.py
- **Τι κάνει:** Βρίσκει τον συγγραφέα δικαστή (circuits): `author_str`, `author_source` (signature / opinion_by / none / manual), `author_initials`.
- **Πώς το κάνει (τεχνικά):** Από 2026-10-12 χρησιμοποιεί το `parse_author.py` του καθηγητή (αμετάβλητο) + `author_initials.py`· στο τέλος εφαρμόζει το `data/author_overrides.csv` (χειροκίνητα, `author_source = manual`).
- **Πρόβλημα που λύνει:** Η παλιά regex έπαιρνε τον τελευταίο της γραμμής «Before» (σωστό μόνο ~55%) → τώρα ~99%.

### parse_author.py  *(του καθηγητή — ΑΜΕΤΑΒΛΗΤΟ)*
- **Τι κάνει:** `parse_author(text) -> (surname, source)` — αφαιρεί τη γραμμή σύνθεσης και βρίσκει την υπογραφή ή το «Opinion by Judge X».

### author_initials.py
- **Τι κάνει:** Αρχικά του συγγραφέα (για συνωνυμίες: M. / N.R. Smith κ.λπ.) και `signed_as_district()` («District Judge» → by designation).
- **Πώς το κάνει (τεχνικά):** Ίδια υπογραφή με το parse_author → ονόματα πριν το επώνυμο· αλλιώς «Opinion by» · αλλιώς γραμμή «Before:» / «The Honorable … sitting by designation» (μόνο αν 1 όνομα).

### judge_aliases.py
- **Τι κάνει:** Κοινός πίνακας ταυτίσεων (Richman=Owen, Forrest=Hunsaker, Ramirez=Carrillo Ramirez) + διορθώσεις OCR (IKLUTA→IKUTA κ.ά.) + συμβατότητα αρχικών.

### enrich_ideology.py
- **Τι κάνει:** Αποδίδει ιδεολογία· για SCOTUS και issue_area/decision_direction.
- **Πώς το κάνει (τεχνικά):** SCOTUS→SCDB→Martin-Quinn (post_mn)· circuits→JuDJIS με **ακριβές επώνυμο** (+ταυτίσεις/OCR, όχι fuzzy από 2026-10-14)· εν ενεργεία στη `date_filed` (FJC) · αρχικά για συνωνυμίες · «District Judge» → όχι JuDJIS. `--circuits-only` = δεν αγγίζει SCOTUS. Καθόλου LLM· unmatched μένουν κενά.
- **Πρόβλημα που λύνει:** Αξιόπιστη ιδεολογική επισήμανση από καθιερωμένες ακαδημαϊκές πηγές.

### clean_headers.py
- **Τι κάνει:** Αφαιρεί κεφαλίδες σελίδας PDF (CA5 ECF «Case: … Document: … Page: …», CA9 επαναλαμβανόμενο caption, ECF παραρτημάτων) από opinion/dissent/concurrence.
- **Πρόβλημα που λύνει:** Θόρυβος στο κείμενο-στόχο. Μόνο ασφαλείς, πολύ συγκεκριμένοι κανόνες.

### opinion_kind.py
- **Τι κάνει:** Στήλη `opinion_kind` ∈ merits / summary_order / memorandum / per_curiam / order — καμία αφαίρεση.

### ideology_fallback.py
- **Τι κάνει:** `ideology_fallback` (JCS score, αλλιώς κόμμα Προέδρου από FJC), `ideology_fallback_source` (jcs / party / party_fjc), `author_visiting`.
- **Πώς το κάνει (τεχνικά):** FJC: ίδιο circuit + εν ενεργεία στη date_filed (+αρχικά για συνωνυμίες)· by designation / «District Judge» → αναζήτηση σε όλα τα δικαστήρια (District Courts) → party_fjc. Δεν αλλάζει τα `ideology*`.

### dedupe.py  *(του καθηγητή — ΑΜΕΤΑΒΛΗΤΟ, v2 2026-10-15)*
- **Τι κάνει:** Τελευταίο βήμα: σελίδες σύγκρισης SCOTUS · σκουπίδια · ίδια κείμενα · WRONG_COURT_IDS · κείμενα που δεν είναι μόνο η πλειοψηφία · τροποποιημένες εκδόσεις (ίδιο όνομα) · σχεδόν ίδιες αποφάσεις με άλλο όνομα (Jaccard 5-grams όλου του κειμένου ≥ 0,5).

### drop_wrong_court.py  *(πλεονάζει από το dedupe v2)*
- **Τι κάνει:** Αφαιρεί υποθέσεις άλλου circuit βάσει `data/wrong_court.csv`.

### lawma_label.py
- **Τι κάνει:** Θεματική περιοχή (issue_area) στα circuits.
- **Πώς το κάνει (τεχνικά):** Νομικό μοντέλο Lawma-70B (MMLU-style)· SCOTUS = σύνολο επικύρωσης με SCDB ground truth.
- **Πρόβλημα που λύνει:** Τα circuits δεν έχουν έτοιμη κατηγοριοποίηση όπως το SCDB.

### enrich_case_fields.py
- **Τι κάνει:** Παράγει facts, issue_text, disposition, prevailing_party.
- **Πώς το κάνει (τεχνικά):** LLM εξαγωγή από opinion_text (head+tail), αυστηρό JSON, ρητός έλεγχος leakage, resumable.
- **Πρόβλημα που λύνει:** Έλειπαν τα πεδία input/έκβαση του task (το syllabus ήταν stub ~15 λέξεων).

### make_splits.py
- **Τι κάνει:** Χωρίζει train/val/test.
- **Πώς το κάνει (τεχνικά):** Author-disjoint & court-stratified, ντετερμινιστικό (seed), έξοδος JSONL.
- **Πρόβλημα που λύνει:** Αποτρέπει διαρροή ύφους δικαστή μεταξύ των συνόλων.

### build_finetune.py
- **Τι κάνει:** Μετατρέπει τα splits σε δεδομένα εκπαίδευσης.
- **Πώς το κάνει (τεχνικά):** Chat messages μορφή, δύο variants (generation, predict), cap μήκους target, model-agnostic.
- **Πρόβλημα που λύνει:** Γεφυρώνει το dataset με τον TRL SFTTrainer.

### train_qlora.py
- **Τι κάνει:** Fine-tuning ενός μοντέλου.
- **Πώς το κάνει (τεχνικά):** QLoRA (4-bit κβαντισμός + LoRA), auto bf16/fp16, ανθεκτικό σε εκδόσεις TRL, σώζει adapter.
- **Πρόβλημα που λύνει:** Εκπαίδευση 7–8B μοντέλων σε περιορισμένη GPU (Colab T4/L4).

### generate.py
- **Τι κάνει:** Παράγει αποφάσεις/εκβάσεις στο test.
- **Πώς το κάνει (τεχνικά):** Φορτώνει base+adapter, apply_chat_template, greedy decoding, parse disposition.
- **Πρόβλημα που λύνει:** Δίνει προβλέψεις ευθυγραμμισμένες με τα gold για αξιολόγηση.

### evaluate.py
- **Τι κάνει:** Ποσοτικές μετρικές.
- **Πώς το κάνει (τεχνικά):** Accuracy/macro-F1 έκβασης, discourse stats, BERTScore, citation-hallucination (CourtListener citation-lookup).
- **Πρόβλημα που λύνει:** Αντικειμενική μέτρηση ορθότητας & ποιότητας.

### eval_judge.py
- **Τι κάνει:** Βαθμολόγηση ποιότητας λόγου.
- **Πώς το κάνει (τεχνικά):** LLM-as-judge, ρουμπρίκα 1–5 (συνοχή/ορολογία/θεσμική συνέπεια/πιστότητα), cache ανά υπόθεση.
- **Πρόβλημα που λύνει:** Μετρά ποιοτικά χαρακτηριστικά που δεν πιάνουν οι αριθμητικές μετρικές.

### eval_ideology.py  *(παρκαρισμένο)*
- **Τι κάνει:** Ιδεολογική πιστότητα του παραγόμενου κειμένου (E2).
- **Πώς το κάνει (τεχνικά):** LLM classifier Lib/Cons/Mod, σύγκριση με gold ιδεολογία (accuracy/macro-F1).
- **Πρόβλημα που λύνει:** Ελέγχει αν το παραγόμενο κείμενο διατηρεί το ιδεολογικό lean του δικαστή.

### compare_results.py
- **Τι κάνει:** Συγκεντρωτικός πίνακας μοντέλων.
- **Πώς το κάνει (τεχνικά):** Διαβάζει results/*.json, εκτύπωση πίνακα + summary.csv.
- **Πρόβλημα που λύνει:** Άμεση αντιπαραβολή επιδόσεων μεταξύ μοντέλων.

### llm_client.py
- **Τι κάνει:** Κοινός βοηθός κλήσεων LLM.
- **Πώς το κάνει (τεχνικά):** OpenAI-compatible chat completions, JSON parsing, retries/backoff.
- **Πρόβλημα που λύνει:** Αποφυγή διπλού κώδικα σε eval_judge/eval_ideology.

### dataset_stats.py
- **Τι κάνει:** Έλεγχος υγείας dataset.
- **Πώς το κάνει (τεχνικά):** Coverage, κατανομές, flags για αραιά (N<10) κελιά.
- **Πρόβλημα που λύνει:** Γρήγορη επισκόπηση ποιότητας πριν τα πειράματα.

### validate_classifier.py  *(legacy, από τον καθηγητή)*
- **Τι κάνει:** Παλιός GPT ταξινομητής issue_area.
- **Πώς το κάνει (τεχνικά):** OpenRouter, επικύρωση σε SCOTUS.
- **Πρόβλημα που λύνει:** Προκάτοχος του lawma_label — δεν χρησιμοποιείται πλέον.

### Αφαιρέθηκαν από το repo (2026-10-15)
Παλιά ή μιας χρήσης scripts, που υπάρχουν στο ιστορικό του git: `juribench_collect.py` (αντικαταστάθηκε από το bulk_filter), `enrich_scdb_ids.py` (από το enrich_scdb), `inspect_split.py`, `check_authors.py`, `diag_unknown_authors.py`, `diag_round2.py`, `export_unknown_authors.py`, `export_ids_context.py` (διαγνωστικά, μόνο ανάγνωση).

---

## Δεδομένα (`data/`, εκτός git)

> **ΤΕΛΙΚΟ (2026-10-15):** `juribench_labeled.dedup.csv` του καθηγητή (9.347, μέσα στο `data.zip` στον φάκελο ΔΙΠΛΩΜΑΤΙΚΗ). Τα παρακάτω είναι ιστορικά. Στο git μόνο: `data/author_overrides.csv`, `data/wrong_court.csv`.

### juribench_dataset.csv
- **Τι κάνει:** Το enriched & deduped dataset του επιβλέποντα.
- **Πώς το κάνει (τεχνικά):** Έξοδος των Σταδίων collect→lawma_label· 2234 γραμμές, 19 πεδία (opinion, ιδεολογία, issue_area κ.λπ.).
- **Πρόβλημα που λύνει:** Η καθαρή βάση πάνω στην οποία χτίζεται το task.

### juribench_cases.csv
- **Τι κάνει:** Το dataset + τα πεδία του task.
- **Πώς το κάνει (τεχνικά):** Έξοδος του enrich_case_fields· 2234 γραμμές, 26 πεδία (+facts/issue_text/disposition/prevailing_party).
- **Πρόβλημα που λύνει:** Το πλήρες, έτοιμο-για-χρήση σύνολο (input + έκβαση).

### splits/{train,val,test}.jsonl
- **Τι κάνει:** Τα διαχωρισμένα σύνολα.
- **Πώς το κάνει (τεχνικά):** Έξοδος make_splits· author-disjoint, court-stratified (1569/330/335).
- **Πρόβλημα που λύνει:** Έγκυρη αξιολόγηση χωρίς διαρροή.

### finetune/{generation,predict}/*.jsonl
- **Τι κάνει:** Δεδομένα σε μορφή chat για εκπαίδευση.
- **Πώς το κάνει (τεχνικά):** Έξοδος build_finetune· messages format ανά task.
- **Πρόβλημα που λύνει:** Άμεση τροφοδοσία στον SFTTrainer.

### scdb/ · mqscores/ · judjis/
- **Τι κάνει:** Πηγές εμπλουτισμού (SCDB, Martin-Quinn, JuDJIS).
- **Πώς το κάνει (τεχνικά):** Τοπικοί πίνακες που διαβάζει το enrich_ideology (join χωρίς δίκτυο).
- **Πρόβλημα που λύνει:** Ιδεολογία & issue_area από αξιόπιστες, μη-LLM πηγές.

### adapters/ · preds/ · results/
- **Τι κάνει:** Παράγωγα των runs (adapters LoRA, προβλέψεις, μετρικές).
- **Πώς το κάνει (τεχνικά):** Δημιουργούνται από train/generate/evaluate· symlinked στο Drive στο Colab.
- **Πρόβλημα που λύνει:** Διατήρηση αποτελεσμάτων πέρα από τη session.

---

## Έγγραφα & ρυθμίσεις

### README.md · RUN.md
- **Τι κάνει:** Τεκμηρίωση (επισκόπηση, οδηγίες εκτέλεσης).
- **Πώς το κάνει (τεχνικά):** Markdown στη ρίζα του repo.
- **Πρόβλημα που λύνει:** Σαφήνεια, αναπαραγωγιμότητα, συνέχεια εργασίας.

### requirements.txt · requirements-train.txt · .env.example · .gitignore
- **Τι κάνει:** Εξαρτήσεις, υπόδειγμα κλειδιών, κανόνες αποκλεισμού από git.
- **Πώς το κάνει (τεχνικά):** requirements-train για Colab/GPU· .env (μυστικά) εκτός git.
- **Πρόβλημα που λύνει:** Στήσιμο περιβάλλοντος & προστασία μυστικών/μεγάλων αρχείων.

### docs/ (issues.md, professor-code-notes.md, pipeline-notes.md)
- **Τι κάνει:** Σημειώσεις επιβλέποντα (issues, professor-code-notes) & pipeline.
- **Πώς το κάνει (τεχνικά):** Markdown αναφοράς.
- **Πρόβλημα που λύνει:** Ιστορικό αποφάσεων & αιτιολόγηση.

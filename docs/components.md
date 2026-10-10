# JuriBench — Αναφορά αρχείων

Ανασκόπηση κάθε αρχείου: τι κάνει, πώς το κάνει τεχνικά, και τι πρόβλημα λύνει.

---

## Scripts (`code/`)

### juribench_collect.py  *(παλιό — αντικαταστάθηκε από bulk_filter)*
- **Τι κάνει:** Συλλέγει δικαστικές γνωμοδοτήσεις (SCOTUS/CA5/CA9).
- **Πώς το κάνει (τεχνικά):** CourtListener search API, round-robin ανά μήνα, φιλτράρισμα per curiam & <500 λέξεων κατά τη συλλογή, resumable (skip seen cluster_ids).
- **Πρόβλημα που λύνει:** Δημιουργεί αναπαραγώγιμα το πρωτογενές σώμα κειμένων.

### bulk_filter.py
- **Τι κάνει:** Φτιάχνει το dataset από τα CourtListener bulk data (SCOTUS/CA5/CA9, Published, 2015–2024, ≥500 λέξεις, όχι per curiam).
- **Πώς το κάνει (τεχνικά):** Streaming 3 περάσματα (dockets → clusters → opinions) σε bz2 χωρίς αποσυμπίεση των ~350GB· reader με `escapechar='\\'` (Postgres export)· 1 κύρια γνώμη ανά υπόθεση· ίδιες 12 στήλες με τον collector.
- **Πρόβλημα που λύνει:** Χωρίς όριο API (125/μέρα) και χωρίς όριο 1.000/δικαστήριο → 10.997 υποθέσεις.

### split_opinions.py
- **Τι κάνει:** Χωρίζει τις γνώμες κάθε υπόθεσης (αίτημα καθηγητή 2026-10-08): `opinion_text` = majority (`020lead`), `dissent_text` (`040dissent`), `concurrence_text` (`030concurrence`), `combined_only=1` για μόνο `010combined` (κείμενο ως έχει).
- **Πώς το κάνει (τεχνικά):** Streaming των bulk opinions για τα cluster_ids μας, ένωση πολλαπλών με κενή γραμμή· γράφει dump `data/opinions_by_type.jsonl.gz` ώστε τα επόμενα τρεξίματα (`--from-dump`) να γίνονται σε λεπτά· διαβάζει πάντα από `juribench_cases.pre_split.csv`. Default = ακριβώς η οδηγία του καθηγητή· opt-in μόνο με έγκριση: `--text-split`, `--majority-fallback`, `--concur-in-part`.
- **Πρόβλημα που λύνει:** Το παλιό `opinion_text` είχε ενωμένα majority + dissent + concurrence.

### inspect_split.py
- **Τι κάνει:** Έλεγχος ποιότητας του διαχωρισμού από το κείμενο (μόνο αν εγκριθεί το text-split).
- **Πώς το κάνει (τεχνικά):** (1) υποθέσεις χωρίς διαχωρισμό που περιέχουν ύποπτη επικεφαλίδα γνώμης, (2) τυχαία δείγματα σημείων κοπής.
- **Πρόβλημα που λύνει:** Ορατότητα στα λάθη του regex πριν χρησιμοποιηθεί.

### enrich_scdb.py
- **Τι κάνει:** SCOTUS ↔ SCDB (αίτημα καθηγητή 2026-10-08): docket → usCite → όνομα+έτος· συμπληρώνει scdb_id, issue_area, decision_direction, ιδεολογία Martin-Quinn.
- **Πώς το κάνει (τεχνικά):** Streaming bulk clusters (cluster→docket_id) + dockets (docket_number) + προαιρετικά citations (U.S.)· normalization docket (No./Nos., en dash, «Orig.»)· το scdb_id του CourtListener μόνο ως διασταύρωση· idempotent.
- **Πρόβλημα που λύνει:** Το match όνομα+έτος αποτύγχανε σε διαφορετικές γραφές («SEC» vs «SECURITIES AND EXCHANGE COMMISSION», «Revisions: …») → 296 → ~700 / 720.

### enrich_scdb_ids.py  *(παλιό — αντικαταστάθηκε από enrich_scdb)*
- **Τι κάνει:** SCOTUS ↔ SCDB μόνο μέσω του scdb_id των bulk clusters (296/720 είχαν).

### completeness_report.py
- **Τι κάνει:** Αναφορά πληρότητας για τον καθηγητή.
- **Πώς το κάνει (τεχνικά):** Πληρότητα ανά πεδίο μόνο όπου εφαρμόζεται (π.χ. decision_direction μόνο SCOTUS), επίπεδα A (generation) / B (LJP) / C–D (πλήρη μεταδεδομένα πριν/μετά Lawma), διάγνωση ελλείψεων, markdown (`--md`).
- **Πρόβλημα που λύνει:** «Πόσα λείπουν / πόσα είναι πλήρη» χωρίς να μεταφερθεί το μεγάλο αρχείο.

### dedupe_case_names.py
- **Τι κάνει:** Αφαιρεί διπλότυπες υποθέσεις.
- **Πώς το κάνει (τεχνικά):** Κλειδί (δικαστήριο, κανονικοποιημένο case_name, ημερομηνία), κρατά την πρώτη εγγραφή.
- **Πρόβλημα που λύνει:** «Revisions»/επανεκδόσεις της ίδιας υπόθεσης μόλυναν το σύνολο.

### enrich_authors.py
- **Τι κάνει:** Βρίσκει τον συγγραφέα δικαστή (circuits).
- **Πώς το κάνει (τεχνικά):** Byline-anchored regex στα πρώτα ~2000 chars του opinion.
- **Πρόβλημα που λύνει:** Η αρχική εξαγωγή ονομάτων έβγαζε σκουπίδια, χαλώντας το ideology matching.

### enrich_ideology.py
- **Τι κάνει:** Αποδίδει ιδεολογία· για SCOTUS και issue_area/decision_direction.
- **Πώς το κάνει (τεχνικά):** SCOTUS→SCDB→Martin-Quinn (post_mn)· circuits→JuDJIS με Jaro-Winkler ≥0.92. Καθόλου LLM· unmatched μένουν κενά.
- **Πρόβλημα που λύνει:** Αξιόπιστη ιδεολογική επισήμανση από καθιερωμένες ακαδημαϊκές πηγές.

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

### validate_classifier.py  *(legacy)*
- **Τι κάνει:** Παλιός GPT ταξινομητής issue_area.
- **Πώς το κάνει (τεχνικά):** OpenRouter, επικύρωση σε SCOTUS.
- **Πρόβλημα που λύνει:** Προκάτοχος του lawma_label — δεν χρησιμοποιείται πλέον.

---

## Δεδομένα (`data/`, εκτός git)

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

### README.md · ROADMAP.md · RUN.md · CLAUDE.md
- **Τι κάνει:** Τεκμηρίωση (επισκόπηση, πλάνο, οδηγίες εκτέλεσης, context για AI βοηθό).
- **Πώς το κάνει (τεχνικά):** Markdown στη ρίζα του repo.
- **Πρόβλημα που λύνει:** Σαφήνεια, αναπαραγωγιμότητα, συνέχεια εργασίας.

### requirements.txt · requirements-train.txt · .env.example · .gitignore
- **Τι κάνει:** Εξαρτήσεις, υπόδειγμα κλειδιών, κανόνες αποκλεισμού από git.
- **Πώς το κάνει (τεχνικά):** requirements-train για Colab/GPU· .env (μυστικά) εκτός git.
- **Πρόβλημα που λύνει:** Στήσιμο περιβάλλοντος & προστασία μυστικών/μεγάλων αρχείων.

### docs/ (issues.md, pipeline-notes.md, mynotes.md, professor-code-notes.md)
- **Τι κάνει:** Σημειώσεις επιβλέποντα & pipeline.
- **Πώς το κάνει (τεχνικά):** Markdown αναφοράς.
- **Πρόβλημα που λύνει:** Ιστορικό αποφάσεων & αιτιολόγηση.

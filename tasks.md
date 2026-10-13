# tasks.md — Λίστα εργασιών JuriBench

Όλα τα tasks της διπλωματικής σε ένα σημείο: πότε ζητήθηκαν, από ποιον, και αν έγιναν.
Ενημερώνεται σε κάθε session μαζί με το `CLAUDE.md` (εκεί υπάρχει το πλήρες context).

**Status:** ✅ έγινε · 🔄 σε εξέλιξη · ⏳ εκκρεμεί · 👤 το κάνει ο καθηγητής · 💤 παρκαρισμένο
**Ημερομηνίες:** το «~» σημαίνει κατά προσέγγιση (ανακατασκευή από το ιστορικό συνομιλιών).

---

## A. Αιτήματα καθηγητή — email Κόνιαρη (2026-10-08)

| # | Task | Ζητήθηκε | Status | Σημειώσεις |
|---|---|---|---|---|
| A1 | **Διαχωρισμός γνωμών:** `opinion_text` = μόνο majority (`020lead`) · νέες στήλες `dissent_text` (`040dissent`) και `concurrence_text` (`030concurrence`), πολλαπλές ενωμένες με κενή γραμμή | 2026-10-08 | ✅ 2026-10-10 | Αυστηρό rebuild (από `.pre_split.csv`): type 1.234 · combined_only=1 **9.158** · με dissent **366** · με concurrence **254** · αγνοήθηκαν `035concurrenceinpart` 120, `070rehearing` 3 · 3 υποθέσεις (CA5 2, CA9 1) χωρίς majority/combined → κράτησαν το παλιό κείμενο, `combined_only` κενό (→ Q2). Dump `data/opinions_by_type.jsonl.gz` (136MB) → `--from-dump` για αλλαγές. |
| A2 | Υποθέσεις μόνο με `010combined` → κείμενο ως έχει στο `opinion_text` + στήλη `combined_only = 1` | 2026-10-08 | 🔄 | **Επαναφορά στην ακριβή οδηγία (2026-10-10):** είχαμε χωρίσει ~1.930 combined από το κείμενο χωρίς έγκριση → αναιρείται. Default πλέον αυστηρό: combined ως έχουν, χωρίς `split_method`. Ο text-split μένει μόνο ως opt-in (`--text-split`) → **ερώτηση Q1**. Εκκρεμεί νέο streaming (strict + dump). |
| A2b | Καθάρισμα κεφαλίδων σελίδας PDF μέσα στα κείμενα (CA5: «Case: … Document: … Page: … Date Filed: …»· CA9: «36 UNITED STATES V. LOPEZ») | 2026-10-10 | ⏳ | Δική μας παρατήρηση από τα δείγματα του inspect_split. Θόρυβος στο κείμενο-στόχο· δεν επηρεάζει τον διαχωρισμό. |
| A2c | Ερώτηση προς καθηγητή: αποφάσεις **απόρριψης rehearing en banc** (σύντομη διάταξη + μεγάλα dissents, π.χ. Thompson v. City of Waco, Book People v. Wong) — κρατούνται ως έχουν (`combined→none`) ή εξαιρούνται από τον στόχο εκπαίδευσης; | 2026-10-10 | ⏳ | Εντοπίστηκαν στο inspect_split (ενότητα 1). Το script σωστά δεν τις χωρίζει (majority < 300 λέξεις). |
| A3 | Να διευκρινιστεί με τον καθηγητή πού πάνε οι άλλοι τύποι γνώμης (`025plurality`, `035concurrenceinpart`, `015unamimous`, `050addendum` κ.λπ.) | 2026-10-08 | ⏳ | Ερώτηση προς Κόνιαρη πριν το A1. |
| A4 | Μετά το A1: επανεξαγωγή `disposition` (τουλάχιστον όπου `unclear`), γιατί το παλιό tail περιείχε συχνά dissent | 2026-10-08 | ⏳ | Πιθανή αιτία του 12,8% unclear στο SCOTUS. Δική μας πρόταση. |
| A5 | **SCOTUS ↔ SCDB μέσω docket number:** SCDB `docket` ↔ CourtListener `docket_number` → fallback `usCite` → fallback όνομα + έτος | 2026-10-08 | ✅ 2026-10-11 | `code/enrich_scdb.py`. Ακριβώς η σειρά του καθηγητή + fix en dash / «Orig.». **Τελικό (2026-10-11):** docket 698 · usCite 1 · όνομα+έτος 2 · χωρίς match 19 → **scdb_id 296 → 701/720** · issue_area 699 · ideology 657 · decision_direction 697. Διασταύρωση: 295 συμφωνούν / **1 διαφωνεί** με το CL scdb_id (να εξεταστεί — μικρό). Οι 19 χωρίς match είναι όλες μη επί της ουσίας (επείγουσες αιτήσεις «A», dissents from denial of cert) → Q3. |
| A6 | Συμπλήρωση `scdb_id` σε **όλες** τις υποθέσεις SCOTUS που βρίσκονται | 2026-10-08 | ✅ 2026-10-11 | 701/720 (όλες όσες υπάρχουν στο SCDB). issue_area/decision_direction/MQ από το ίδιο match → Q6. |
| A7 | **Circuits fallback ιδεολογίας:** νέες στήλες `ideology_fallback` (JCS score, αλλιώς κόμμα Προέδρου R/D) + `ideology_fallback_source` (`jcs`/`party`), για **όλους** τους circuit δικαστές | 2026-10-08 | ✅ 2026-10-11 | **Να μην αλλάξουν** τα `ideology` / `ideology_score`. Πηγές (2026-10-11): **JCS 2024** (epstein.wustl.edu/jcs → `JCS2024.zip`, έως 2024) + **FJC** `judges.csv` (κόμμα Προέδρου). Λήψη στο labrat ✅ (2026-10-11): `data/jcs/jcs 2024/csv/coa_judges_2024.csv` (name, circuit, jcs) + `data/fjc/judges.csv`. **`code/ideology_fallback.py`** γράφτηκε + δοκιμάστηκε σε συνθετικά: FJC (επώνυμο + ίδιο circuit + εν ενεργεία στη date_filed) → JCS (ίδιο μικρό όνομα) ή κόμμα R/D· αμφίσημα/by designation → κενό· σύγκριση με JuDJIS στην αναφορά. **Έτρεξε (2026-10-11):** συμπληρώθηκαν **8.311/9.675** circuit υποθέσεις (JCS 8.092 · κόμμα 219)· CA5 93,6% · CA9 78,7%· σύγκριση με JuDJIS: r = 0,765, συμφωνία πρόσημου 85,2% (6.904 ζεύγη). Κόμμα μόνο για 3 δικαστές: Richman (=Owen στο JCS), Forrest (=Hunsaker), Ramirez (=«Carrillo Ramirez»). Αμφίσημα 325 (Smith/Nelson/Thomas — 2 δικαστές ίδιο επώνυμο). Δεν βρέθηκαν 79 (by designation → Q7). **Βελτιώσεις σε αναμονή του A10.** |
| A8 | Μετά τα A1–A7: νέο `completeness_report`, νέα αποστολή dataset στον καθηγητή | 2026-10-08 | ✅ ~2026-10-11 | Στάλθηκε email (χωρίς .md) με αποτελέσματα A1/A5/A6/A7, εύρημα author_str και ερωτήσεις 1–9 (= Q8, Q1, Q4, Q3, Q2, Q6, Q7, Q9, Q5) + `juribench_cases.csv.gz` μέσω WeTransfer. **Αναμονή απαντήσεων.** | Report μετά A1+A5 (2026-10-11): A 10.394 · B 10.071 · D ~7.717 (74,2%). Μένει A7. Πιθανώς ο καθηγητής ξανατρέχει το Lawma. |
| A10 | **⚠ Πιθανό σφάλμα `author_str` (circuits):** το `enrich_authors.py` παίρνει το 1ο «Επώνυμο, Circuit Judge» στα πρώτα 2000 chars → συχνά ο **τελευταίος της γραμμής «Before»**, όχι ο συγγραφέας. Επηρεάζει JuDJIS ideology, author-disjoint splits, A7. | 2026-10-11 | ⏳ | **ΕΠΙΒΕΒΑΙΩΘΗΚΕ (check_authors, 2026-10-11):** author_str σωστό μόνο **59,3% (CA5)** / **53,6% (CA9)** όπου βρέθηκε ο πραγματικός συγγραφέας (3.854 / 3.948)· από τα λάθη, 1.386/1.569 (CA5) και 1.663/1.830 (CA9) = ο τελευταίος της «Before». Per curiam στην αρχή: 651 / 204. → **Q8 στον καθηγητή.** Τίποτα δεν αλλάζει πριν απαντήσει. Βελτιώσεις A7 σε αναμονή. |
| A9 | Έλεγχος: 42 SCOTUS με SCDB match αλλά χωρίς Martin-Quinn score (per curiam; ή το `justices.csv` δεν καλύπτει τα τελευταία terms;) + η 1 διαφωνία με CL scdb_id | 2026-10-11 | ⏳ | Μόνο διάγνωση (δεν αλλάζει δεδομένα χωρίς έγκριση). |

## A'. Απάντηση καθηγητή (2026-10-12) — ξαναχτίσιμο από το βήμα του συγγραφέα (χωρίς 50GB, χωρίς LLM)

| # | Task | Ημ/νία | Κατάσταση | Σημειώσεις |
|---|---|---|---|---|
| A11 | `parse_author.py` (του καθηγητή) στο `enrich_authors.py` + στήλη `author_source` (signature/opinion_by/none) | 2026-10-12 | ✅ 2026-10-12 | Σωστό 99,9% (CA5) / 99,2% (CA9) (πριν 59/54%). Χωρίς συγγραφέα 1.191. Merits χωρίς συγγραφέα **389** (αναμενόταν ~70+): ORDER 234 · καμία ένδειξη 79 · PER CURIAM μετά τους 4.000 χαρ. 53 · υπογραφή που δεν πιάστηκε 16 · «Opinion by» που δεν πιάστηκε 7 (`diag_unknown_authors.py`) → ερώτηση στον καθηγητή. |
| A12 | Διαχωρισμός combined με επικεφαλίδες: `split_method` cl_separate/heading/none · `combined_only=0` όταν πετυχαίνει | 2026-10-12 | ✅ 2026-10-12 | cl_separate 1.234 · heading 1.934 · combined_only=1 7.224 · με dissent 1.517 · με concurrence 1.048. |
| A13 | `opinion_kind` = merits/summary_order/memorandum/per_curiam — καμία αφαίρεση | 2026-10-12 | ✅ 2026-10-12 | merits 9.528 · summary_order 45 · memorandum 112 · per_curiam 710. |
| A14 | By designation → κόμμα Προέδρου από FJC (όλα τα δικαστήρια), `ideology_fallback_source = party_fjc`, `author_visiting = 1` (ακόμη κι αν είναι στο JCS) | 2026-10-12 | ✅ 2026-10-12 | Fallback 7.969/9.675 (JCS 7.523 · party_fjc 446)· r=0,784 με JuDJIS· αμφίσημα 410 (Smith 299, Nelson 84, Thomas 27)· by designation αμφίσημα 85· δεν βρέθηκαν 20 (OCR/σκουπίδια στο author_str). |
| A15 | Πίνακας ταυτίσεων Richman=Owen, Forrest=Hunsaker, Ramirez=Carrillo Ramirez για JuDJIS/JCS/FJC | 2026-10-12 | ✅ 2026-10-12 | `code/judge_aliases.py` (ανά circuit). JuDJIS 7.465. |
| A16 | Αφαίρεση κεφαλίδων PDF (CA5 ECF, CA9 «2 SHELTRA V. CHRISTENSEN») απ' όλες τις στήλες κειμένου, μόνο όπου είναι ασφαλές | 2026-10-12 | ✅ 2026-10-12 | CA5 42.599 κεφαλίδες ECF · CA9 74.121 captions · ~5,5εκ. χαρακτήρες. |
| A17 | Τρέξιμο αλυσίδας στο labrat (σειρά στο CLAUDE.md) → αριθμοί → σύντομο email | 2026-10-12 | 🔄 έτρεξε, email εκκρεμεί | Completeness D 7.853 (75,5%). Ερωτήσεις που δεν στάλθηκαν (disposition, 035/070, εξαρτώμενα SCDB): αγνοούνται προς το παρόν. |

## A''. 2η απάντηση καθηγητή (2026-10-13) — συνωνυμίες, OCR, order, ECF

| # | Task | Ποιος | Κατάσταση | Σημειώσεις |
|---|---|---|---|---|
| R2-0 | Διάγνωση (μόνο ανάγνωση): πόσοι Smith/Nelson/Thomas/visiting έχουν αρχικά στην υπογραφή ή πλήρες όνομα στο «Before:» · δείγματα ECF που έμειναν στο CA5 · στήλες JuDJIS/FJC | εγώ γράφω → εσύ τρέχεις | ✅ 2026-10-13 | Smith: αρχικά στην υπογραφή 297/299 (M. 244 · N.R. 53). Nelson: R. 35 + «D.» 44 (= Ryan D. Nelson, τελευταίος της «Before» → το «Judges» πρέπει να αποκλειστεί) + D.W. 23. Thomas: 67/107 (S.R./Sidney R. ~53, H.A./«A.» ~11), 40 χωρίς (π.χ. «THOMAS, Chief Judge:»). Visiting: πλήρες όνομα συχνά μόνο στην υποσημείωση «The Honorable … sitting by designation». ECF υπόλοιπα: CA5 «RESTRICTED», CA9 μορφή «Case: N, date, ID: N, DktEntry: N, Page X of Y» σε παραρτήματα· SCOTUS 12 με σελίδα σύγκρισης εγγράφων («Differences exist between documents») → ερώτηση. |
| R2-1 | Νέα στήλη `author_initials` (υπογραφή / «Opinion by», αλλιώς γραμμή «Before:» αν μοναδικό επώνυμο) | εγώ | ✅ κώδικας 2026-10-13 (test συνθετικά) | Το `parse_author` του καθηγητή δεν αλλάζει. |
| R2-2 | Match με (αρχικά, επώνυμο) — συνωνυμία = ≥2 στο JuDJIS **ή** στο FJC (όσοι υπηρέτησαν στην περίοδο του dataset· όχι ανά ημερομηνία υπόθεσης) σε JuDJIS (`enrich_ideology`) και FJC (`ideology_fallback`, και για visiting π.χ. Friedman). Αμφίσημο → κενό | εγώ | ✅ κώδικας 2026-10-13 (test συνθετικά) | Κάποιες υποθέσεις χάνουν το (λάθος) JuDJIS score. |
| R2-3 | Aliases OCR: IKLUTA/IEUTA→IKUTA, MeKEOWN→McKEOWN, GRAJBER→GRABER, MURGIA→MURGUIA, REAYLEY→REAVLEY | εγώ | ✅ κώδικας 2026-10-13 (test συνθετικά) | Στο `judge_aliases.py`, μόνο στην αντιστοίχιση· το `author_str` μένει ως έχει. |
| R2-4 | `opinion_kind = order` για τις 234 merits χωρίς συγγραφέα που ξεκινούν με ORDER | εγώ | ✅ κώδικας 2026-10-13 (test συνθετικά) | |
| R2-5 | `clean_headers`: υπόλοιπες κεφαλίδες ECF CA5 («Page:1» κ.λπ.) | εγώ | ✅ κώδικας 2026-10-13 (test συνθετικά) | Με βάση τα δείγματα του R2-0. |
| R2-6 | Συνθετικά tests → push → τρέξιμο στο labrat → έλεγχος αριθμών → email + dataset | εγώ + εσύ | 🔄 tests ✅, αναμονή labrat | Στόχοι: Nelson ~79/24, Smith ~245/58, Thomas ~57/11, order 234, ECF υπόλοιπα 0. |

## Q. Ερωτήσεις προς τον καθηγητή (ΔΕΝ υλοποιούνται πριν απαντήσει)

| # | Ερώτηση | Από | Σημειώσεις |
|---|---|---|---|
| Q1 | 88% των υποθέσεων (9.158) είναι μόνο `010combined` → majority + dissents ενωμένα. Να τα χωρίσουμε από το κείμενο (επικεφαλίδες «JUSTICE X, dissenting» / «Y, Circuit Judge, dissenting»); | 2026-10-10 | Δοκιμασμένο: ~1.930 θα χωρίζονταν, ~0,3% πιθανά λάθη. Έτοιμο ως `--text-split` (λεπτά από το dump). |
| Q2 | Πού πάνε οι τύποι που δεν όρισε: `035concurrenceinpart` (120), `070rehearing` (3), `025plurality`/`015unamimous` (0 στα δεδομένα); Και τι κάνουμε με τις 3 υποθέσεις που δεν έχουν ούτε `020lead` ούτε `010combined`; | 2026-10-08 | = A3. Προσωρινά: δεν μπαίνουν πουθενά· οι 3 κράτησαν το παλιό κείμενο. Αλλαγή σε λεπτά με `--from-dump`. |
| Q3 | Αποφάσεις που δεν είναι επί της ουσίας (επείγουσες αιτήσεις SCOTUS «…A…», dissents from denial of cert, απορρίψεις rehearing en banc): κρατούνται ή σημαίνονται/εξαιρούνται; | 2026-10-10 | = A2c. ~16 στο SCOTUS χωρίς SCDB + αρκετές en banc στα circuits. |
| Q4 | Επανεξαγωγή `disposition` από τη νέα majority (A4); Η παλιά βγήκε από το τέλος κειμένου που συχνά ήταν dissent. | 2026-10-10 | Κόστος ~€1–2 (OpenRouter). |
| Q5 | Καθάρισμα κεφαλίδων σελίδας PDF στα CA5/CA9 (A2b); | 2026-10-10 | Θόρυβος στο κείμενο-στόχο. |
| Q7 | A7: «για όλους τους circuit δικαστές» — περιλαμβάνονται και οι **district judges by designation** που γράφουν αποφάσεις εφετείων; (Το JCS δεν τους έχει· το FJC θα έδινε κόμμα.) | 2026-10-11 | Προσωρινά: μόνο δικαστές με διορισμό στο CA5/CA9· οι άλλοι κενοί. |
| Q8 | **author_str λάθος σε ~41% (CA5) / ~46% (CA9)** — συνήθως ο τελευταίος της σύνθεσης («Before»), όχι ο συγγραφέας. Να διορθωθεί η εξαγωγή (CA9 «Opinion by Judge X», byline «X, Circuit Judge:», per curiam → κενό) και να ξανατρέξουν JuDJIS ideology, A7 fallback και splits; | 2026-10-11 | Επηρεάζει τα `ideology`/`ideology_score` των circuits (δεν τα αλλάζουμε χωρίς έγκριση) και το author-disjoint. Η σωστή εξαγωγή λύνει και τα αμφίσημα Smith/Nelson/Thomas («Opinion by Judge M. Smith»). |
| Q9 | A7: να ταυτιστούν οι Richman = Owen, Forrest = Hunsaker, Ramirez = «Carrillo Ramirez» στο JCS (ίδια πρόσωπα, άλλο όνομα); | 2026-10-11 | +~219 υποθέσεις με JCS αντί για κόμμα. |
| Q6 | SCDB: εκτός από `scdb_id`, συμπληρώνουμε από το ίδιο match και `issue_area`, `decision_direction`, ιδεολογία Martin-Quinn; | 2026-10-10 | Έτσι υλοποιήθηκε (θεωρήθηκε μέρος του «βελτίωσης μεταδεδομένων»). Να επιβεβαιωθεί. |

## B. Αιτήματα καθηγητή — προηγούμενη συνάντηση (~2026-10-03)

| # | Task | Ζητήθηκε | Status | Σημειώσεις |
|---|---|---|---|---|
| B1 | Αποστολή dataset για Lawma + πόσα λείπουν εκτός Lawma | ~2026-10-03 | ✅ 2026-10-06 | WeTransfer: `juribench_cases.csv.gz` + `completeness_report.md`. A 10.394 · B 10.071 · D ~7.600. |
| B2 | Τρέξιμο **Lawma** (issue_area circuits) | ~2026-10-03 | 👤 | Ο καθηγητής. Output: `juribench_labeled.csv` + `lawma_validation.csv`. |
| B3 | Πρόταση μοντέλων για fine-tuning (έως ~50B) | ~2026-10-03 | ✅ 2026-10-06 | `docs/models-proposal.md`. Εκκρεμεί η αποστολή (βλ. B5). |
| B4 | Έγγραφο μετρικών αξιολόγησης | ~2026-10-03 | ✅ 2026-10-06 | `docs/evaluation-metrics.md`. Εκκρεμεί η αποστολή (βλ. B5). |
| B5 | Αποστολή B3 + B4 στον καθηγητή | ~2026-10-06 | ✅ 2026-10-08 | Στάλθηκαν· commit+push. |
| B6 | Εκπαίδευση μοντέλων (3–4 × 2 tasks) στο μηχάνημα του καθηγητή | ~2026-10-03 | 👤 | Μετά την οριστικοποίηση του dataset και των μοντέλων. |

## C. Dataset & κώδικας

| # | Task | Ζητήθηκε | Status | Σημειώσεις |
|---|---|---|---|---|
| C1 | Νέο build dataset από bulk data (3 δικαστήρια, 2015–2024) | ~2026-09-29 | ✅ ~2026-10-01 | 10.997 → dedupe 10.395. |
| C2 | LLM enrichment facts/issue/disposition (DeepSeek, parallel) | ~2026-10-01 | ✅ 2026-10-06 | 100% facts, 10.394 issue. Κόστος ~€7. |
| C3 | Διόρθωση JuDJIS matching (`circuit_key`) | ~2026-10-01 | ✅ | 0 → 7.344 matches. |
| C4 | `enrich_scdb_ids.py` (ακριβές SCOTUS↔SCDB μέσω `scdb_id`) | 2026-10-06 | ✅ | ideology SCOTUS 429→528, issue_area 458→559. **Αντικαταστάθηκε** από το `enrich_scdb.py` (A5). |
| C5 | `completeness_report.py` | 2026-10-06 | ✅ | |
| C6 | `lawma_label.py` default input → `juribench_cases.csv` | 2026-10-06 | ✅ | |
| C7 | Μετά το Lawma: `completeness_report` + `make_splits` + `build_finetune` πάνω στο `juribench_labeled.csv` | ~2026-10-06 | ⏳ | Περιμένει B2 (και πιθανώς A1–A8). |
| C8 | Προσθήκη `jellyfish`, `python-dotenv`, `awscli` στο `requirements.txt` | ~2026-10-06 | ✅ 2026-10-10 | jellyfish/python-dotenv υπήρχαν ήδη· προστέθηκε awscli. |
| C9 | Προσαρμογή `train_qlora.py` / `generate.py` για Qwen3.5 / Gemma 4 (πολυτροπική αρχιτεκτονική, `enable_thinking=False`) | 2026-10-06 | ⏳ | Όταν κλειδώσει η λίστα μοντέλων. |
| C10 | Prune περιττών στηλών (`court`, `judge_id`, `author_cl_id`, `syllabus`, σταθερά `*_source`) | ~2026-10-03 | 💤 | Εκκρεμεί απόφαση χρήστη. |
| C11 | Ενημέρωση `docs/components.md` με τα νέα scripts | ~2026-10-06 | ✅ 2026-10-10 | bulk_filter, split_opinions, inspect_split, enrich_scdb, enrich_scdb_ids, completeness_report. |
| C14 | Μεταφορά από Cowork σε **Claude Code** (το CLAUDE.md φορτώνεται αυτόματα) | 2026-10-10 | 🔄 | CLAUDE.md ανανεώθηκε με ενότητα «Ξεκίνα από εδώ». |
| C12 | Διόρθωση διατύπωσης διάγνωσης στο `completeness_report` («χωρίς match» = και χωρίς scdb_id) | 2026-10-06 | ⏳ | Μικρό. |
| C13 | Revoke εκτεθειμένου OpenRouter key + αφαίρεση hardcoded default | ~2026-09-11 | 💤 | Ο χρήστης επέλεξε να το αφήσει προς το παρόν. Repo public. |

## D. Αξιολόγηση (υλοποίηση μετρικών)

| # | Task | Ζητήθηκε | Status | Σημειώσεις |
|---|---|---|---|---|
| D1 | PPL, Distinct-n, Self-BLEU, MoverScore, GRUEN στο `evaluate.py` | ~2026-09-11 | ⏳ | Από ParliaBench. |
| D2 | Weighted-F1, F1 ανά κλάση, confusion, 3-class, baselines (majority / base) | 2026-10-06 | ⏳ | |
| D3 | Citation density | 2026-10-06 | ⏳ | |
| D4 | Νέες μετρικές Court-Style Alignment + Ideology Alignment | ~2026-09-11 | ⏳ | Τύποι στο `docs/evaluation-metrics.md`. |
| D5 | Ρουμπρίκα κριτή IRAC / αναλυτική + J_Qual + pairwise Turing-style | ~2026-09-11 | ⏳ | |
| D6 | Cross-Context Stability + στατιστικοί έλεγχοι | 2026-10-06 | ⏳ | |
| D7 | Ανθρώπινη επικύρωση κριτή (~50 κείμενα) | 2026-10-06 | ⏳ | |
| D8 | `eval_ideology.py` | — | 💤 | Παρκαρισμένο με απόφαση χρήστη. |

## E. Συγγραφή

| # | Task | Ζητήθηκε | Status | Σημειώσεις |
|---|---|---|---|---|
| E1 | Κεφ. 2 — Βιβλιογραφία (LLMs & νομικά, SaulLM, LoRA/QLoRA, ParliaBench, LegalBench, argument mining) | ~2026-09-11 | ⏳ | Μπορεί να γίνει τώρα. |
| E2 | Κεφ. 3 — Συλλογή/προετοιμασία dataset (πίνακας πεδίων, completeness, αιτιολόγηση μεγέθους, επαναπλαισίωση scope) | ~2026-10-06 | ⏳ | Υλικό στο CLAUDE.md / docs. Μετά το A1, για να περιγράφει το τελικό σχήμα. |
| E3 | Κεφ. 4–7 | — | ⏳ | Μετά τα runs. |

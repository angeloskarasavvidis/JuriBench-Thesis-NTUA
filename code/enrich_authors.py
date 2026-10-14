#!/usr/bin/env python3
"""
enrich_authors.py
------------------
Stage 1 of ideology enrichment: author_str (+ author_source) for circuit rows (CA5/CA9),
parsed from opinion_text.

2026-10-12: η παλιά parse_author() έπαιρνε το 1ο «Επώνυμο, Circuit Judge» στα πρώτα 2000 chars
→ συχνά τον ΤΕΛΕΥΤΑΙΟ της σύνθεσης («Before A, B, and C, Circuit Judges»). Αντικαταστάθηκε
(οδηγία καθηγητή) από τη parse_author() του `parse_author.py` (καθηγητής), η οποία αφαιρεί πρώτα
τη γραμμή της σύνθεσης και επιστρέφει (surname, source):
  source = signature  (byline «COSTA, Circuit Judge:»)
         | opinion_by (CA9 «Opinion by Judge X»)
         | none       (unsigned: per curiam / memorandum / order)

Ξαναϋπολογίζει ΟΛΕΣ τις circuit γραμμές (όχι μόνο τις κενές). SCOTUS: ανέγγιχτο (η ιδεολογία
του SCOTUS έρχεται από SCDB majOpinWriter).

Adds/overwrites columns: author_str, author_source, author_initials, author_cl_id (κενό — δεν υπάρχει People FK).
2026-10-13 (οδηγία καθηγητή): `author_initials` (π.χ. M. / N.R. / R.D.) από την υπογραφή, το «Opinion by»
ή τη γραμμή «Before:» / «The Honorable … sitting by designation» (`author_initials.py`) — για συνωνυμίες.
2026-10-14 (οδηγία καθηγητή): στο ΤΕΛΟΣ εφαρμόζεται το `data/author_overrides.csv` (συμπληρωμένο με το χέρι:
cluster_id, author_str, author_initials, note) → αντικαθιστά author_str / author_initials και βάζει
author_source = manual. Έτσι οι αλλαγές δεν χάνονται στο επόμενο τρέξιμο του pipeline.

Usage:
  python code/enrich_authors.py                       # in-place στο data/juribench_dataset.csv
  python code/enrich_authors.py --input X --output Y
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse_author import parse_author  # noqa: E402  (αρχείο του καθηγητή, αμετάβλητο)
from author_initials import author_initials  # noqa: E402

csv.field_size_limit(sys.maxsize)

NEW_COLS = ["author_str", "author_source", "author_initials", "author_cl_id"]
CIRCUITS = ("CA5", "CA9")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root        = Path(__file__).parent.parent
    data_dir    = root / "data"
    input_path  = Path(args.input)  if args.input  else data_dir / "juribench_dataset.csv"
    output_path = Path(args.output) if args.output else input_path

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)
    for row in rows:
        for c in NEW_COLS:
            row.setdefault(c, "")

    print(f"Input : {input_path}")
    print(f"Loaded: {len(rows)} rows")

    src = {j: Counter() for j in CIRCUITS}
    ini_src = {j: Counter() for j in CIRCUITS}
    for row in rows:
        j = row.get("jurisdiction")
        if j not in CIRCUITS:
            continue
        surname, source = parse_author(row.get("opinion_text"))
        row["author_str"], row["author_source"], row["author_cl_id"] = surname, source, ""
        ini, isrc = author_initials(row.get("opinion_text"), surname, source)
        row["author_initials"] = ini
        src[j][source] += 1
        if surname:
            ini_src[j][isrc or "χωρίς αρχικά"] += 1

    # --- χειροκίνητες διορθώσεις (data/author_overrides.csv) ---
    ov_path = data_dir / "author_overrides.csv"
    if ov_path.exists():
        with open(ov_path, encoding="utf-8") as f:
            overrides = {r["cluster_id"].strip(): r for r in csv.DictReader(f) if (r.get("cluster_id") or "").strip()}
        by_id = {row.get("cluster_id"): row for row in rows if row.get("jurisdiction") in CIRCUITS}
        applied = missing = 0
        for cid, ov in overrides.items():
            row = by_id.get(cid)
            if row is None:
                missing += 1
                continue
            row["author_str"] = (ov.get("author_str") or "").strip()
            row["author_initials"] = (ov.get("author_initials") or "").strip()
            row["author_source"] = "manual"
            applied += 1
        print(f"\nOverrides ({ov_path.name}): {len(overrides)} γραμμές · εφαρμόστηκαν {applied} · "
              f"δεν βρέθηκαν στο dataset {missing} · με συγγραφέα "
              f"{sum(1 for o in overrides.values() if (o.get('author_str') or '').strip())}")
    else:
        print(f"\n(δεν υπάρχει {ov_path} — καμία χειροκίνητη διόρθωση)")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved -> {output_path}")
    for j in CIRCUITS:
        n = sum(src[j].values())
        print(f"  {j}: {n} rows · " + " · ".join(f"{k} {v}" for k, v in sorted(src[j].items())))
        print(f"      author_initials: " + " · ".join(f"{k} {v}" for k, v in sorted(ini_src[j].items())))


if __name__ == "__main__":
    main()

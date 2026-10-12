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

Adds/overwrites columns: author_str, author_source, author_cl_id (κενό — δεν υπάρχει People FK).

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

csv.field_size_limit(sys.maxsize)

NEW_COLS = ["author_str", "author_source", "author_cl_id"]
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
    for row in rows:
        j = row.get("jurisdiction")
        if j not in CIRCUITS:
            continue
        surname, source = parse_author(row.get("opinion_text"))
        row["author_str"], row["author_source"], row["author_cl_id"] = surname, source, ""
        src[j][source] += 1

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved -> {output_path}")
    for j in CIRCUITS:
        n = sum(src[j].values())
        print(f"  {j}: {n} rows · " + " · ".join(f"{k} {v}" for k, v in sorted(src[j].items())))


if __name__ == "__main__":
    main()

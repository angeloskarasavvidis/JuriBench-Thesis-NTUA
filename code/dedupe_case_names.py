#!/usr/bin/env python3
"""
dedupe_case_names.py
---------------------
Collapses CourtListener "Revisions:" reissue duplicates (same case
republished as a new cluster after a corrected slip opinion) plus any
other same-case duplicates in the collected corpus.

Key: (jurisdiction, normalized case_name with "Revisions:.*" suffix
stripped, date_filed). Keeps the first row per key (original file
order), drops the rest.

Usage:
  python dedupe_case_names.py                       # in-place on data/juribench_dataset.csv
  python dedupe_case_names.py --input X --output Y
"""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def norm_name(name):
    name = re.sub(r"\s+Revisions?:.*$", "", name or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    input_path  = Path(args.input)  if args.input  else root / "data" / "juribench_dataset.csv"
    output_path = Path(args.output) if args.output else input_path

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    print(f"Input : {input_path}")
    print(f"Loaded: {len(rows)} rows")

    seen = set()
    kept, dropped = [], []
    for row in rows:
        key = (row.get("jurisdiction"), norm_name(row.get("case_name")), row.get("date_filed"))
        if key in seen:
            dropped.append(row)
            continue
        seen.add(key)
        kept.append(row)

    by_juris = Counter(r.get("jurisdiction") for r in dropped)
    print(f"\nDropped {len(dropped)} duplicate rows: {dict(by_juris)}")
    for j in ("SCOTUS", "CA5", "CA9"):
        before = sum(1 for r in rows if r.get("jurisdiction") == j)
        after  = sum(1 for r in kept if r.get("jurisdiction") == j)
        print(f"  {j}: {before} -> {after}")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)

    print(f"\nSaved -> {output_path}")
    print(f"  total: {len(rows)} -> {len(kept)} rows")


if __name__ == "__main__":
    main()

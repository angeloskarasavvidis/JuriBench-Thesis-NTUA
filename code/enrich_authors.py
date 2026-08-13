#!/usr/bin/env python3
"""
enrich_authors.py
------------------
Stage 1 of ideology enrichment. Backfills author_str for circuit rows by
parsing the authoring judge's surname directly out of opinion_text.

Originally this fetched author_str from CourtListener's per-cluster API
(sub_opinions[].author_str / .author). That premise turned out to be false
for circuits: a live fetch of a CA5 cluster returned author_str="",
author (People FK)=None, and cluster judges="" — CourtListener carries no
structured author for circuit opinions in this 2020-2024 window. So this
stage is now a local, offline text parse instead: no network, no API token.

SCOTUS rows are left untouched here — the SCOTUS ideology path (Stage 2)
matches via SCDB majOpinWriter, not author_str, so there is nothing to
parse for SCOTUS.

Adds two columns to data/juribench_dataset.csv: author_str, author_cl_id.
author_cl_id stays empty (no People FK available from a text parse).
Resumable: rerun picks up rows not yet enriched (author_str column empty).

Usage:
  python enrich_authors.py                       # in-place enrich data/juribench_dataset.csv
  python enrich_authors.py --input X --output Y  # explicit paths
"""

import argparse
import csv
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

NEW_COLS = ["author_str", "author_cl_id"]

# Matches the opinion-head byline, e.g. "OLDHAM, Circuit Judge:" or
# "Elrod, Chief Judge, delivered the opinion of the court."
AUTHOR_PAT = re.compile(
    r"\b([A-Z][a-zA-Z]+),\s+(?:Circuit\s+Judge|Chief\s+Judge)", re.IGNORECASE
)
HEAD_CHARS = 2000


def parse_author(opinion_text):
    """Return the authoring judge's surname parsed from the opinion head, or ''."""
    if not opinion_text:
        return ""
    m = AUTHOR_PAT.search(opinion_text[:HEAD_CHARS])
    return m.group(1) if m else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root       = Path(__file__).parent.parent
    data_dir   = root / "data"
    input_path  = Path(args.input)  if args.input  else data_dir / "juribench_dataset.csv"
    output_path = Path(args.output) if args.output else input_path

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)
        for row in rows:
            row.setdefault(c, "")

    print(f"Input : {input_path}")
    print(f"Loaded: {len(rows)} rows")

    todo = [r for r in rows if not (r.get("author_str") or "").strip()]
    print(f"To enrich: {len(todo)} rows (already have author_str: {len(rows)-len(todo)})")

    parsed = 0
    for row in todo:
        if row.get("jurisdiction") not in ("CA5", "CA9"):
            continue  # SCOTUS: nothing to parse, ideology uses SCDB instead
        author_str = parse_author(row.get("opinion_text"))
        row["author_str"]   = author_str
        row["author_cl_id"] = ""
        if author_str:
            parsed += 1

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    have = sum(1 for r in rows if (r.get("author_str") or "").strip())
    print(f"\nParsed {parsed} new circuit author_str values from opinion_text")
    print(f"Saved -> {output_path}")
    print(f"  author_str coverage: {have}/{len(rows)} ({have/len(rows):.1%})")


if __name__ == "__main__":
    main()

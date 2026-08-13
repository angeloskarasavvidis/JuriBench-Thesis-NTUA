#!/usr/bin/env python3
"""
make_splits.py
--------------
Χτίζει train/val/test splits από το enriched dataset (data/juribench_cases.csv),
σε ΚΑΝΟΝΙΚΗ / method-agnostic μορφή JSONL. ΔΕΝ κάνει model-specific formatting —
αυτό μπαίνει αργότερα σε ξεχωριστό formatter, ανάλογα με base model / LoRA / QLoRA.

Εγγυήσεις:
  • AUTHOR-DISJOINT: ίδιος συγγραφέας δικαστής ΔΕΝ εμφανίζεται σε train ΚΑΙ test/val.
    (SCOTUS: judge_name/justice · circuits: author_str surname · αν λείπει -> singleton group)
  • COURT-STRATIFIED: οι αναλογίες train/val/test κρατιούνται ανά court (SCOTUS/CA5/CA9).
  • Ντετερμινιστικό (seed).

Κάθε γραμμή JSONL:
  id, split, jurisdiction, court, case_name, date_filed, author_key,
  input{facts, issue_text, court},
  targets{opinion_text[, opinion_text_capped], disposition, prevailing_party},
  eval_meta{ideology, ideology_score, ideology_source, issue_area, issue_area_source, decision_direction},
  outcome_usable  (disposition ∉ {unclear})

Υποστηρίζει δύο task variants downstream (χωρίς αλλαγή του split):
  • generation  : input -> opinion_text (+ έκβαση)
  • predict_only: input(facts+issue) -> disposition   (LJP benchmark· χωρίς opinion στο input)

Usage:
  python make_splits.py
  python make_splits.py --test 0.15 --val 0.15 --seed 42
  python make_splits.py --max-target-chars 12000   # προαιρετικό cap (granularity αργότερα)
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def author_key(row):
    jur = row.get("jurisdiction", "")
    if jur == "SCOTUS":
        nm = (row.get("judge_name") or "").strip().lower()
        return f"scotus::{nm}" if nm else f"scotus::_unknown_{row.get('cluster_id')}"
    # circuits: ο συγγραφέας (author_str), όχι όλο το panel
    a = (row.get("author_str") or "").strip().lower()
    return f"{jur.lower()}::{a}" if a else f"{jur.lower()}::_unknown_{row.get('cluster_id')}"


def split_one_court(rows, test_frac, val_frac, seed):
    """Group-disjoint split μέσα σε ένα court. Επιστρέφει dict split->list[row]."""
    groups = defaultdict(list)
    for r in rows:
        groups[r["_author_key"]].append(r)
    keys = list(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(keys)

    n = len(rows)
    n_test, n_val = int(round(n * test_frac)), int(round(n * val_frac))
    out = {"test": [], "val": [], "train": []}
    # γέμισε test, μετά val, μετά train — ακέραια groups (author-disjoint)
    for k in keys:
        g = groups[k]
        if len(out["test"]) + len(g) <= n_test:
            out["test"] += g
        elif len(out["val"]) + len(g) <= n_val:
            out["val"] += g
        else:
            out["train"] += g
    return out


def build_record(r, split, max_chars):
    opinion = r.get("opinion_text") or ""
    targets = {
        "opinion_text": opinion,
        "disposition": r.get("disposition", ""),
        "prevailing_party": r.get("prevailing_party", ""),
    }
    if max_chars and len(opinion) > max_chars:
        targets["opinion_text_capped"] = opinion[:max_chars]
    return {
        "id": r.get("cluster_id", ""),
        "split": split,
        "jurisdiction": r.get("jurisdiction", ""),
        "court": r.get("court", ""),
        "case_name": r.get("case_name", ""),
        "date_filed": r.get("date_filed", ""),
        "author_key": r["_author_key"],
        "input": {
            "facts": r.get("facts", ""),
            "issue_text": r.get("issue_text", ""),
            "court": r.get("jurisdiction", ""),
        },
        "targets": targets,
        "eval_meta": {
            "ideology": r.get("ideology", ""),
            "ideology_score": r.get("ideology_score", ""),
            "ideology_source": r.get("ideology_source", ""),
            "issue_area": r.get("issue_area", ""),
            "issue_area_source": r.get("issue_area_source", ""),
            "decision_direction": r.get("decision_direction", ""),
        },
        "outcome_usable": (r.get("disposition", "").strip().lower() not in ("", "unclear")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--test", type=float, default=0.15)
    ap.add_argument("--val",  type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-target-chars", type=int, default=0,
                    help="προαιρετικό cap μήκους target (granularity αποφασίζεται αργότερα)")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    data = root / "data"
    input_path = Path(args.input) if args.input else data / "juribench_cases.csv"
    outdir = Path(args.outdir) if args.outdir else data / "splits"
    outdir.mkdir(parents=True, exist_ok=True)

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # μόνο αξιοποιήσιμες γραμμές: πρέπει να έχουν facts + issue_text + opinion_text
    usable = [r for r in rows
              if (r.get("facts") or "").strip()
              and (r.get("issue_text") or "").strip()
              and (r.get("opinion_text") or "").strip()]
    for r in usable:
        r["_author_key"] = author_key(r)

    print(f"Input : {input_path}")
    print(f"Loaded: {len(rows)} | usable (facts+issue+opinion): {len(usable)}")

    # split ανά court (stratified), author-disjoint μέσα σε κάθε court
    by_court = defaultdict(list)
    for r in usable:
        by_court[r["jurisdiction"]].append(r)

    assigned = {"train": [], "val": [], "test": []}
    for court, crows in sorted(by_court.items()):
        parts = split_one_court(crows, args.test, args.val, args.seed)
        for s in assigned:
            assigned[s] += parts[s]
        print(f"  {court}: {len(crows)} -> train {len(parts['train'])}, "
              f"val {len(parts['val'])}, test {len(parts['test'])}")

    # γράψε JSONL
    for s in ("train", "val", "test"):
        with open(outdir / f"{s}.jsonl", "w", encoding="utf-8") as f:
            for r in assigned[s]:
                f.write(json.dumps(build_record(r, s, args.max_target_chars), ensure_ascii=False) + "\n")

    # ── report + έλεγχοι ──────────────────────────────────────────
    print("\n== Split sizes ==")
    tot = sum(len(assigned[s]) for s in assigned)
    for s in ("train", "val", "test"):
        print(f"  {s:5}: {len(assigned[s]):5} ({len(assigned[s])/tot:.1%})")

    # author-disjoint assertion
    keysets = {s: {r["_author_key"] for r in assigned[s]} for s in assigned}
    overlap = (keysets["train"] & keysets["test"]) | (keysets["train"] & keysets["val"]) | (keysets["val"] & keysets["test"])
    # αγνόησε singleton _unknown_ (μοναδικά ανά υπόθεση, δεν σπάνε disjointness ουσιαστικά)
    real_overlap = {k for k in overlap if "_unknown_" not in k}
    print(f"\nAuthor-disjoint check: {len(real_overlap)} πραγματικοί συγγραφείς σε >1 split "
          f"({'OK' if not real_overlap else 'PROBLEM: '+', '.join(list(real_overlap)[:5])})")

    print("\n== Court ανά split ==")
    for s in ("train", "val", "test"):
        print(f"  {s:5}: {dict(Counter(r['jurisdiction'] for r in assigned[s]))}")

    print("\n== Ideology (eval-only) ανά split ==")
    for s in ("train", "val", "test"):
        c = Counter((r.get("ideology") or "∅") for r in assigned[s])
        print(f"  {s:5}: {dict(c)}")

    print("\n== Disposition ανά split ==")
    for s in ("train", "val", "test"):
        c = Counter(r.get("disposition", "") for r in assigned[s])
        print(f"  {s:5}: {dict(c)}")

    print(f"\nSaved -> {outdir}/train.jsonl, val.jsonl, test.jsonl")


if __name__ == "__main__":
    main()

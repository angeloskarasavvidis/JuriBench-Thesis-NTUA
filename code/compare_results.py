#!/usr/bin/env python3
"""
compare_results.py  — Στάδιο 5
------------------------------
Διαβάζει όλα τα results/*.json (έξοδοι του evaluate.py) και βγάζει έναν
συγκριτικό πίνακα των μοντέλων/tasks. Έξοδος: εκτύπωση + results/summary.csv.

Usage:
  python code/compare_results.py
  python code/compare_results.py --dir results --out results/summary.csv
"""
import argparse, csv, json
from pathlib import Path


def flatten(r, name):
    o = r.get("outcome", {})
    disc = r.get("discourse", {})
    g = disc.get("generated", {}) or {}
    a = disc.get("authentic", {}) or {}
    cit = r.get("citation_hallucination", {}) or {}
    return {
        "name": name,
        "task": r.get("task", ""),
        "n": r.get("n", ""),
        "accuracy": o.get("accuracy", ""),
        "macro_f1": o.get("macro_f1", ""),
        "bertscore_f1": r.get("bertscore_f1", ""),
        "gen_words": g.get("words", ""),
        "auth_words": a.get("words", ""),
        "gen_fk": g.get("flesch_kincaid", ""),
        "auth_fk": a.get("flesch_kincaid", ""),
        "gen_ttr": g.get("ttr", ""),
        "auth_ttr": a.get("ttr", ""),
        "halluc_rate": cit.get("hallucination_rate", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results")
    ap.add_argument("--out", default="results/summary.csv")
    args = ap.parse_args()

    files = sorted(Path(args.dir).glob("*.json"))
    rows = []
    for f in files:
        if f.name == "summary.json":
            continue
        try:
            rows.append(flatten(json.load(open(f, encoding="utf-8")), f.stem))
        except Exception as e:
            print(f"  skip {f.name}: {e}")

    if not rows:
        print(f"Δεν βρέθηκαν results/*.json στο {args.dir}."); return

    cols = list(rows[0].keys())
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)

    # εκτύπωση πίνακα
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    line = " | ".join(c.ljust(widths[c]) for c in cols)
    print(line); print("-" * len(line))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))
    print(f"\n✓ summary -> {args.out}")


if __name__ == "__main__":
    main()

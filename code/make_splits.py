#!/usr/bin/env python3
"""
make_splits.py
--------------
Χτίζει train/val/test splits από το enriched dataset (data/juribench_cases.csv),
σε ΚΑΝΟΝΙΚΗ / method-agnostic μορφή JSONL. ΔΕΝ κάνει model-specific formatting —
αυτό μπαίνει αργότερα σε ξεχωριστό formatter, ανάλογα με base model / LoRA / QLoRA.

Εγγυήσεις:
  • STRATIFIED: δικαστήριο × έκβαση (disposition σε 5 ομάδες, βλ. DISP_GROUP) — κάθε σύνολο έχει
    περίπου τις ίδιες αναλογίες με όλο το dataset.
  • AUTHOR-DISJOINT (circuits): ίδιος συγγραφέας δικαστής ΔΕΝ εμφανίζεται σε train ΚΑΙ test/val
    (author_str· αν λείπει -> μόνη της η υπόθεση). Μαζί με το stratification μέσω greedy αλγορίθμου
    (stratified_group_split): μοιράζει ολόκληρους δικαστές ώστε οι αναλογίες να βγαίνουν όσο γίνεται ίδιες.
  • SCOTUS: χωρίς author-disjoint (9 δικαστές· το judge_name του CourtListener είναι συχνά όλη η σύνθεση)
    -> κάθε υπόθεση μόνη της.
  • Ντετερμινιστικό (seed). Οι γραμμές κάθε αρχείου ανακατεύονται (όχι ταξινόμηση ανά δικαστήριο).
  • Στο τέλος: πίνακες αναλογιών ανά σύνολο (δικαστήριο, έκβαση, issue_area, έτος, ιδεολογία).

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
  python make_splits.py --input juribench_labeled.dedup.csv          # 80-10-10, seed 42
  python make_splits.py --test 0.10 --val 0.15 --seed 42
  python make_splits.py --max-target-chars 12000   # προαιρετικό cap (granularity αργότερα)
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter
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


# έκβαση σε 5 ομάδες για το stratification (οι 11 ετικέτες έχουν πολύ μικρές κατηγορίες)
DISP_GROUP = {
    "affirmed": "affirmed",
    "reversed": "reversed", "vacated": "reversed", "remanded": "reversed",
    "mixed": "mixed", "affirmed_in_part": "mixed",
    "denied": "procedural", "dismissed": "procedural", "granted": "procedural",
}


def disp_group(row):
    return DISP_GROUP.get((row.get("disposition") or "").strip().lower(), "other")


def group_key(row):
    """Μονάδα που μένει ολόκληρη σε ένα σύνολο: ο δικαστής (circuits) ή η υπόθεση (SCOTUS)."""
    if row.get("jurisdiction") == "SCOTUS":
        return f"scotus::case_{row.get('cluster_id')}"
    return row["_author_key"]


def stratified_group_split(rows, test_frac, val_frac, seed):
    """Greedy stratified group split.
    Οι ομάδες (δικαστές) μπαίνουν από τη μεγαλύτερη στη μικρότερη· κάθε μία πάει στο σύνολο όπου
    φέρνει τα πλήθη ανά (δικαστήριο × έκβαση) πιο κοντά στον στόχο (ελάχιστο τετραγωνικό σφάλμα).
    Το StratifiedGroupKFold δοκιμάστηκε και απέτυχε: δικαστές με 200–370 υποθέσεις ξεπερνούν το μέγεθος
    ενός fold και τα σύνολα έβγαιναν 84/12/4 με άνισα δικαστήρια."""
    frac = {"train": 1 - test_frac - val_frac, "val": val_frac, "test": test_frac}
    if min(frac.values()) <= 0:
        raise SystemExit("--test και --val πρέπει να είναι > 0 και μαζί < 1")
    label = lambda r: f"{r['jurisdiction']}|{disp_group(r)}"
    groups = {}
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)
    total = Counter(label(r) for r in rows)
    target = {sp: {l: f * n for l, n in total.items()} for sp, f in frac.items()}
    have = {sp: Counter() for sp in frac}
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    keys.sort(key=lambda k: len(groups[k]), reverse=True)   # stable: ίσα μεγέθη μένουν τυχαία
    out = {sp: [] for sp in frac}
    for k in keys:
        g = Counter(label(r) for r in groups[k])
        # αύξηση σφάλματος αν η ομάδα μπει στο sp: Σ g·(2·(έχει − στόχος) + g)
        cost = {sp: sum(c * (2 * (have[sp][l] - target[sp][l]) + c) for l, c in g.items()) for sp in frac}
        best = min(("test", "val", "train"), key=lambda sp: cost[sp])
        have[best].update(g)
        out[best] += groups[k]
    rng = random.Random(seed)
    for sp in out:
        rng.shuffle(out[sp])
    return out


def issue_group(row):
    v = (row.get("issue_area") or "").split(".")[0]
    return {"1": "1 criminal", "2": "2 civil_rights", "8": "8 economic"}.get(v, "other" if v else "∅")


def print_table(title, assigned, keyfn):
    """Ποσοστά ανά σύνολο για κάθε τιμή — για έλεγχο ισορροπίας."""
    counts = {s: Counter(keyfn(r) for r in assigned[s]) for s in assigned}
    keys = sorted(set().union(*counts.values()))
    print(f"\n== {title} (% ανά σύνολο) ==")
    print(f"  {'':18}" + "".join(f"{s:>8}" for s in ("train", "val", "test")))
    for k in keys:
        cells = "".join(f"{100*counts[s][k]/max(len(assigned[s]),1):7.1f}%" for s in ("train", "val", "test"))
        print(f"  {str(k)[:18]:18}{cells}")


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
    ap.add_argument("--test", type=float, default=0.10)
    ap.add_argument("--val",  type=float, default=0.10)
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

    assigned = stratified_group_split(usable, args.test, args.val, args.seed)

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

    # author-disjoint έλεγχος (μόνο circuits· οι _unknown_ είναι μία υπόθεση η καθεμία)
    keysets = {sp: {group_key(r) for r in assigned[sp] if r["jurisdiction"] != "SCOTUS"} for sp in assigned}
    overlap = (keysets["train"] & keysets["test"]) | (keysets["train"] & keysets["val"]) | (keysets["val"] & keysets["test"])
    print(f"\nAuthor-disjoint (circuits): {len(overlap)} συγγραφείς σε >1 σύνολο "
          f"({'OK' if not overlap else 'PROBLEM: ' + ', '.join(sorted(overlap)[:5])})")

    print_table("Δικαστήριο", assigned, lambda r: r["jurisdiction"])
    print_table("Δικαστήριο × έκβαση", assigned, lambda r: f"{r['jurisdiction']} {disp_group(r)}")
    print_table("Issue area", assigned, issue_group)
    print_table("Έτος", assigned, lambda r: (r.get("date_filed") or "")[:4])
    print_table("Ιδεολογία (eval-only)", assigned, lambda r: r.get("ideology") or "∅")

    print(f"\nSaved -> {outdir}/train.jsonl, val.jsonl, test.jsonl")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
inspect_split.py — Έλεγχος ποιότητας του διαχωρισμού γνωμών (split_opinions.py)
-----------------------------------------------------------------------------
1. ΠΙΘΑΝΑ ΧΑΜΕΝΑ: γραμμές split_method=none (combined) που περιέχουν κάτι που μοιάζει
   με επικεφαλίδα ξεχωριστής γνώμης («… Judge …, dissenting», «Justice …, concurring»),
   εκτός παραπομπών σε παρένθεση «(Smith, J., dissenting)». Δείχνει πλήθος + δείγματα.
2. ΔΕΙΓΜΑΤΑ ΚΟΨΙΜΑΤΩΝ: τυχαίες γραμμές text_regex — τέλος της majority και αρχή κάθε
   dissent/concurrence, για να κριθεί με το μάτι αν το σημείο κοπής είναι σωστό.

Usage:
  python code/inspect_split.py               # 12 δείγματα ανά ενότητα
  python code/inspect_split.py --n 25 --out data/inspect_split.md
"""
import argparse
import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)

LOOSE = re.compile(r"(?:Judges?|JUSTICE|Justice)\b[^.:;()]{0,120}?,\s*(dissenting|concurring)\b")
PAREN = re.compile(r"\([^()]{0,80},\s*J+\.,\s*(?:dissenting|concurring)[^()]*\)")


def snippet(t, a, b):
    return re.sub(r"\s+", " ", t[max(0, a):b]).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    root = Path(__file__).parent.parent
    path = Path(args.input) if args.input else root / "data" / "juribench_cases.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    rng = random.Random(args.seed)
    L = [f"# Έλεγχος διαχωρισμού — `{path.name}`", ""]

    # 1. πιθανά χαμένα
    none_rows = [r for r in rows if r.get("split_method") == "none" and r.get("combined_only") == "1"]
    suspects = []
    for r in none_rows:
        t = PAREN.sub(" ", r.get("opinion_text", ""))
        for m in LOOSE.finditer(t):
            if m.start() > 0.15 * len(t):
                suspects.append((r, t, m)); break
    by = Counter(r.get("jurisdiction") for r, _, _ in suspects)
    L += ["## 1. Πιθανά χαμένα (combined→none με ύποπτη επικεφαλίδα)", "",
          f"**{len(suspects)} από {len(none_rows)}** · ανά δικαστήριο: {dict(by)}", ""]
    for r, t, m in rng.sample(suspects, min(args.n, len(suspects))):
        L.append(f"- **{r.get('jurisdiction')}** · {r.get('case_name','')[:60]} · θέση {m.start()/len(t):.0%}  \n"
                 f"  `…{snippet(t, m.start()-120, m.end()+80)}…`")
    L.append("")

    # 2. δείγματα κοψίματος
    split_rows = [r for r in rows if r.get("split_method") == "text_regex"]
    L += ["## 2. Δείγματα κοψίματος (text_regex)", "", f"Σύνολο text_regex: {len(split_rows)}", ""]
    for r in rng.sample(split_rows, min(args.n, len(split_rows))):
        maj = r.get("opinion_text", "")
        L.append(f"### {r.get('jurisdiction')} · {r.get('case_name','')[:70]}")
        L.append(f"- **Τέλος majority** ({len(maj.split())} λέξεις): `…{snippet(maj, len(maj)-220, len(maj))}`")
        for col, lab in (("dissent_text", "Dissent"), ("concurrence_text", "Concurrence")):
            parts = [p for p in (r.get(col) or "").split("\n\n") if p.strip()]
            for p in parts:
                L.append(f"- **{lab}** ({len(p.split())} λέξεις): `{snippet(p, 0, 160)}…`")
        L.append("")

    text = "\n".join(L)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n[αποθηκεύτηκε → {args.out}]")


if __name__ == "__main__":
    main()

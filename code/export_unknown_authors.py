#!/usr/bin/env python3
"""
export_unknown_authors.py — ΜΟΝΟ ΑΝΑΓΝΩΣΗ (οδηγία καθηγητή 2026-10-14, σημείο ε).
Βγάζει τις circuit υποθέσεις opinion_kind == merits & author_source == none (≈155) σε ένα .md,
για να συμπληρωθεί με το χέρι το data/author_overrides.csv. Για κάθε υπόθεση: cluster_id, όνομα,
ημερομηνία, judge_name (CourtListener), αρχή κειμένου (1.500 χαρ.) και αποσπάσματα γύρω από
«Circuit/District Judge», «Opinion by», «PER CURIAM», «joined by» στους πρώτους 30.000 χαρ.

Usage:  python code/export_unknown_authors.py > data/unknown_authors_export.md
"""
import csv
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
INP = Path(__file__).parent.parent / "data" / "juribench_cases.csv"
CUE = re.compile(r"(?:Circuit|District|Chief|Senior)\s+Judges?\b|Opinion\s+by|PER\s+CURIAM|joined\s+by|"
                 r"Special\s+Concurrence|delivered", re.I)


def ws(t):
    return re.sub(r"\s+", " ", t or "")


def main():
    n = 0
    print("# Circuit merits χωρίς συγγραφέα — για συμπλήρωση με το χέρι\n")
    for r in csv.DictReader(open(INP, encoding="utf-8")):
        if r.get("jurisdiction") not in ("CA5", "CA9") or r.get("opinion_kind") != "merits" \
                or r.get("author_source") != "none":
            continue
        n += 1
        t = ws((r.get("opinion_text") or "")[:30000])
        print(f"## {n}. {r['cluster_id']} · {r['jurisdiction']} · {r.get('date_filed')} · {r.get('case_name', '')[:80]}")
        print(f"judge_name (CL): `{r.get('judge_name', '')}`\n")
        print(f"HEAD: `{t[:1500]}`\n")
        cues, last = [], -1000
        for m in CUE.finditer(t):
            if m.start() < 1500 or m.start() - last < 300:
                continue
            last = m.start()
            cues.append(t[max(0, m.start() - 150):m.end() + 120])
            if len(cues) >= 6:
                break
        for c in cues:
            print(f"- `…{c}…`")
        print()
    print(f"\n**Σύνολο: {n}**")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
export_ids_context.py — ΜΟΝΟ ΑΝΑΓΝΩΣΗ. Για συγκεκριμένα cluster_id τυπώνει αποσπάσματα γύρω από
«Circuit/District Judge», «Opinion by», «joined by», «PER CURIAM» (πρώτοι 60.000 χαρ.), για να
συμπληρωθεί με το χέρι το data/author_overrides.csv.

Usage:  python code/export_ids_context.py ID1 ID2 ... > data/ids_context.md
"""
import csv
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
INP = Path(__file__).parent.parent / "data" / "juribench_cases.csv"
CUE = re.compile(r"(?:Circuit|District|Chief|Senior)\s+Judges?\b\s*[,:;]|Opinion\s+by|joined\s+by|PER\s+CURIAM(?!\))|"
                 r"with\s+whom", re.I)
ids = set(sys.argv[1:])
for r in csv.DictReader(open(INP, encoding="utf-8")):
    if r.get("cluster_id") not in ids:
        continue
    t = re.sub(r"\s+", " ", (r.get("opinion_text") or "")[:60000])
    print(f"## {r['cluster_id']} · {r['jurisdiction']} · {r.get('date_filed')} · {r.get('case_name', '')[:80]}\n")
    print(f"START: `{t[:600]}`\n")
    last, n = -1000, 0
    for m in CUE.finditer(t):
        if m.start() - last < 400:
            continue
        last, n = m.start(), n + 1
        print(f"- `…{t[max(0, m.start() - 250):m.end() + 200]}…`")
        if n >= 8:
            break
    print()

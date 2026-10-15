#!/usr/bin/env python3
"""
drop_wrong_court.py — Αφαίρεση υποθέσεων άλλου δικαστηρίου (οδηγία καθηγητή, 2026-10-15)
---------------------------------------------------------------------------------------
Κάποιες υποθέσεις του CourtListener είναι καταχωρημένες ως CA5/CA9 αλλά είναι αποφάσεις άλλου
circuit (1st, 6th, 10th, Federal). Η λίστα είναι στο `data/wrong_court.csv`
(cluster_id, dataset_court, actual_court, note) — συμπληρώνεται με το χέρι.

Τρέχει ΠΡΙΝ από το dedupe.py (που μένει το τελευταίο βήμα). In-place με backup
(<όνομα>.pre_wrongcourt.csv)· οι γραμμές που σβήνονται καταγράφονται στο data/wrong_court_dropped.csv.
Ξανατρέχει χωρίς πρόβλημα (όσες έχουν ήδη σβηστεί απλώς δεν βρίσκονται).

Usage:  python code/drop_wrong_court.py
"""
import argparse
import csv
import shutil
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
DATA = Path(__file__).parent.parent / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DATA / "juribench_cases.csv"))
    ap.add_argument("--output", default=None)
    ap.add_argument("--list", default=str(DATA / "wrong_court.csv"))
    ap.add_argument("--dropped", default=str(DATA / "wrong_court_dropped.csv"))
    args = ap.parse_args()
    inp = Path(args.input)
    out = Path(args.output) if args.output else inp

    with open(args.list, encoding="utf-8") as f:
        wrong = {r["cluster_id"].strip(): r for r in csv.DictReader(f) if (r.get("cluster_id") or "").strip()}
    with open(inp, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        fieldnames, rows = rd.fieldnames, list(rd)

    keep, dropped = [], []
    for r in rows:
        (dropped if r.get("cluster_id") in wrong else keep).append(r)
    found = {r["cluster_id"] for r in dropped}

    if out == inp and dropped:
        bak = inp.with_name(inp.stem + ".pre_wrongcourt.csv")
        if not bak.exists():
            shutil.copy2(inp, bak)
            print(f"Backup → {bak}")
    if dropped or out != inp:
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(keep)
    # ο κατάλογος των σβησμένων ΣΥΜΠΛΗΡΩΝΕΤΑΙ (ώστε να μη χάνεται σε 2ο τρέξιμο)
    prev = {}
    p = Path(args.dropped)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            prev = {r["cluster_id"]: r for r in csv.DictReader(f)}
    for r in dropped:
        w_ = wrong[r["cluster_id"]]
        prev[r["cluster_id"]] = {"cluster_id": r["cluster_id"], "jurisdiction": r.get("jurisdiction", ""),
                                 "case_name": r.get("case_name", ""), "date_filed": r.get("date_filed", ""),
                                 "actual_court": w_.get("actual_court", ""), "note": w_.get("note", "")}
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cluster_id", "jurisdiction", "case_name", "date_filed", "actual_court", "note"])
        w.writeheader()
        w.writerows(prev.values())

    print(f"Λίστα: {len(wrong)} · σβήστηκαν τώρα: {len(dropped)} · "
          f"δεν βρέθηκαν (ήδη σβησμένες ή λάθος id): {len(set(wrong) - found)}")
    for r in dropped:
        print(f"  - {r['cluster_id']} · {r.get('jurisdiction')} → {wrong[r['cluster_id']].get('actual_court')} · "
              f"{r.get('case_name', '')[:60]}")
    print(f"Output: {len(keep)} γραμμές → {out}")


if __name__ == "__main__":
    main()

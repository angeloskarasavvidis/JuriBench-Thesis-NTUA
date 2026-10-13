#!/usr/bin/env python3
"""
diag_round2.py — ΜΟΝΟ ΑΝΑΓΝΩΣΗ (2η απάντηση καθηγητή, 2026-10-13). Δεν αλλάζει κανένα αρχείο.

A. Συνωνυμίες: για Smith/Nelson/Thomas (CA9) και visiting επώνυμα (Friedman κ.ά.) — πόσες υποθέσεις
   έχουν αρχικά στην υπογραφή / «Opinion by», πόσες πλήρες όνομα στη γραμμή «Before:», πόσες τίποτα.
B. Κεφαλίδες ECF που έμειναν (μετά το clean_headers) — πλήθη + δείγματα.
C. Στήλες ονομάτων JuDJIS / FJC + οι εγγραφές για τα επίμαχα επώνυμα.

Usage:  python code/diag_round2.py > data/diag_round2.md
"""
import csv
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

TARGETS = {"CA9": ["smith", "nelson", "thomas"]}
VISITING = ["friedman", "murphy", "parker", "hamilton", "kelly", "simon", "katzmann", "motz", "chen",
            "peterson", "rogers", "walter", "pratt", "rodriguez", "marshall", "burns", "davis"]
PANEL = re.compile(r"Before:?\s(.{0,600}?)(?:Circuit|District|Senior)?\s*Judges?\s*\.", re.S)
INIT = r"((?:[A-Z]\.\s*){1,3})"


def ws(t):
    return re.sub(r"\s+", " ", t or "")


def sig_initials(text, surname):
    """Αρχικά ΜΟΝΟ με κεφαλαία (case-sensitive)· το επώνυμο και το «Circuit Judge» χωρίς διάκριση πεζών."""
    s = "(?i:" + re.escape(surname) + r")\b"
    J = r"(?i:,?\s+(?:Chief\s+|Senior\s+)?(?:Circuit|District)\s+Judge)"
    OB = r"(?i:Opinion\s+by\s+(?:Chief\s+|Senior\s+)?Judge)\s+"
    for p in (r"(?<![A-Za-z.])" + INIT + r"\s*" + s + J, OB + INIT + r"\s*" + s):
        m = re.search(p, text)
        if m:
            return re.sub(r"\s+", "", m.group(1))
    m = re.search(OB + r"([A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?){0,2})\s+" + s, text)
    if m:
        return "full:" + m.group(1)
    return ""


def before_names(text, surname):
    m = PANEL.search(text[:20000])
    if not m:
        return None
    hits = re.findall(r"(?<![A-Za-z])([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3})\s+(?i:" + re.escape(surname) + r")\b",
                      m.group(1))
    return hits


def main():
    rows = list(csv.DictReader(open(DATA / "juribench_cases.csv", encoding="utf-8")))
    L = ["# diag_round2 — μόνο ανάγνωση", "", "## A. Συνωνυμίες — από πού μπορούμε να πάρουμε αρχικά", "",
         "| Δικαστήριο · επώνυμο | Υποθέσεις | Αρχικά στην υπογραφή/«Opinion by» | Μόνο από «Before:» (1 όνομα) | «Before:» με ≥2 ίδια επώνυμα | Τίποτα |",
         "|---|---|---|---|---|---|"]
    found = defaultdict(Counter)
    nothing = defaultdict(list)
    groups = [(j, s) for j, ss in TARGETS.items() for s in ss] + [(j, s) for j in ("CA5", "CA9") for s in VISITING]
    for j, s in groups:
        st = Counter()
        for r in rows:
            if r.get("jurisdiction") != j or (r.get("author_str") or "").strip().lower() != s:
                continue
            t = ws((r.get("opinion_text") or "")[:30000])
            st["n"] += 1
            ini = sig_initials(t, s)
            if ini:
                st["sig"] += 1; found[(j, s)]["υπογραφή " + ini] += 1; continue
            b = before_names(t, s)
            if b and len(b) == 1:
                st["before"] += 1; found[(j, s)]["Before " + b[0].strip()] += 1
            elif b and len(b) > 1:
                st["before_multi"] += 1
            else:
                st["none"] += 1; nothing[(j, s)].append(t[:220])
        if st["n"]:
            L.append(f"| {j} · {s} | {st['n']} | {st['sig']} | {st['before']} | {st['before_multi']} | {st['none']} |")
    L += ["", "### Τι βρέθηκε (top ανά επώνυμο)", ""]
    for k, c in found.items():
        L.append(f"- **{k[0]} {k[1]}**: " + " · ".join(f"{a} ({n})" for a, n in c.most_common(8)))
    rng = random.Random(1)
    L += ["", "### Δείγματα χωρίς τίποτα", ""]
    for k, lst in nothing.items():
        for t in rng.sample(lst, min(2, len(lst))):
            L.append(f"- {k[0]} {k[1]}: `{t}…`")

    # B. ECF
    pat = re.compile(r"Case:\s*\d|Document:\s*\d|Date\s*Filed:|Page:\s*\d", re.I)
    cnt, occ, samples = Counter(), Counter(), []
    for r in rows:
        for col in ("opinion_text", "dissent_text", "concurrence_text"):
            t = r.get(col) or ""
            ms = list(pat.finditer(t))
            if ms:
                cnt[r["jurisdiction"]] += 1; occ[r["jurisdiction"]] += len(ms)
                m = ms[0]; samples.append((r["jurisdiction"], col, ws(t[max(0, m.start() - 80):m.end() + 120])))
    L += ["", "## B. Κεφαλίδες ECF που έμειναν", "",
          "| | SCOTUS | CA5 | CA9 |", "|---|---|---|---|",
          f"| στήλες-κειμένου με υπόλοιπα | {cnt['SCOTUS']} | {cnt['CA5']} | {cnt['CA9']} |",
          f"| εμφανίσεις | {occ['SCOTUS']} | {occ['CA5']} | {occ['CA9']} |", "", "### Δείγματα", ""]
    for j, col, s in rng.sample(samples, min(20, len(samples))):
        L.append(f"- {j} · {col}: `…{s}…`")

    # C. JuDJIS / FJC
    L += ["", "## C. Στήλες ονομάτων", ""]
    with open(DATA / "judjis" / "agjudge_full.csv", encoding="latin-1") as f:
        rd = csv.DictReader(f)
        L.append("**JuDJIS στήλες:** " + ", ".join(rd.fieldnames))
        L.append("")
        for r in rd:
            if (r.get("last.name") or "").strip().lower() in ("smith", "nelson", "thomas", "friedman"):
                L.append("- JuDJIS: " + " | ".join(f"{k}={r[k]}" for k in rd.fieldnames
                                                   if any(x in k.lower() for x in ("name", "court", "judjis", "year", "id"))))
    for enc in ("utf-8-sig", "latin-1"):
        try:
            f = open(DATA / "fjc" / "judges.csv", encoding=enc, newline=""); f.read(); f.seek(0); break
        except UnicodeDecodeError:
            f.close()
    rd = csv.DictReader(f)
    L += ["", "**FJC στήλες ονομάτων:** " + ", ".join(c for c in rd.fieldnames if "name" in c.lower() and "(" not in c), ""]
    for r in rd:
        if (r.get("Last Name") or "").strip().lower() in ("smith", "nelson", "thomas", "friedman"):
            courts = [r.get(f"Court Name ({k})", "") for k in range(1, 7) if r.get(f"Court Name ({k})")]
            if any("Ninth" in c for c in courts) or (r.get("Last Name") or "").lower() == "friedman":
                L.append(f"- FJC: {r.get('First Name')} | {r.get('Middle Name')} | {r.get('Last Name')} | "
                         f"{r.get('Suffix')} · " + "; ".join(courts))
    print("\n".join(L))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
clean_headers.py — Αφαίρεση κεφαλίδων σελίδας PDF από τα κείμενα (οδηγία καθηγητή, 2026-10-12)
--------------------------------------------------------------------------------------------
Στήλες: opinion_text, dissent_text, concurrence_text.

1. CA5 (και όπου αλλού εμφανίζεται): κεφαλίδα του ECF
     «21 Case: 21-40849 Document: 00516833261 Page: 19 Date Filed: 07/25/2023 No. 21-40849»
   (ο αριθμός σελίδας που προηγείται και το «No. …» / «Cons. w/ No. …» που ακολουθεί).
2. CA9: επαναλαμβανόμενη κεφαλίδα «2 SHELTRA V. CHRISTENSEN» / «UNITED STATES V. WAGGY 15».
   ΑΣΦΑΛΕΙΑ: αφαιρείται μόνο φράση «ΚΕΦΑΛΑΙΑ V. ΚΕΦΑΛΑΙΑ» που (α) είναι όλη με κεφαλαία,
   (β) έχει δίπλα της αριθμό σελίδας και (γ) εμφανίζεται έτσι ≥3 φορές στην ίδια υπόθεση.
   Τα κανονικά «United States v. Lopez» (πεζά) μέσα στο σκεπτικό δεν αγγίζονται.

In-place με backup (<όνομα>.pre_clean.csv) + αναφορά data/clean_headers_report.md.
Usage:  python code/clean_headers.py
"""
import argparse
import csv
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)

TEXT_COLS = ["opinion_text", "dissent_text", "concurrence_text"]
DOCKET = r"\d{2}-\d{2,6}"
CA5_HDR = re.compile(
    r"(?:(?<![\w.,])\d{1,3}\s+)?Case:\s*" + DOCKET + r"\s+Document:\s*[\w\-]+\s+Page:\s*\d+\s+"
    r"Date\s+Filed:\s*\d{1,2}/\d{1,2}/\d{4}"
    r"(?:\s+No\.\s*" + DOCKET + r"(?:\s*,?\s*(?:c/w|Cons\.\s*w/|consolidated\s+with)\s*No\.\s*" + DOCKET + r")*)?")

TOK = r"[A-Z][A-Z0-9.&'’\-]*"                # λέξη ΜΟΝΟ με κεφαλαία
CAPTION = re.compile(r"(?<![A-Za-z])((?:" + TOK + r"\s+){1,4})V\.\s+((?:" + TOK + r"(?:\s+|$)){1,6})")
TRAIL_STOP = {"OPINION", "SUMMARY", "COUNSEL", "ORDER", "MEMORANDUM", "BACKGROUND", "DISCUSSION",
              "CONCLUSION", "ANALYSIS", "FACTS", "AND", "THE", "OF", "IN", "I", "II", "III", "IV", "VI",
              "A", "B", "C", "D", "E", "AFFIRMED", "REVERSED", "VACATED", "REMANDED", "DISMISSED"}
MIN_REPEATS = 3


def ws(s):
    return r"\s+".join(re.escape(t) for t in s.split())


def caption_variants(text):
    """→ Counter{caption: πόσες φορές εμφανίζεται ΜΕ αριθμό σελίδας δίπλα}."""
    seen = set()
    for m in CAPTION.finditer(text):
        before = m.group(1).split()
        after = m.group(2).split()
        while after and after[-1].rstrip(".") in TRAIL_STOP:
            after.pop()
        if not after:
            continue
        for k in range(1, len(before) + 1):
            seen.add(" ".join(before[-k:] + ["V."] + after))
    counts = Counter()
    for v in seen:
        pat = re.compile(r"(?<![\w])\d{1,3}\s+" + ws(v) + r"(?![A-Za-z])|(?<![A-Za-z])" + ws(v) + r"\s+\d{1,3}(?![\d/])")
        counts[v] = len(pat.findall(text))
    return counts


def clean_row(texts, court):
    """→ (νέα κείμενα, #CA5 κεφαλίδες, #CA9 κεφαλίδες, [δείγματα])"""
    out, n5, n9, samples = {}, 0, 0, []
    caps = []
    if court == "CA9":
        allt = " ".join(texts.values())
        counts = caption_variants(allt)
        caps = sorted([v for v, c in counts.items() if c >= MIN_REPEATS], key=len, reverse=True)
    for col, t in texts.items():
        if not t:
            out[col] = t
            continue
        new, k = CA5_HDR.subn(" ", t)
        n5 += k
        for v in caps:
            pat = re.compile(r"(?<![\w])\d{1,3}\s+" + ws(v) + r"(?![A-Za-z])|(?<![A-Za-z])" + ws(v) + r"\s+\d{1,3}(?![\d/])")
            for m in list(pat.finditer(new))[:1]:
                samples.append(new[max(0, m.start() - 40):m.end() + 40])
            new, k = pat.subn(" ", new)
            n9 += k
        if n5 and not samples:
            m = CA5_HDR.search(t)
            if m:
                samples.append(t[max(0, m.start() - 40):m.end() + 40])
        out[col] = re.sub(r"[ \t]{2,}", " ", new)
    return out, n5, n9, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    root = Path(__file__).parent.parent
    inp = Path(args.input) if args.input else root / "data" / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp
    report = Path(args.report) if args.report else root / "data" / "clean_headers_report.md"
    bak = inp.with_name(inp.stem + ".pre_clean.csv")
    if out == inp and not bak.exists():
        shutil.copy2(inp, bak); print(f"Backup → {bak}")

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    st = {c: Counter() for c in ("SCOTUS", "CA5", "CA9")}
    samples = []
    for r in rows:
        court = r.get("jurisdiction", "")
        texts = {c: r.get(c, "") or "" for c in TEXT_COLS if c in r}
        before = sum(len(t) for t in texts.values())
        new, n5, n9, smp = clean_row(texts, court)
        r.update(new)
        s = st.setdefault(court, Counter())
        s["υποθέσεις"] += 1
        s["με αλλαγή"] += bool(n5 or n9)
        s["κεφαλίδες CA5 (ECF)"] += n5
        s["κεφαλίδες CA9 (caption)"] += n9
        s["χαρακτήρες που αφαιρέθηκαν"] += before - sum(len(t) for t in new.values())
        if smp:
            samples.append((court, r.get("case_name", "")[:50], smp[0]))

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)

    keys = ["υποθέσεις", "με αλλαγή", "κεφαλίδες CA5 (ECF)", "κεφαλίδες CA9 (caption)", "χαρακτήρες που αφαιρέθηκαν"]
    L = [f"# Αφαίρεση κεφαλίδων σελίδας — `{out.name}`", "", "| | SCOTUS | CA5 | CA9 |", "|---|---|---|---|"]
    L += [f"| {k} | {st['SCOTUS'][k]} | {st['CA5'][k]} | {st['CA9'][k]} |" for k in keys]
    L += ["", "## Δείγματα (κείμενο ΠΡΙΝ την αφαίρεση, γύρω από την κεφαλίδα)", ""]
    for c, cn, s in random.Random(3).sample(samples, min(12, len(samples))):
        L.append(f"- **{c}** · {cn}: `…{re.sub(chr(10), ' ', s)}…`")
    text = "\n".join(L)
    report.write_text(text + "\n", encoding="utf-8")
    print(text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

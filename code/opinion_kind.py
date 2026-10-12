#!/usr/bin/env python3
"""
opinion_kind.py — Είδος απόφασης (οδηγία καθηγητή, 2026-10-12)
--------------------------------------------------------------
Νέα στήλη `opinion_kind` ∈ {merits, summary_order, memorandum, per_curiam}. ΚΑΜΙΑ υπόθεση
δεν αφαιρείται — η εξαίρεση γίνεται στα πειράματα. Κανόνες (σειρά προτεραιότητας):

  memorandum    : circuits — «MEMORANDUM» στην αρχή (CA9 memorandum dispositions).
  summary_order : SCOTUS — dissent/statement on denial of certiorari, επείγουσες αιτήσεις
                  («application for stay/injunction…», «ON APPLICATION FOR …»).
                  circuits — διάταξη απόρριψης rehearing en banc, όταν η κύρια γνώμη είναι σύντομη
                  (< 1.500 λέξεις· αλλιώς είναι amended opinion επί της ουσίας).
  per_curiam    : «PER CURIAM» στην αρχή — circuits: και χωρίς υπογεγραμμένο συγγραφέα
                  (author_source = none)· SCOTUS: και χωρίς «delivered the opinion of the Court».
  merits        : όλα τα υπόλοιπα.

Αναφορά (data/opinion_kind_report.md): πλήθη ανά δικαστήριο, δείγματα ανά κατηγορία και οι
circuit υποθέσεις «merits» χωρίς συγγραφέα (ο καθηγητής περιμένει ~70+).
Usage:  python code/opinion_kind.py      (μετά το enrich_authors.py)
"""
import argparse
import csv
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

KINDS = ["merits", "summary_order", "memorandum", "per_curiam"]
MEMO = re.compile(r"\bMEMORANDUM\b")
CERT = r"(?:the\s+)?(?:petition\s+for\s+)?(?:a\s+)?(?:writ\s+of\s+)?certiorari"
SCOTUS_SUMMARY = re.compile(
    r"dissenting\s+from\s+(?:the\s+)?denial\s+of\s+" + CERT +
    r"|respecting\s+(?:the\s+)?denial\s+of\s+" + CERT +
    r"|concurring\s+in\s+(?:the\s+)?denial\s+of\s+" + CERT +
    r"|\bON\s+APPLICATION\s+FOR\b|\bapplication\s+for\s+(?:a\s+|an\s+)?(?:stay|injunction|vacatur|recall)"
    r"|ORDER\s+IN\s+PENDING\s+CASE", re.I)
EN_BANC_DENIAL = re.compile(
    r"rehearing\s+en\s+banc\s+(?:is|are)\s+(?:hereby\s+)?DENIED|ORDER\s+DENYING\s+(?:THE\s+)?PETITION\s+FOR\s+"
    r"REHEARING\s+EN\s+BANC|ON\s+PETITION\s+FOR\s+REHEARING\s+EN\s+BANC|"
    r"dissenting\s+from\s+(?:the\s+)?denial\s+of\s+(?:the\s+petition\s+for\s+)?rehearing\s+en\s+banc|"
    r"respecting\s+(?:the\s+)?denial\s+of\s+(?:the\s+petition\s+for\s+)?rehearing\s+en\s+banc", re.I)
PER_CURIAM = re.compile(r"\bPER\s+CURIAM\b", re.I)
DELIVERED = re.compile(r"delivered\s+the\s+opinion\s+of\s+the\s+Court", re.I)
SHORT_WORDS = 1500


def head(t, n):
    return re.sub(r"\s+", " ", (t or "")[:n])


def classify(r):
    jur, txt = r.get("jurisdiction", ""), r.get("opinion_text", "") or ""
    h = head(txt, 4000)
    if jur in ("CA5", "CA9"):
        if MEMO.search(head(txt, 1500)):
            return "memorandum"
        if EN_BANC_DENIAL.search(h) and len(txt.split()) < SHORT_WORDS:
            return "summary_order"
        if (r.get("author_source") or "") == "none" and PER_CURIAM.search(h):
            return "per_curiam"
        return "merits"
    if jur == "SCOTUS":
        if SCOTUS_SUMMARY.search(h):
            return "summary_order"
        if PER_CURIAM.search(h) and not DELIVERED.search(h):
            return "per_curiam"
        return "merits"
    return "merits"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    root = Path(__file__).parent.parent
    inp = Path(args.input) if args.input else root / "data" / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp
    report = Path(args.report) if args.report else root / "data" / "opinion_kind_report.md"
    bak = inp.with_name(inp.stem + ".pre_kind.csv")
    if out == inp and not bak.exists():
        shutil.copy2(inp, bak); print(f"Backup → {bak}")

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    if "opinion_kind" not in fieldnames:
        fieldnames.append("opinion_kind")

    cnt = {c: Counter() for c in ("SCOTUS", "CA5", "CA9")}
    examples = defaultdict(list)
    unknown = []
    for r in rows:
        k = classify(r)
        r["opinion_kind"] = k
        cnt.setdefault(r.get("jurisdiction", ""), Counter())[k] += 1
        examples[(r.get("jurisdiction"), k)].append(r)
        if r.get("jurisdiction") in ("CA5", "CA9") and k == "merits" and (r.get("author_source") or "") == "none":
            unknown.append(r)

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)

    rng = random.Random(5)
    L = [f"# opinion_kind — `{out.name}`", "", "| opinion_kind | SCOTUS | CA5 | CA9 | Σύνολο |", "|---|---|---|---|---|"]
    for k in KINDS:
        L.append(f"| {k} | {cnt['SCOTUS'][k]} | {cnt['CA5'][k]} | {cnt['CA9'][k]} | "
                 f"{cnt['SCOTUS'][k] + cnt['CA5'][k] + cnt['CA9'][k]} |")
    L += ["", f"**Circuit «merits» χωρίς υπογεγραμμένο συγγραφέα (author_source = none): {len(unknown)}** "
          f"(CA5 {sum(1 for r in unknown if r['jurisdiction'] == 'CA5')} · "
          f"CA9 {sum(1 for r in unknown if r['jurisdiction'] == 'CA9')})", ""]
    for r in rng.sample(unknown, min(10, len(unknown))):
        L.append(f"- {r['jurisdiction']} · {r.get('case_name', '')[:60]} · `{head(r.get('opinion_text'), 160)}…`")
    L += ["", "## Δείγματα ανά κατηγορία (εκτός merits)", ""]
    for (jur, k), lst in sorted(examples.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        if k == "merits":
            continue
        for r in rng.sample(lst, min(3, len(lst))):
            L.append(f"- **{k}** · {jur} · {r.get('case_name', '')[:55]} · `{head(r.get('opinion_text'), 140)}…`")
    text = "\n".join(L)
    report.write_text(text + "\n", encoding="utf-8")
    print(text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

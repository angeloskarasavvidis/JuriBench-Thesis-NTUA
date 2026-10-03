#!/usr/bin/env python3
"""
completeness_report.py
----------------------
Αναφορά πληρότητας του τελικού dataset (για τον επιβλέποντα).

Απαντά σε δύο ερωτήματα:
  1. Πόσα λείπουν ανά πεδίο — μετρημένα ΜΟΝΟ στις υποθέσεις όπου το πεδίο
     εφαρμόζεται (π.χ. το decision_direction υπάρχει μόνο για SCOTUS, το
     author_str μόνο για circuits). Έτσι το «λείπει» είναι πραγματικό κενό,
     όχι σχεδιαστική απουσία.
  2. Πόσες υποθέσεις είναι «πλήρεις» σε κάθε επίπεδο (generation-ready,
     LJP-ready, πλήρη μεταδεδομένα τώρα / μετά το Lawma).

Βγάζει markdown (διαβάζεται και στο terminal). Μόνο stdlib.

Usage:
  python code/completeness_report.py                                    # data/juribench_cases.csv
  python code/completeness_report.py --md data/completeness_report.md   # + αποθήκευση
  python code/completeness_report.py --input data/juribench_labeled.csv # μετά το Lawma
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

csv.field_size_limit(sys.maxsize)

COURTS = ["SCOTUS", "CA5", "CA9"]
CIRCUITS = {"CA5", "CA9"}

# (πεδίο, σε ποια δικαστήρια εφαρμόζεται, πηγή τιμής, ρόλος)
FIELDS = [
    ("opinion_text",       "ALL",      "bulk CourtListener",              "στόχος παραγωγής"),
    ("case_name",          "ALL",      "bulk",                            "μεταδεδομένο"),
    ("date_filed",         "ALL",      "bulk",                            "μεταδεδομένο"),
    ("judge_name",         "ALL",      "bulk (clusters.judges)",          "μεταδεδομένο / author-key SCOTUS"),
    ("facts",              "ALL",      "LLM (DeepSeek)",                  "input task"),
    ("issue_text",         "ALL",      "LLM (DeepSeek)",                  "input task"),
    ("disposition",        "ALL",      "LLM (DeepSeek)",                  "label (LJP)"),
    ("prevailing_party",   "ALL",      "LLM (DeepSeek)",                  "δευτερεύον label"),
    ("author_str",         "CIRCUITS", "regex byline",                    "author-key + ideology match"),
    ("ideology_score",     "ALL",      "Martin-Quinn / JuDJIS",           "eval-only"),
    ("ideology",           "CIRCUITS", "JuDJIS (κατώφλι ±0.3)",           "eval-only"),
    ("issue_area",         "ALL",      "SCDB (SCOTUS) / Lawma (circuits)", "eval-only"),
    ("decision_direction", "SCOTUS",   "SCDB",                            "eval-only"),
    ("syllabus",           "ALL",      "bulk (headnotes/summary)",        "βοηθητικό"),
]
NEVER_FILLED = ["judge_id", "author_cl_id"]   # σκόπιμα κενά (δεν υπάρχει People FK)
SCOPE_LABEL = {"ALL": "όλα", "CIRCUITS": "CA5/CA9", "SCOTUS": "SCOTUS"}


def has(r, f):
    return bool((r.get(f) or "").strip())


def applies(scope, jur):
    return scope == "ALL" or (scope == "CIRCUITS" and jur in CIRCUITS) or scope == jur


def frac(a, b):
    return f"{a}/{b} ({a / b:.1%})" if b else "—"


def ljp_ok(r):
    return (r.get("disposition") or "").strip().lower() not in ("", "unclear")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--md", default=None, help="αποθήκευση της αναφοράς σε markdown αρχείο")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    path = Path(args.input) if args.input else root / "data" / "juribench_cases.csv"
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"Άδειο αρχείο: {path}")
    cols = set(rows[0].keys())

    by = {c: [r for r in rows if r.get("jurisdiction") == c] for c in COURTS}
    lawma_done = any("lawma" in (r.get("issue_area_source") or "").lower() for r in rows)

    out = []
    p = out.append

    p(f"# Αναφορά πληρότητας — `{path.name}`")
    p("")
    p(f"**Σύνολο:** {len(rows)} υποθέσεις — " +
      " · ".join(f"{c} {len(by[c])}" for c in COURTS))
    p(f"**Lawma (issue_area circuits):** {'ΕΧΕΙ τρέξει' if lawma_done else 'ΔΕΝ έχει τρέξει ακόμα'}")
    p("")

    # ── 1. Ανά πεδίο ──────────────────────────────────────────────────────
    p("## 1. Πληρότητα ανά πεδίο (μόνο όπου το πεδίο εφαρμόζεται)")
    p("")
    p("| Πεδίο | Πηγή | Ρόλος | Εφαρμόζεται | SCOTUS | CA5 | CA9 | Σύνολο | Λείπουν |")
    p("|---|---|---|---|---|---|---|---|---|")
    for f, scope, src, role in FIELDS:
        if f not in cols:
            p(f"| `{f}` | {src} | {role} | {SCOPE_LABEL[scope]} | — | — | — | ΔΕΝ ΥΠΑΡΧΕΙ ΣΤΗΛΗ | — |")
            continue
        cells, tot_has, tot_n = [], 0, 0
        for c in COURTS:
            if applies(scope, c):
                n = len(by[c]); h = sum(has(r, f) for r in by[c])
                tot_has += h; tot_n += n
                cells.append(frac(h, n))
            else:
                cells.append("n/a")
        p(f"| `{f}` | {src} | {role} | {SCOPE_LABEL[scope]} | " + " | ".join(cells) +
          f" | {frac(tot_has, tot_n)} | {tot_n - tot_has} |")
    p("")

    # ── 2. Επίπεδα πληρότητας ─────────────────────────────────────────────
    def tier_a(r): return has(r, "opinion_text") and has(r, "facts") and has(r, "issue_text")
    def tier_b(r): return tier_a(r) and ljp_ok(r)
    def tier_c(r): return tier_b(r) and has(r, "ideology_score") and has(r, "issue_area")
    def tier_d(r):  # εκτίμηση: το Lawma γεμίζει issue_area σε ΟΛΑ τα circuits
        ia = has(r, "issue_area") or r.get("jurisdiction") in CIRCUITS
        return tier_b(r) and has(r, "ideology_score") and ia

    tiers = [
        ("A. Generation-ready", "opinion_text + facts + issue_text", tier_a),
        ("B. LJP-ready", "A + disposition ≠ unclear/κενό", tier_b),
        ("C. Πλήρη μεταδεδομένα (τώρα)", "B + ideology_score + issue_area", tier_c),
    ]
    if not lawma_done:
        tiers.append(("D. Πλήρη μεταδεδομένα (μετά το Lawma, εκτίμηση)",
                      "όπως C, με issue_area circuits από Lawma", tier_d))

    p("## 2. Πόσες υποθέσεις είναι πλήρεις")
    p("")
    p("| Επίπεδο | Ορισμός | SCOTUS | CA5 | CA9 | Σύνολο |")
    p("|---|---|---|---|---|---|")
    for name, desc, fn in tiers:
        cells = [frac(sum(fn(r) for r in by[c]), len(by[c])) for c in COURTS]
        p(f"| **{name}** | {desc} | " + " | ".join(cells) +
          f" | **{frac(sum(fn(r) for r in rows), len(rows))}** |")
    p("")
    p("> Τα A/B είναι τα δεδομένα που χρειάζεται η εκπαίδευση. Τα C/D αφορούν μόνο την "
      "ανάλυση (ιδεολογία/θεματική είναι eval-only) — όσες υποθέσεις τους λείπει μεταδεδομένο "
      "μένουν κανονικά στο train/test, απλώς δεν μπαίνουν στις αναλύσεις ανά ιδεολογία/θέμα.")
    p("")

    # ── 3. Διάγνωση: γιατί λείπουν ────────────────────────────────────────
    p("## 3. Γιατί λείπουν (διάγνωση)")
    p("")
    miss_llm = sum(1 for r in rows if not (has(r, "facts") and has(r, "issue_text")))
    p(f"- **facts/issue_text κενά:** {miss_llm} — αποτυχίες κλήσεων LLM· ξανατρέχουν "
      "(`enrich_case_fields.py` είναι resumable και πιάνει μόνο τα κενά).")
    disp = Counter((r.get("disposition") or "").strip().lower() for r in rows)
    p(f"- **disposition:** unclear {disp.get('unclear', 0)} · other {disp.get('other', 0)} · "
      f"κενό {disp.get('', 0)}.")

    sc = by["SCOTUS"]
    sc_miss = [r for r in sc if not has(r, "ideology_score")]
    sc_nomatch = sum(1 for r in sc_miss
                     if (r.get("issue_area_source") or "") != "scdb" and not has(r, "decision_direction"))
    p(f"- **Ιδεολογία SCOTUS λείπει σε {len(sc_miss)}:** {sc_nomatch} χωρίς match στο SCDB "
      f"(όνομα+έτος), {len(sc_miss) - sc_nomatch} με SCDB match αλλά χωρίς Martin-Quinn "
      "(π.χ. per curiam / χωρίς majOpinWriter).")

    ci = [r for r in rows if r.get("jurisdiction") in CIRCUITS]
    ci_miss = [r for r in ci if not has(r, "ideology_score")]
    ci_noauthor = sum(1 for r in ci_miss if not has(r, "author_str"))
    p(f"- **Ιδεολογία circuits λείπει σε {len(ci_miss)}:** {ci_noauthor} χωρίς author_str "
      f"(δεν βρέθηκε byline), {len(ci_miss) - ci_noauthor} με author_str αλλά χωρίς JuDJIS match ≥0.92 "
      "(π.χ. district/visiting judges εκτός roster).")

    ci_noia = sum(1 for r in ci if not has(r, "issue_area"))
    if ci_noia:
        p(f"- **issue_area circuits κενό σε {ci_noia}:** εκκρεμεί το Lawma (το τρέχει ο επιβλέπων).")
    p("")

    # ── 4. Κατανομή disposition ───────────────────────────────────────────
    p("## 4. Κατανομή disposition")
    p("")
    p("| disposition | SCOTUS | CA5 | CA9 | Σύνολο |")
    p("|---|---|---|---|---|")
    for d, n in disp.most_common():
        cells = [str(sum(1 for r in by[c] if (r.get("disposition") or "").strip().lower() == d))
                 for c in COURTS]
        p(f"| {d or '(κενό)'} | " + " | ".join(cells) + f" | {n} |")
    p("")

    # ── 5. Σκόπιμα κενά ───────────────────────────────────────────────────
    present = [c for c in NEVER_FILLED if c in cols]
    if present:
        p("## 5. Πεδία που μένουν σκόπιμα κενά")
        p("")
        p(", ".join(f"`{c}`" for c in present) +
          " — θέσεις για CourtListener People-ID, που δεν υπάρχει στα bulk opinions. "
          "Δεν χρησιμοποιούνται πουθενά· δεν μετράνε ως «ελλείψεις».")
        p("")

    text = "\n".join(out)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n", encoding="utf-8")
        print(f"\n[αποθηκεύτηκε → {args.md}]")


if __name__ == "__main__":
    main()

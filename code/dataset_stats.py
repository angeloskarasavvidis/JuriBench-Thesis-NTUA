#!/usr/bin/env python3
"""
dataset_stats.py
----------------
Print dataset statistics for the juribench CSV.

Usage:
  python dataset_stats.py                          # uses juribench_labeled.csv
  python dataset_stats.py --input my_file.csv
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ISSUE_AREA_LABELS = {
    1: "Criminal Procedure",   2: "Civil Rights",        3: "First Amendment",
    4: "Due Process",          5: "Privacy",             6: "Attorneys' Fees",
    7: "Unions",               8: "Economic Activity",   9: "Judicial Power",
    10: "Federalism",          11: "Interstate Relations", 12: "Federal Taxation",
    13: "Miscellaneous",       14: "Private Action",
}

# Per implementation-details.md §1: only these two sources are an authorized
# ideology label origin. Anything else (e.g. an LLM fallback) is unvalidated.
AUTHORIZED_IDEOLOGY_SOURCES = {"judis", "martin_quinn"}


def pct(n, total):
    return f"{n/total*100:.1f}%" if total else "n/a"


def bar(n, total, width=20):
    filled = round(n / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def print_section(title):
    print(f"\n{'─'*65}")
    print(f"  {title}")
    print(f"{'─'*65}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=None)
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    default = root / "data" / "juribench_labeled.csv"
    if not default.exists():
        default = root / "data" / "juribench_dataset.csv"
    path = Path(args.input) if args.input else default
    print(f"File: {path}")

    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    columns = list(rows[0].keys()) if rows else []

    # ── Overview ──────────────────────────────────────────────────────────────
    print_section("OVERVIEW")
    print(f"  Rows    : {total}")
    print(f"  Columns : {len(columns)}")
    print(f"  Fields  : {', '.join(columns)}")

    # ── By jurisdiction ───────────────────────────────────────────────────────
    print_section("BY JURISDICTION")
    juri_count = Counter(r.get("jurisdiction", "").strip() for r in rows)
    for juri, n in sorted(juri_count.items(), key=lambda x: -x[1]):
        print(f"  {juri or '(empty)':<12} {n:>6}  {pct(n, total):>6}  {bar(n, total)}")

    # ── Duplicate case_name check ─────────────────────────────────────────────
    print_section("DUPLICATE CASE_NAME CHECK")
    name_count = Counter(r.get("case_name", "").strip() for r in rows if r.get("case_name", "").strip())
    dupes = {name: n for name, n in name_count.items() if n > 1}
    print(f"  Unique case_name values : {len(name_count)}")
    print(f"  Duplicated case_name    : {len(dupes)}  ({sum(dupes.values())} rows involved)")
    if dupes:
        for name, n in sorted(dupes.items(), key=lambda x: -x[1])[:10]:
            print(f"    x{n}  {name}")
        if len(dupes) > 10:
            print(f"    … and {len(dupes) - 10} more")

    # ── Ideology distribution (categorical) + jurisdiction x ideology cells ──
    print_section("IDEOLOGY DISTRIBUTION (categorical)")
    ideo_count = Counter(r.get("ideology", "").strip() for r in rows)
    for label, n in sorted(ideo_count.items(), key=lambda x: -x[1]):
        print(f"  {label or '(empty)':<14} {n:>6}  {pct(n, total):>6}  {bar(n, total)}")

    print_section("JURISDICTION x IDEOLOGY CELL COUNTS")
    cells = Counter((r.get("jurisdiction", "").strip(), r.get("ideology", "").strip()) for r in rows)
    for (juri, ideo), n in sorted(cells.items()):
        flag = "  ⚠ N<10 — too thin for a reliable centroid" if 0 < n < 10 else ""
        print(f"  {juri or '(empty)':<10} x {ideo or '(empty)':<14} {n:>5}{flag}")

    # ── ideology_source health (flag anything outside JuDJIS/Martin-Quinn) ────
    print_section("IDEOLOGY_SOURCE HEALTH")
    src_count = Counter(r.get("ideology_source", "").strip() or "(empty)" for r in rows)
    for src, n in sorted(src_count.items(), key=lambda x: -x[1]):
        flag = "" if src in AUTHORIZED_IDEOLOGY_SOURCES or src == "(empty)" else "  ⚠ NOT an authorized source"
        print(f"  {src:<16} {n:>6}  {pct(n, total):>6}{flag}")

    # ── issue_area coverage ───────────────────────────────────────────────────
    print_section("ISSUE_AREA COVERAGE")
    by_juri = defaultdict(lambda: {"has": 0, "miss": 0, "sources": Counter()})
    for r in rows:
        j  = r.get("jurisdiction", "").strip()
        ia = r.get("issue_area", "").strip()
        src = r.get("issue_area_source", "").strip() or "unknown"
        if ia:
            by_juri[j]["has"] += 1
            by_juri[j]["sources"][src] += 1
        else:
            by_juri[j]["miss"] += 1

    for juri in sorted(by_juri):
        d   = by_juri[juri]
        tot = d["has"] + d["miss"]
        src_str = ", ".join(f"{s}:{n}" for s, n in d["sources"].most_common())
        print(f"  {juri or '(empty)':<12}  {d['has']:>5}/{tot:<5} ({pct(d['has'], tot):>6})  sources: {src_str or '—'}")

    # ── issue_area distribution (where present) ───────────────────────────────
    print_section("ISSUE_AREA DISTRIBUTION (all jurisdictions)")
    ia_count = Counter()
    for r in rows:
        ia = r.get("issue_area", "").strip()
        if ia:
            try:
                ia_count[int(ia)] += 1
            except ValueError:
                ia_count[ia] += 1

    ia_total = sum(ia_count.values())
    for code in sorted(ia_count, key=lambda x: (isinstance(x, str), x if isinstance(x, str) else -ia_count[x])):
        n     = ia_count[code]
        label = ISSUE_AREA_LABELS.get(code, str(code))
        print(f"  {str(code):>2}  {label:<24}  {n:>5}  {pct(n, ia_total):>6}  {bar(n, ia_total)}")
    print(f"  {'':>2}  {'TOTAL':<24}  {ia_total:>5}")

    # ── ideology_score coverage ───────────────────────────────────────────────
    print_section("IDEOLOGY_SCORE COVERAGE")
    ideo_by_juri = defaultdict(lambda: {"has": 0, "miss": 0, "sources": Counter(), "vals": []})
    for r in rows:
        j    = r.get("jurisdiction", "").strip()
        ids  = r.get("ideology_score", "").strip()
        src  = r.get("ideology_source", "").strip() or "unknown"
        if ids:
            ideo_by_juri[j]["has"] += 1
            ideo_by_juri[j]["sources"][src] += 1
            try:
                ideo_by_juri[j]["vals"].append(float(ids))
            except ValueError:
                pass
        else:
            ideo_by_juri[j]["miss"] += 1

    for juri in sorted(ideo_by_juri):
        d    = ideo_by_juri[juri]
        tot  = d["has"] + d["miss"]
        vals = d["vals"]
        src_str = ", ".join(f"{s}:{n}" for s, n in d["sources"].most_common())
        if vals:
            mn, mx, avg = min(vals), max(vals), sum(vals) / len(vals)
            range_str = f"range [{mn:.2f}, {mx:.2f}]  mean {avg:.2f}"
        else:
            range_str = ""
        print(f"  {juri or '(empty)':<12}  {d['has']:>5}/{tot:<5} ({pct(d['has'], tot):>6})  {src_str}  {range_str}")

    # ── opinion_text coverage BY jurisdiction ─────────────────────────────────
    print_section("OPINION_TEXT COVERAGE BY JURISDICTION")
    text_by_juri = defaultdict(lambda: {"has": 0, "miss": 0})
    for r in rows:
        j = r.get("jurisdiction", "").strip()
        d = text_by_juri[j]
        if r.get("opinion_text", "").strip():
            d["has"] += 1
        else:
            d["miss"] += 1
    for juri in sorted(text_by_juri):
        d = text_by_juri[juri]
        tot = d["has"] + d["miss"]
        print(f"  {juri or '(empty)':<12}  {d['has']:>5}/{tot:<5} present  "
              f"{d['miss']:>5} missing ({pct(d['miss'], tot):>6})")

    # ── cross-check: does the opinion_text gap overlap the ideology_source gap? ─
    no_text_keys = {
        (r.get("case_name", ""), r.get("date_filed", ""), r.get("judge_name", ""))
        for r in rows if not r.get("opinion_text", "").strip()
    }
    unauth_ideo = [
        r for r in rows
        if r.get("ideology_source", "").strip() not in AUTHORIZED_IDEOLOGY_SOURCES
        and r.get("ideology_source", "").strip() not in ("", None)
    ]
    if unauth_ideo:
        overlap = sum(
            1 for r in unauth_ideo
            if (r.get("case_name", ""), r.get("date_filed", ""), r.get("judge_name", "")) in no_text_keys
        )
        still_usable = len(unauth_ideo) - overlap
        warn = "  ⚠ contamination survives the text filter" if still_usable else ""
        print_section("CROSS-CHECK: unauthorized ideology_source vs missing opinion_text")
        print(f"  Unauthorized-source rows               : {len(unauth_ideo)}")
        print(f"  … of those, also missing opinion_text  : {overlap}")
        print(f"  … of those, STILL usable (have text)   : {still_usable}{warn}")

    # ── Missing key fields ────────────────────────────────────────────────────
    print_section("MISSING VALUE SUMMARY")
    key_fields = ["opinion_text", "syllabus", "issue_text", "facts", "issue_area",
                  "ideology_score", "judge_name", "judge_id", "court_id", "decision_direction"]
    for field in key_fields:
        if field not in columns:
            print(f"  {field:<22}  COLUMN NOT PRESENT")
            continue
        missing = sum(1 for r in rows if not r.get(field, "").strip())
        print(f"  {field:<22}  {total - missing:>6} present  {missing:>6} missing  ({pct(missing, total)} missing)")

    # ── Text length stats ─────────────────────────────────────────────────────
    print_section("TEXT LENGTH (chars)")
    for field in ["opinion_text", "syllabus", "issue_text"]:
        if field not in columns:
            continue
        lengths = [len(r.get(field, "") or "") for r in rows if r.get(field, "").strip()]
        if lengths:
            print(f"  {field:<22}  n={len(lengths):>5}  "
                  f"min={min(lengths):>7}  median={sorted(lengths)[len(lengths)//2]:>7}  max={max(lengths):>8}")

    # ── lawma_conf stats (only present in juribench_labeled.csv) ──────────────
    if "lawma_conf" in columns:
        print_section("LAWMA CONFIDENCE (issue_area predictions)")
        confs = []
        for r in rows:
            v = r.get("lawma_conf", "").strip()
            if v:
                try:
                    confs.append(float(v))
                except ValueError:
                    pass
        if confs:
            confs.sort()
            print(f"  n={len(confs):>5}  min={min(confs):.3f}  "
                  f"median={confs[len(confs)//2]:.3f}  mean={sum(confs)/len(confs):.3f}  max={max(confs):.3f}")

    # ── lawma_validation.csv accuracy gate (sibling file, if present) ─────────
    val_path = path.parent / "lawma_validation.csv"
    if val_path.exists():
        with open(val_path, encoding="utf-8") as f:
            val_rows = list(csv.DictReader(f))
        evaluated = [r for r in val_rows if r.get("correct", "").strip() != ""]
        correct = sum(1 for r in evaluated if r["correct"].strip().lower() == "true")
        if evaluated:
            acc = correct / len(evaluated)
            gate = "PASS" if acc >= 0.85 else "FAIL"
            print_section("LAWMA VALIDATION GATE (lawma_validation.csv)")
            print(f"  Accuracy vs SCDB ground truth : {correct}/{len(evaluated)} = {acc:.1%}")
            print(f"  Required gate (implementation-details.md) : ≥85%  →  {gate}")

    print()


if __name__ == "__main__":
    main()

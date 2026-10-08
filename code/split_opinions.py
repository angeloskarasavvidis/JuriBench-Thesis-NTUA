#!/usr/bin/env python3
"""
split_opinions.py — Διαχωρισμός γνωμών ανά υπόθεση (αίτημα Κόνιαρη, 2026-10-08)
-------------------------------------------------------------------------------
Πριν: το opinion_text είχε ΜΙΑ γνώμη ανά υπόθεση (την «καλύτερη»), συχνά με
ενωμένα majority + dissent + concurrence (π.χ. Thompson v. Clark τελειώνει με dissent).

Μετά (στο juribench_cases.csv αλλάζουν/προστίθενται ΜΟΝΟ αυτά):
  opinion_text      → μόνο η majority (020lead)
  dissent_text      → όλα τα 040dissent (κενό αν δεν υπάρχουν)
  concurrence_text  → όλα τα 030concurrence (κενό αν δεν υπάρχουν)
  combined_only     → 1 αν η υπόθεση έχει μόνο 010combined (το κείμενο μένει ως έχει
                      στο opinion_text), αλλιώς 0
Πολλαπλές γνώμες ίδιου τύπου ενώνονται με μία κενή γραμμή (σειρά: opinion id).

Τύποι CourtListener που ΔΕΝ όρισε ρητά ο καθηγητής (εκκρεμεί επιβεβαίωση, tasks.md A3)
— default χειρισμός, ρυθμίζεται με flags:
  025plurality, 015unamimous  → majority αν ΔΕΝ υπάρχει 020lead (--no-majority-fallback για απενεργοποίηση)
  035concurrenceinpart        → concurrence_text (--concur-in-part dissent|concurrence|ignore)
  050addendum, 060remittitur, 070rehearing, 080onthemerits, 090onmotiontostrike, …
                              → αγνοούνται (μετριούνται στην αναφορά)

Διαβάζει ΜΟΝΟ τα opinions των cluster_ids του dataset (streaming, όπως το bulk_filter).
Γράφει in-place με αυτόματο backup (<όνομα>.pre_split.csv) + αναφορά markdown.

Usage:
  python code/split_opinions.py --opinions /data/mkoniaris/akar/bulk/opinions-2026-06-30.csv.bz2
  python code/split_opinions.py --opinions ... --report data/split_report.md
"""
import argparse
import csv
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bulk_filter import opener, reader, strip_html, TEXT_FIELDS  # noqa: E402

csv.field_size_limit(sys.maxsize)

LEAD = "020lead"
MAJ_FALLBACK = ["025plurality", "015unamimous"]
CONCUR = "030concurrence"
CONCUR_IN_PART = "035concurrenceinpart"
DISSENT = "040dissent"
COMBINED = "010combined"
COURTS = ["SCOTUS", "CA5", "CA9"]


def best_text(row):
    for fld in TEXT_FIELDS:
        v = row.get(fld)
        if v:
            t = v.strip() if fld == "plain_text" else strip_html(v)
            if t:
                return t
    return ""


def join(items):
    return "\n\n".join(t for _, t in sorted(items, key=lambda x: x[0]) if t)


def oid(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return sys.maxsize


def words(t):
    return len((t or "").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opinions", required=True, help="opinions-*.csv.bz2 (bulk)")
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None, help="markdown αναφορά (default: data/split_report.md)")
    ap.add_argument("--no-majority-fallback", action="store_true",
                    help="μην χρησιμοποιείς plurality/unanimous ως majority όταν λείπει το 020lead")
    ap.add_argument("--concur-in-part", choices=["concurrence", "dissent", "ignore"],
                    default="concurrence")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    inp = Path(args.input) if args.input else root / "data" / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp
    report = Path(args.report) if args.report else root / "data" / "split_report.md"

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in ("dissent_text", "concurrence_text", "combined_only"):
        if c not in fieldnames:
            fieldnames.append(c)
    want = {str(r.get("cluster_id")) for r in rows}
    print(f"Input : {inp} | υποθέσεις: {len(rows)}")

    # ── streaming: όλες οι γνώμες των clusters μας ──
    ops = defaultdict(lambda: defaultdict(list))   # cid -> type -> [(id, text)]
    n = 0
    print(f"Streaming opinions: {args.opinions}")
    with opener(args.opinions) as f:
        for row in reader(f):
            n += 1
            if n % 1_000_000 == 0:
                print(f"   ...{n:,} opinions, clusters με γνώμες: {len(ops)}")
            cid = (row.get("cluster_id") or "").strip()
            if cid in want:
                ops[cid][(row.get("type") or "").strip() or "(κενό)"].append(
                    (oid(row.get("id")), best_text(row)))
    print(f"   clusters που βρέθηκαν: {len(ops)}/{len(want)}")

    # ── ανάθεση ──
    maj_types = [LEAD] + ([] if args.no_majority_fallback else MAJ_FALLBACK)
    type_count = {c: Counter() for c in COURTS}
    ignored = Counter()
    stats = Counter()
    w_before, w_after = [], []
    for r in rows:
        jur = r.get("jurisdiction", "")
        t = ops.get(str(r.get("cluster_id")))
        old = r.get("opinion_text", "")
        if not t:
            stats["χωρίς γνώμες στο bulk (κράτησα το παλιό κείμενο)"] += 1
            r.setdefault("dissent_text", ""); r.setdefault("concurrence_text", "")
            r["combined_only"] = ""
            continue
        for ty, items in t.items():
            if jur in type_count:
                type_count[jur][ty] += len(items)

        maj = next((ty for ty in maj_types if t.get(ty)), None)
        dis = list(t.get(DISSENT, []))
        con = list(t.get(CONCUR, []))
        if t.get(CONCUR_IN_PART):
            if args.concur_in_part == "concurrence":
                con += t[CONCUR_IN_PART]
            elif args.concur_in_part == "dissent":
                dis += t[CONCUR_IN_PART]

        if maj:
            new_text, combined = join(t[maj]), "0"
            if maj != LEAD:
                stats[f"majority από {maj} (δεν υπήρχε 020lead)"] += 1
            if len(t[maj]) > 1:
                stats["πολλαπλές majority γνώμες (ενώθηκαν)"] += 1
            if t.get(COMBINED):
                stats["είχε και 010combined (αγνοήθηκε, υπάρχει majority)"] += 1
        elif t.get(COMBINED):
            new_text, combined = join(t[COMBINED]), "1"
        else:
            new_text, combined = old, ""
            stats["χωρίς majority/combined (κράτησα το παλιό κείμενο)"] += 1

        handled = set(maj_types) | {DISSENT, CONCUR, CONCUR_IN_PART, COMBINED}
        for ty, items in t.items():
            if ty not in handled:
                ignored[ty] += len(items)

        w_before.append(words(old)); w_after.append(words(new_text))
        r["opinion_text"] = new_text
        r["dissent_text"] = join(dis)
        r["concurrence_text"] = join(con)
        r["combined_only"] = combined
        stats["combined_only=1"] += combined == "1"
        stats["με dissent"] += bool(r["dissent_text"])
        stats["με concurrence"] += bool(r["concurrence_text"])
        stats["opinion_text < 200 λέξεις μετά τον διαχωρισμό"] += 0 < words(new_text) < 200

    # ── backup + write ──
    if out == inp:
        bak = inp.with_name(inp.stem + ".pre_split.csv")
        if not bak.exists():
            shutil.copy2(inp, bak)
            print(f"Backup → {bak}")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    # ── αναφορά ──
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
    L = [f"# Αναφορά διαχωρισμού γνωμών — `{out.name}`", "",
         f"**Υποθέσεις:** {len(rows)} · βρέθηκαν στο bulk: {len(ops)}", "",
         "## Αποτέλεσμα", "", "| Μέτρηση | Πλήθος |", "|---|---|"]
    for k in ["με dissent", "με concurrence", "combined_only=1"]:
        L.append(f"| {k} | {stats[k]} |")
    for k, v in stats.items():
        if k not in ("με dissent", "με concurrence", "combined_only=1"):
            L.append(f"| {k} | {v} |")
    L += ["", f"**Median λέξεις opinion_text:** πριν {med(w_before)} → μετά {med(w_after)}", "",
          "## Τύποι γνωμών ανά δικαστήριο (πλήθος γνωμών)", "",
          "| Τύπος | " + " | ".join(COURTS) + " | Χειρισμός |", "|---|" + "---|" * (len(COURTS) + 1)]
    all_types = sorted(set().union(*[set(c) for c in type_count.values()]))
    for ty in all_types:
        if ty == LEAD:
            how = "opinion_text"
        elif ty in MAJ_FALLBACK:
            how = "opinion_text αν λείπει 020lead" if not args.no_majority_fallback else "αγνοείται"
        elif ty == CONCUR:
            how = "concurrence_text"
        elif ty == CONCUR_IN_PART:
            how = {"concurrence": "concurrence_text", "dissent": "dissent_text", "ignore": "αγνοείται"}[args.concur_in_part]
        elif ty == DISSENT:
            how = "dissent_text"
        elif ty == COMBINED:
            how = "opinion_text + combined_only=1 (μόνο αν δεν υπάρχει majority)"
        else:
            how = "αγνοείται"
        L.append(f"| `{ty}` | " + " | ".join(str(type_count[c][ty]) for c in COURTS) + f" | {how} |")
    if ignored:
        L += ["", "**Αγνοήθηκαν:** " + ", ".join(f"`{k}` {v}" for k, v in ignored.most_common())]
    text = "\n".join(L)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    print(f"\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

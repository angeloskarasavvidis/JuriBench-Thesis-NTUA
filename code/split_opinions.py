#!/usr/bin/env python3
"""
split_opinions.py — Διαχωρισμός γνωμών ανά υπόθεση (αίτημα Κόνιαρη, 2026-10-08)
-------------------------------------------------------------------------------
Πριν: το opinion_text είχε ΜΙΑ γνώμη ανά υπόθεση, συχνά με ενωμένα majority +
dissent + concurrence (π.χ. Thompson v. Clark τελειώνει με dissent).

Μετά (στο juribench_cases.csv):
  opinion_text      → μόνο η majority (020lead)
  dissent_text      → όλα τα 040dissent (κενό αν δεν υπάρχουν)
  concurrence_text  → όλα τα 030concurrence (κενό αν δεν υπάρχουν)
  combined_only     → 1 αν η υπόθεση έχει μόνο 010combined, αλλιώς 0
  split_method      → type        : διαχωρισμός από το πεδίο type του CourtListener
                      text_regex  : combined κείμενο χωρίστηκε από τις επικεφαλίδες
                                    («JUSTICE X, dissenting», «Y, Circuit Judge, concurring»)
                      none        : combined χωρίς αναγνωρίσιμες ξεχωριστές γνώμες (ως έχει)
Πολλαπλές γνώμες ίδιου τύπου ενώνονται με μία κενή γραμμή (σειρά: opinion id / θέση).

Τύποι που δεν όρισε ρητά ο καθηγητής (tasks.md A3) — default, ρυθμίζεται με flags:
  025plurality, 015unamimous → majority μόνο αν λείπει 020lead (--no-majority-fallback)
  035concurrenceinpart       → concurrence_text (--concur-in-part concurrence|dissent|ignore)
  υπόλοιποι (addendum, rehearing, …) → αγνοούνται (μετρώνται στην αναφορά)

ΠΡΟΝΟΙΑ: στο πρώτο τρέξιμο αποθηκεύει ΟΛΕΣ τις γνώμες των υποθέσεών μας στο
data/opinions_by_type.jsonl.gz. Κάθε επόμενο τρέξιμο (άλλες επιλογές) γίνεται με
--from-dump σε λίγα λεπτά, ΧΩΡΙΣ νέο streaming των 50GB. Το input διαβάζεται πάντα από
το backup (<όνομα>.pre_split.csv), ώστε τα επαναληπτικά τρεξίματα να είναι ισοδύναμα.

Usage:
  # 1ο τρέξιμο (streaming, ώρες):
  python code/split_opinions.py --opinions /data/mkoniaris/akar/bulk/opinions-2026-06-30.csv.bz2
  # επόμενα (λεπτά):
  python code/split_opinions.py --from-dump data/opinions_by_type.jsonl.gz [--concur-in-part dissent] [--no-text-split]
"""
import argparse
import csv
import gzip
import json
import re
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

# Αρχή ξεχωριστής γνώμης μέσα σε combined κείμενο (το κείμενο έχει ενωμένα κενά).
# SCOTUS: «JUSTICE ALITO, with whom JUSTICE THOMAS joins, dissenting.» (ΟΧΙ «ALITO, J., dissenting»
#         που είναι κεφαλίδα σελίδας / παραπομπή).
# Circuits: «JONES, Circuit Judge, dissenting:»
KW = r"(con-?\s*cur-?\s*ring|dis-?\s*sent-?\s*ing)\b"   # και «dis- senting» (παύλα αλλαγής γραμμής)
SEP_PATTERNS = [
    # «JUSTICE X, dissenting.» · «Justice X, with whom … join, and with whom … joins as to Parts II, III, and IV, dissenting.»
    re.compile(r"(?:(?i:chief)\s+)?(?i:justice)\s+[A-Z][A-Za-z'\-]+"
               r"(?:\s*,\s*with\s+whom\s+[^:;]{0,400}?)?\s*,\s*" + KW),
    # «JONES, Circuit Judge, dissenting:» · «RICHMAN, Chief Judge, dissenting» ·
    # «ELROD, Circuit Judge, joined by SMITH, …, Circuit Judges, dissenting:» · «…, with whom … join, …»
    # + καταλήξεις/αρχικά μετά το επώνυμο: «GRAVES, JR., Circuit Judge», «NELSON, R., Circuit Judge»
    # + σκέτο «Judge» (by designation): «BAKER, Judge, concurring in part»
    re.compile(r"\b[A-Z][A-Za-z'\-]+(?:\s*,\s*(?:Jr|JR|Sr|SR|III|II|IV|[A-Z](?:\.[A-Z])*)\.?)?\s*,\s*"
               r"(?:(?:Chief|Senior|Circuit|District)\s+){0,2}Judges?\s*,\s*"
               r"(?:(?:with\s+whom\s+[^:;]{0,400}?\s+joins?|joined\s+by\s+[^:;]{0,400}?)\s*,\s*)?" + KW),
]
# 1–3 tokens ονόματος/αρχικών ακριβώς πριν το επώνυμο (π.χ. «Andrew S. », «Rhesa Hawkins »)·
# ΟΧΙ λέξεις όλο κεφαλαία (AFFIRMED) ούτε το «JUSTICE»
NAME_BEFORE = re.compile(r"(?:(?<![A-Za-z])(?:[A-Z][A-Za-z]+|[A-Z]\.)\s+){1,3}$")
# λέξεις που ΔΕΝ είναι ονόματα, αν τύχει να βρίσκονται ακριβώς πριν την επικεφαλίδα
NOT_NAMES = {"AFFIRMED", "AFFIRM", "REVERSED", "REVERSE", "VACATED", "VACATE", "REMANDED",
             "DENIED", "DISMISSED", "GRANTED", "ORDERED", "CLERK", "APPEALS", "COURT", "OPINION",
             "JUSTICE", "JUDGE", "PER", "CURIAM", "THE", "AND", "OF", "No"}


def name_prefix_len(before):
    """Μήκος του ονόματος/αρχικών ακριβώς πριν το επώνυμο (πετά λέξεις του NOT_NAMES)."""
    m = NAME_BEFORE.search(before)
    if not m:
        return 0
    toks = m.group(0).split()
    while toks and toks[0].rstrip(".") in NOT_NAMES:
        toks.pop(0)
    if not toks:
        return 0
    i = before.rfind(toks[0], m.start())
    return len(before) - i
MIN_MAJ_FRAC = 0.15    # η 1η ξεχωριστή γνώμη πρέπει να ξεκινά μετά το 15% του κειμένου
MIN_MAJ_WORDS = 300     # και η majority να έχει ≥300 λέξεις
MIN_GAP = 300           # αγνόησε matches πιο κοντά από 300 χαρακτήρες στο προηγούμενο


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


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"-\s+", "", s.lower()))   # «dis- senting» → «dissenting»


def classify(m_text, tail):
    s = _norm(m_text + " " + tail)
    # «concurring in part and dissenting in part» · «concurring in the judgment in part and dissenting in part»
    if "in part" in s and "concurring" in s and "dissenting" in s:
        return CONCUR_IN_PART
    return DISSENT if _norm(m_text).rstrip().endswith("dissenting") else CONCUR


def find_separate_opinions(text):
    """Επιστρέφει [(start, type)] για τις αρχές ξεχωριστών γνωμών μέσα σε κείμενο."""
    hits = []
    for pat in SEP_PATTERNS:
        for m in pat.finditer(text):
            start = m.start()
            # παραπομπή μέσα σε παρένθεση «(Jones, Judge, dissenting)» → ΟΧΙ αρχή γνώμης
            lo = max(0, start - 120)
            if text.rfind("(", lo, start) > text.rfind(")", lo, start):
                continue
            # «Andrew S. Oldham, Circuit Judge, dissenting» → συμπερίλαβε μικρό όνομα / αρχικά
            start -= name_prefix_len(text[max(0, start - 50):start])
            hits.append((start, classify(m.group(0), text[m.end():m.end() + 60])))
    hits.sort()
    out, last = [], -10**9
    for pos, ty in hits:
        if pos - last >= MIN_GAP:
            out.append((pos, ty)); last = pos
    return out


def text_split(text):
    """Combined κείμενο → (majority, [(pos, type, text)]) ή None αν δεν είναι ασφαλές."""
    seps = [s for s in find_separate_opinions(text) if s[0] >= MIN_MAJ_FRAC * len(text)]
    if not seps or words(text[:seps[0][0]]) < MIN_MAJ_WORDS:
        return None
    maj = text[:seps[0][0]].strip()
    parts = []
    for i, (pos, ty) in enumerate(seps):
        end = seps[i + 1][0] if i + 1 < len(seps) else len(text)
        parts.append((pos, ty, text[pos:end].strip()))
    return maj, parts


# ── φόρτωση γνωμών ──────────────────────────────────────────────────────────
def load_stream(path, want, dump_path):
    ops = defaultdict(lambda: defaultdict(list))
    n = 0
    print(f"Streaming opinions: {path}")
    with opener(path) as f:
        for row in reader(f):
            n += 1
            if n % 1_000_000 == 0:
                print(f"   ...{n:,} opinions, clusters με γνώμες: {len(ops)}")
            cid = (row.get("cluster_id") or "").strip()
            if cid in want:
                ty = (row.get("type") or "").strip() or "(κενό)"
                ops[cid][ty].append((oid(row.get("id")), best_text(row),
                                     (row.get("author_str") or "").strip()))
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dump_path, "wt", encoding="utf-8") as g:
        for cid, by_t in ops.items():
            g.write(json.dumps({"cluster_id": cid, "opinions": [
                {"id": i, "type": ty, "author_str": a, "text": t}
                for ty, items in by_t.items() for i, t, a in items]}, ensure_ascii=False) + "\n")
    print(f"   Dump → {dump_path} (επόμενα τρεξίματα: --from-dump, χωρίς streaming)")
    return ops


def load_dump(path, want):
    ops = defaultdict(lambda: defaultdict(list))
    with gzip.open(path, "rt", encoding="utf-8") as g:
        for line in g:
            d = json.loads(line)
            if d["cluster_id"] in want:
                for o in d["opinions"]:
                    ops[d["cluster_id"]][o["type"]].append((o["id"], o["text"], o.get("author_str", "")))
    print(f"Από dump: {path}")
    return ops


def run_from_csv(target, out, report):
    """Διαχωρισμός από το κείμενο, κατευθείαν στο dataset (χωρίς bulk).
    Προϋπόθεση: έχει ήδη γίνει ο type-split (υπάρχουν combined_only/dissent_text/concurrence_text).
    Οι γραμμές combined_only=0 (από type) μένουν ως έχουν· οι combined_only=1 χωρίζονται.
    Διαβάζει πάντα από <όνομα>.pre_textsplit.csv → επαναλήψιμο."""
    bak = target.with_name(target.stem + ".pre_textsplit.csv")
    if not bak.exists():
        shutil.copy2(target, bak)
        print(f"Backup → {bak}")
    with open(bak, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in ("dissent_text", "concurrence_text", "combined_only"):
        if c not in fieldnames:
            raise SystemExit(f"Λείπει η στήλη {c}: τρέξε πρώτα τον type-split (--opinions).")
    if "split_method" not in fieldnames:
        fieldnames.append("split_method")
    print(f"Input : {bak} | υποθέσεις: {len(rows)}")

    method = {c: Counter() for c in COURTS}
    stats = Counter()
    w_before, w_after = [], []
    for r in rows:
        jur = r.get("jurisdiction", "")
        comb = (r.get("combined_only") or "").strip()
        old = r.get("opinion_text", "")
        if comb == "1":
            sp = text_split(old)
            if sp:
                maj, parts = sp
                dis = [(p, t) for p, ty, t in parts if ty == DISSENT]
                con = [(p, t) for p, ty, t in parts if ty in (CONCUR, CONCUR_IN_PART)]
                r.update(opinion_text=maj, dissent_text=join(dis), concurrence_text=join(con),
                         split_method="text_regex")
                stats["concurrence in part (text) → concurrence_text"] += sum(
                    1 for _, ty, _ in parts if ty == CONCUR_IN_PART)
            else:
                r["split_method"] = "none"
            key = "combined→" + r["split_method"]
        elif comb == "0":
            r["split_method"] = "type"; key = "type"
        else:
            r["split_method"] = "none"; key = "none (χωρίς γνώμες στο bulk)"
        if jur in method:
            method[jur][key] += 1
        w_before.append(words(old)); w_after.append(words(r["opinion_text"]))
        stats["με dissent"] += bool((r.get("dissent_text") or "").strip())
        stats["με concurrence"] += bool((r.get("concurrence_text") or "").strip())
        stats["opinion_text < 200 λέξεις"] += 0 < words(r["opinion_text"]) < 200

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
    L = [f"# Αναφορά διαχωρισμού γνωμών (text-split) — `{out.name}`", "",
         f"**Υποθέσεις:** {len(rows)}", "", "## Μέθοδος ανά δικαστήριο", "",
         "| Μέθοδος | " + " | ".join(COURTS) + " |", "|---|" + "---|" * len(COURTS)]
    for mth in sorted(set().union(*[set(m) for m in method.values()])):
        L.append(f"| {mth} | " + " | ".join(str(method[c][mth]) for c in COURTS) + " |")
    L += ["", "## Αποτέλεσμα", "", "| Μέτρηση | Πλήθος |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in stats.items()]
    L += ["", f"**Median λέξεις opinion_text:** πριν {med(w_before)} → μετά {med(w_after)}"]
    text = "\n".join(L)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text + f"\n\nSaved -> {out}\nReport -> {report}")


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--opinions", help="opinions-*.csv.bz2 (bulk) — 1ο τρέξιμο, γράφει dump")
    src.add_argument("--from-dump", help="data/opinions_by_type.jsonl.gz — γρήγορα επαναληπτικά τρεξίματα")
    src.add_argument("--from-csv", action="store_true",
                     help="ΧΩΡΙΣ bulk: εφαρμόζει μόνο τον διαχωρισμό από το κείμενο στις γραμμές "
                          "combined_only=1 του ήδη type-split juribench_cases.csv (λεπτά)")
    ap.add_argument("--dump", default=None, help="πού γράφεται το dump (default: data/opinions_by_type.jsonl.gz)")
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--no-majority-fallback", action="store_true")
    ap.add_argument("--concur-in-part", choices=["concurrence", "dissent", "ignore"], default="concurrence")
    ap.add_argument("--no-text-split", action="store_true",
                    help="μην χωρίζεις τα 010combined από το κείμενο (μένουν ως έχουν)")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    data = root / "data"
    target = Path(args.input) if args.input else data / "juribench_cases.csv"
    out = Path(args.output) if args.output else target
    report = Path(args.report) if args.report else data / "split_report.md"
    dump = Path(args.dump) if args.dump else data / "opinions_by_type.jsonl.gz"

    if args.from_csv:
        return run_from_csv(target, out, report)

    # Πάντα από το ΠΡΙΝ-τον-διαχωρισμό αρχείο → επαναλήψιμο
    bak = target.with_name(target.stem + ".pre_split.csv")
    if not bak.exists():
        shutil.copy2(target, bak)
        print(f"Backup → {bak}")
    with open(bak, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in ("dissent_text", "concurrence_text", "combined_only", "split_method"):
        if c not in fieldnames:
            fieldnames.append(c)
    want = {str(r.get("cluster_id")) for r in rows}
    print(f"Input : {bak} | υποθέσεις: {len(rows)}")

    raw = load_stream(args.opinions, want, dump) if args.opinions else load_dump(args.from_dump, want)
    ops = {cid: {ty: [(i, t) for i, t, _ in items] for ty, items in by_t.items()} for cid, by_t in raw.items()}
    print(f"   clusters με γνώμες: {len(ops)}/{len(want)}")

    maj_types = [LEAD] + ([] if args.no_majority_fallback else MAJ_FALLBACK)
    handled = set(maj_types) | {DISSENT, CONCUR, CONCUR_IN_PART, COMBINED}
    type_count = {c: Counter() for c in COURTS}
    ignored, stats = Counter(), Counter()
    method = {c: Counter() for c in COURTS}
    w_before, w_after = [], []

    def route(dis, con, ty, item):
        if ty == DISSENT:
            dis.append(item)
        elif ty == CONCUR:
            con.append(item)
        elif ty == CONCUR_IN_PART:
            if args.concur_in_part == "concurrence":
                con.append(item)
            elif args.concur_in_part == "dissent":
                dis.append(item)

    for r in rows:
        jur = r.get("jurisdiction", "")
        old = r.get("opinion_text", "")
        t = ops.get(str(r.get("cluster_id")))
        if not t:
            r.update(dissent_text="", concurrence_text="", combined_only="", split_method="none")
            stats["χωρίς γνώμες στο bulk (κράτησα το παλιό κείμενο)"] += 1
            continue
        for ty, items in t.items():
            if jur in type_count:
                type_count[jur][ty] += len(items)
            if ty not in handled:
                ignored[ty] += len(items)

        dis, con = [], []
        for ty in (DISSENT, CONCUR, CONCUR_IN_PART):
            for item in t.get(ty, []):
                route(dis, con, ty, item)

        maj = next((ty for ty in maj_types if t.get(ty)), None)
        if maj:
            new_text, combined, how = join(t[maj]), "0", "type"
            if maj != LEAD:
                stats[f"majority από {maj} (δεν υπήρχε 020lead)"] += 1
            if len(t[maj]) > 1:
                stats["πολλαπλές majority γνώμες (ενώθηκαν)"] += 1
            if find_separate_opinions(new_text) and text_split(new_text):
                stats["⚠ majority (type) που μοιάζει να περιέχει ξεχωριστή γνώμη — έλεγχος"] += 1
        elif t.get(COMBINED):
            comb = join(t[COMBINED])
            combined = "1"
            sp = None if args.no_text_split else text_split(comb)
            if sp:
                new_text, parts = sp
                for pos, ty, txt in parts:
                    route(dis, con, ty, (pos, txt))
                how = "text_regex"
            else:
                new_text, how = comb, "none"
        else:
            new_text, combined, how = old, "", "none"
            stats["χωρίς majority/combined (κράτησα το παλιό κείμενο)"] += 1

        w_before.append(words(old)); w_after.append(words(new_text))
        r.update(opinion_text=new_text, dissent_text=join(dis), concurrence_text=join(con),
                 combined_only=combined, split_method=how)
        if jur in method:
            method[jur][how if combined != "1" else f"combined→{how}"] += 1
        stats["με dissent"] += bool(r["dissent_text"])
        stats["με concurrence"] += bool(r["concurrence_text"])
        stats["combined_only=1"] += combined == "1"
        stats["opinion_text < 200 λέξεις"] += 0 < words(new_text) < 200

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
         f"**Υποθέσεις:** {len(rows)} · με γνώμες στο bulk: {len(ops)} · "
         f"text-split: {'ΟΧΙ' if args.no_text_split else 'ΝΑΙ'} · concur-in-part → {args.concur_in_part}", "",
         "## Μέθοδος ανά δικαστήριο", "", "| Μέθοδος | " + " | ".join(COURTS) + " |",
         "|---|" + "---|" * len(COURTS)]
    for mth in sorted(set().union(*[set(m) for m in method.values()])):
        L.append(f"| {mth} | " + " | ".join(str(method[c][mth]) for c in COURTS) + " |")
    L += ["", "## Αποτέλεσμα", "", "| Μέτρηση | Πλήθος |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in stats.items()]
    L += ["", f"**Median λέξεις opinion_text:** πριν {med(w_before)} → μετά {med(w_after)}", "",
          "## Τύποι γνωμών ανά δικαστήριο (πλήθος γνωμών)", "",
          "| Τύπος | " + " | ".join(COURTS) + " |", "|---|" + "---|" * len(COURTS)]
    for ty in sorted(set().union(*[set(c) for c in type_count.values()])):
        L.append(f"| `{ty}` | " + " | ".join(str(type_count[c][ty]) for c in COURTS) + " |")
    if ignored:
        L += ["", "**Αγνοήθηκαν:** " + ", ".join(f"`{k}` {v}" for k, v in ignored.most_common())]
    text = "\n".join(L)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

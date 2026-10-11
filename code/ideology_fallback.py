#!/usr/bin/env python3
"""
ideology_fallback.py — Fallback ιδεολογίας για circuit δικαστές (αίτημα Κόνιαρη, 2026-10-08)
-------------------------------------------------------------------------------------------
Νέες στήλες (ΔΕΝ αλλάζουν τα ideology / ideology_score):
  ideology_fallback         → JCS score του δικαστή· αν δεν βρεθεί στο JCS, το κόμμα του
                              Προέδρου που τον διόρισε (R / D)
  ideology_fallback_source  → jcs | party
Γεμίζουν για ΟΛΕΣ τις circuit υποθέσεις (CA5/CA9) όπου ο συγγραφέας αναγνωρίζεται,
ώστε να συγκριθούν με το JuDJIS. Τα SCOTUS μένουν κενά.

Πηγές (ακαδημαϊκές/επίσημες, ΚΑΘΟΛΟΥ LLM):
  data/jcs/jcs 2024/csv/coa_judges_2024.csv   (Epstein, Martin, Segal, Westerland — JCS 2024)
  data/fjc/judges.csv                          (FJC Biographical Directory, flat export)

Αναγνώριση δικαστή (author_str = επώνυμο από byline):
  FJC: ίδιο επώνυμο + διορισμός στο ΙΔΙΟ circuit (CA5/CA9) + εν ενεργεία στη date_filed
       (commission ≤ date ≤ termination). Αν 0 με ημερομηνία → χωρίς ημερομηνία, μόνο αν μοναδικός.
       ≥2 υποψήφιοι → αμφίσημο → κενό.
  JCS: ίδιο επώνυμο + ίδιο circuit + ίδιο μικρό όνομα (από το FJC)· αν δεν βρέθηκε δικαστής στο
       FJC → JCS μόνο αν το επώνυμο είναι μοναδικό στο circuit.
  District judges by designation (δεν έχουν διορισμό στο CA5/CA9) → κενό (στενή ανάγνωση, Q7).

Usage:
  python code/ideology_fallback.py            # in-place στο data/juribench_cases.csv (+ backup)
"""
import argparse
import csv
import math
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
JCS_PATH = DATA / "jcs" / "jcs 2024" / "csv" / "coa_judges_2024.csv"
FJC_PATH = DATA / "fjc" / "judges.csv"
CIRCUIT_OF = {"CA5": 5, "CA9": 9}
COURT_WORD = {5: "fifth", 9: "ninth"}
PARTY = {"republican": "R", "democratic": "D", "democrat": "D"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def first_token(s):
    for t in re.split(r"[\s,]+", s or ""):
        if t and norm(t) not in ("jr", "sr", "ii", "iii", "iv") and len(norm(t)) > 1:
            return norm(t)
    return ""


def parse_date(s):
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)          # FJC: mm/dd/yyyy
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)              # dataset: ISO
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def open_any(path):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            f = open(path, encoding=enc, newline="")
            f.read(4096); f.seek(0)
            return f
        except UnicodeDecodeError:
            f.close()
    raise SystemExit(f"Δεν διαβάζεται: {path}")


def load_fjc():
    """→ {circuit: [ {last, first, start, end, party, raw_party, name} ]} για CA5/CA9."""
    with open_any(FJC_PATH) as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames
        ks = sorted({int(m.group(1)) for c in cols if (m := re.match(r"Court Name \((\d+)\)$", c))})
        print(f"FJC: {len(cols)} στήλες · διορισμοί ανά δικαστή: {ks}")
        for need in ("Commission Date (1)", "Termination Date (1)", "Party of Appointing President (1)"):
            if need not in cols:
                print(f"  ⚠ ΛΕΙΠΕΙ η στήλη «{need}» — έλεγξε τα ονόματα στηλών του FJC πριν εμπιστευτείς το αποτέλεσμα")
        out = defaultdict(list)
        for r in rd:
            for k in ks:
                court = (r.get(f"Court Name ({k})") or "").lower()
                if "court of appeals" not in court:
                    continue
                for c, word in COURT_WORD.items():
                    if word in court:
                        raw = (r.get(f"Party of Appointing President ({k})") or "").strip()
                        out[c].append({
                            "last": norm(r.get("Last Name")),
                            "first": first_token(r.get("First Name")),
                            "start": parse_date(r.get(f"Commission Date ({k})")),
                            "end": parse_date(r.get(f"Termination Date ({k})")),
                            "party": PARTY.get(raw.lower(), ""),
                            "raw_party": raw,
                            "name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
                        })
    return out


def load_jcs():
    """→ {(circuit, last): [(first, score, name)]}"""
    idx = defaultdict(list)
    with open_any(JCS_PATH) as f:
        for r in csv.DictReader(f):
            name = r.get("name") or ""
            last, _, rest = name.partition(",")
            try:
                circ, score = int(float(r.get("circuit"))), float(r.get("jcs"))
            except (TypeError, ValueError):
                continue
            idx[(circ, norm(last))].append((first_token(rest), score, name))
    return idx


def identify(cands, d):
    """Μοναδικός υποψήφιος εν ενεργεία στη d· αλλιώς μοναδικός γενικά· αλλιώς None/'ambiguous'."""
    if not cands:
        return None
    active = [c for c in cands if d and c["start"] and c["start"] <= d and (c["end"] is None or d <= c["end"])]
    pool = active if active else cands
    uniq = {(c["last"], c["first"]): c for c in pool}
    return list(uniq.values())[0] if len(uniq) == 1 else "ambiguous"


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    inp = Path(args.input) if args.input else DATA / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp
    report = Path(args.report) if args.report else DATA / "ideology_fallback_report.md"
    bak = inp.with_name(inp.stem + ".pre_fallback.csv")
    if out == inp and not bak.exists():
        shutil.copy2(inp, bak); print(f"Backup → {bak}")

    fjc, jcs = load_fjc(), load_jcs()
    print(f"FJC δικαστές: CA5 {len(fjc[5])} · CA9 {len(fjc[9])} · JCS εγγραφές: {sum(len(v) for v in jcs.values())}")

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in ("ideology_fallback", "ideology_fallback_source"):
        if c not in fieldnames:
            fieldnames.append(c)

    st = {k: Counter() for k in CIRCUIT_OF}
    miss_names, amb_names, other_party = Counter(), Counter(), Counter()
    cmp_x, cmp_y, sign_agree, sign_n = [], [], 0, 0
    for r in rows:
        r["ideology_fallback"] = r["ideology_fallback_source"] = ""
        jur = r.get("jurisdiction")
        if jur not in CIRCUIT_OF:
            continue
        circ, s = CIRCUIT_OF[jur], st[jur]
        s["υποθέσεις"] += 1
        a = norm(r.get("author_str"))
        if not a:
            s["χωρίς author_str"] += 1; continue
        judge = identify([c for c in fjc[circ] if c["last"] == a], parse_date(r.get("date_filed")))
        if judge == "ambiguous":
            s["αμφίσημο (≥2 δικαστές ίδιο επώνυμο)"] += 1; amb_names[f"{jur} {r.get('author_str')}"] += 1; continue
        jc = jcs.get((circ, a), [])
        hit = None
        if judge:
            hits = [x for x in jc if x[0] and judge["first"] and (x[0][:3] == judge["first"][:3])]
            hit = hits[0] if len(hits) == 1 else None
        elif len(jc) == 1:
            hit = jc[0]
        if hit:
            r["ideology_fallback"], r["ideology_fallback_source"] = hit[1], "jcs"
            s["jcs"] += 1
            try:
                j = float(r.get("ideology_score") or "")
                cmp_x.append(j); cmp_y.append(hit[1])
                sign_n += 1; sign_agree += (j > 0) == (hit[1] > 0)
            except ValueError:
                pass
        elif judge and judge["party"]:
            r["ideology_fallback"], r["ideology_fallback_source"] = judge["party"], "party"
            s["party"] += 1
        elif judge:
            s["δικαστής στο FJC, κόμμα όχι R/D"] += 1; other_party[judge["raw_party"] or "(κενό)"] += 1
        else:
            s["δεν βρέθηκε (εκτός CA5/CA9 roster — π.χ. by designation)"] += 1
            miss_names[f"{jur} {r.get('author_str')}"] += 1

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    keys = ["υποθέσεις", "jcs", "party", "χωρίς author_str", "αμφίσημο (≥2 δικαστές ίδιο επώνυμο)",
            "δεν βρέθηκε (εκτός CA5/CA9 roster — π.χ. by designation)", "δικαστής στο FJC, κόμμα όχι R/D"]
    L = [f"# Ideology fallback (JCS / κόμμα Προέδρου) — `{out.name}`", "",
         "| | CA5 | CA9 | Σύνολο |", "|---|---|---|---|"]
    for k in keys:
        L.append(f"| {k} | {st['CA5'][k]} | {st['CA9'][k]} | {st['CA5'][k] + st['CA9'][k]} |")
    filled = {j: st[j]["jcs"] + st[j]["party"] for j in CIRCUIT_OF}
    L.append(f"| **ideology_fallback συμπληρωμένο** | **{filled['CA5']}** | **{filled['CA9']}** | "
             f"**{filled['CA5'] + filled['CA9']}** |")
    r_ = pearson(cmp_x, cmp_y)
    L += ["", "## Σύγκριση με JuDJIS (υποθέσεις με JuDJIS score ΚΑΙ JCS)", "",
          f"- Ζεύγη: {len(cmp_x)} · Pearson r = {r_:.3f}" if r_ is not None else f"- Ζεύγη: {len(cmp_x)}",
          f"- Συμφωνία πρόσημου (φιλελεύθερος/συντηρητικός): {sign_agree}/{sign_n}"
          + (f" ({sign_agree / sign_n:.1%})" if sign_n else "")]
    if amb_names:
        L += ["", "## Αμφίσημα (top 15)", ""] + [f"- {k}: {v}" for k, v in amb_names.most_common(15)]
    if miss_names:
        L += ["", "## Δεν βρέθηκαν στο CA5/CA9 roster (top 20)", ""] + [f"- {k}: {v}" for k, v in miss_names.most_common(20)]
    if other_party:
        L += ["", "**Κόμματα εκτός R/D:** " + ", ".join(f"{k} {v}" for k, v in other_party.items())]
    text = "\n".join(L)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

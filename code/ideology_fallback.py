#!/usr/bin/env python3
"""
ideology_fallback.py — Fallback ιδεολογίας για circuit δικαστές (οδηγίες καθηγητή 2026-10-08 / 2026-10-12)
--------------------------------------------------------------------------------------------------------
Στήλες (ΔΕΝ αλλάζουν τα ideology / ideology_score):
  ideology_fallback         → JCS score· αλλιώς κόμμα του Προέδρου που διόρισε (R / D)
  ideology_fallback_source  → jcs        : δικαστής του ίδιου circuit, βρέθηκε στο JCS
                              party      : δικαστής του ίδιου circuit, όχι στο JCS → κόμμα (FJC)
                              party_fjc  : δικαστής BY DESIGNATION (district / άλλου circuit) → κόμμα (FJC)
  author_visiting           → 1 by designation · 0 δικαστής του ίδιου circuit · κενό αν δεν ταυτοποιήθηκε
Τα SCOTUS μένουν κενά.

Πηγές (ΚΑΘΟΛΟΥ LLM): JCS 2024 (`data/jcs/jcs 2024/csv/coa_judges_2024.csv`) · FJC Biographical
Directory (`data/fjc/judges.csv`) · κοινός πίνακας ταυτίσεων `judge_aliases.py` (Richman=Owen,
Forrest=Hunsaker, Ramirez=Carrillo Ramirez — ίδιος με JuDJIS).

Ταυτοποίηση (author_str = επώνυμο από parse_author· author_initials για συνωνυμίες, 2026-10-13):
  1. ίδιο circuit (FJC): επώνυμο (+ ταυτίσεις) + διορισμός στο CA5/CA9 + εν ενεργεία στη date_filed
     → JCS (ίδιο μικρό όνομα· ή μοναδικό επώνυμο στο circuit) ή κόμμα. ≥2 υποψήφιοι → κενό.
  2. αν δεν βρέθηκε στο ίδιο circuit: JCS μόνο αν μοναδικό επώνυμο στο circuit.
  3. αλλιώς by designation: ΟΛΑ τα δικαστήρια του FJC, εν ενεργεία στη date_filed, μοναδικό πρόσωπο
     → κόμμα, `party_fjc`, author_visiting = 1. ≥2 πρόσωπα → κενό.

Usage:  python code/ideology_fallback.py
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

sys.path.insert(0, str(Path(__file__).parent))
from judge_aliases import surname_variants, initials_of_name, initials_ok, initials_conflict  # noqa: E402
from author_initials import signed_as_district  # noqa: E402

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
JCS_PATH = DATA / "jcs" / "jcs 2024" / "csv" / "coa_judges_2024.csv"
FJC_PATH = DATA / "fjc" / "judges.csv"
CIRCUIT_OF = {"CA5": 5, "CA9": 9}
COURT_WORD = {5: "fifth", 9: "ninth"}
PARTY = {"republican": "R", "democratic": "D", "democrat": "D"}
NEW_COLS = ["ideology_fallback", "ideology_fallback_source", "author_visiting"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def last_keys(last):
    """«O'Scannlain» → {'oscannlain','scannlain'} (το byline χάνει συχνά το «O'»)."""
    keys = {norm(last)}
    m = re.match(r"^\s*([OD])['’]\s*(.+)$", last or "", flags=re.I)
    if m:
        keys.add(norm(m.group(2)))
    return keys


def first_token(s):
    for t in re.split(r"[\s,]+", s or ""):
        if t and norm(t) not in ("jr", "sr", "ii", "iii", "iv") and len(norm(t)) > 1:
            return norm(t)
    return ""


def parse_date(s):
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
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
    """→ (own {5|9: [appt]}, every [appt]) · appt = dict(nid, keys, first, start, end, party, raw_party, name, court)"""
    own, every = defaultdict(list), []
    with open_any(FJC_PATH) as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames
        ks = sorted({int(m.group(1)) for c in cols if (m := re.match(r"Court Name \((\d+)\)$", c))})
        print(f"FJC: {len(cols)} στήλες · διορισμοί ανά δικαστή: {ks}")
        for need in ("Commission Date (1)", "Termination Date (1)", "Party of Appointing President (1)"):
            if need not in cols:
                print(f"  ⚠ ΛΕΙΠΕΙ η στήλη «{need}» — έλεγξε τα ονόματα στηλών του FJC")
        for r in rd:
            for k in ks:
                court = (r.get(f"Court Name ({k})") or "").strip()
                if not court:
                    continue
                raw = (r.get(f"Party of Appointing President ({k})") or "").strip()
                appt = {
                    "nid": r.get("nid") or f"{r.get('Last Name')}|{r.get('First Name')}",
                    "keys": last_keys(r.get("Last Name")),
                    "first": first_token(r.get("First Name")),
                    "ini": initials_of_name(r.get("First Name"), r.get("Middle Name")),
                    "start": parse_date(r.get(f"Commission Date ({k})")),
                    "end": parse_date(r.get(f"Termination Date ({k})")),
                    "party": PARTY.get(raw.lower(), ""), "raw_party": raw,
                    "name": f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip(),
                    "court": court,
                }
                every.append(appt)
                low = court.lower()
                if "court of appeals" in low:
                    for c, word in COURT_WORD.items():
                        if word in low:
                            own[c].append(appt)
    return own, every


def load_jcs():
    idx = defaultdict(list)
    with open_any(JCS_PATH) as f:
        for r in csv.DictReader(f):
            name = r.get("name") or ""
            last, _, rest = name.partition(",")
            try:
                circ, score = int(float(r.get("circuit"))), float(r.get("jcs"))
            except (TypeError, ValueError):
                continue
            for k in last_keys(last):
                idx[(circ, k)].append((first_token(rest), score, name))
    return idx


def active(c, d):
    return d and c["start"] and c["start"] <= d and (c["end"] is None or d <= c["end"])


def by_initials(vals, ini):
    """≥2 υποψήφιοι → κράτα όσους έχουν συμβατά αρχικά (FJC: μικρό + μεσαίο όνομα)."""
    if not ini:
        return vals
    if len(vals) == 1:
        return [] if initials_conflict(ini, vals[0]["ini"]) else vals
    return [c for c in vals if initials_ok(ini, c["ini"])]


def identify_own(cands, d, ini=""):
    if not cands:
        return None, []
    act = [c for c in cands if active(c, d)]
    pool = act or cands
    uniq = {(sorted(c["keys"])[0], c["first"]): c for c in pool}
    allv = list(uniq.values())
    if act and len(allv) == 1:
        # 2026-10-14 (καθηγητής): μόνο ένας εν ενεργεία με αυτό το επώνυμο τη μέρα της απόφασης →
        # αυτός, ακόμη κι αν τα αρχικά δεν ταιριάζουν (λάθος «O.» Bea, «R.» Wardlaw κ.λπ.)
        return allv[0], allv
    vals = by_initials(allv, ini)
    if not vals:
        # τα αρχικά δεν ταιριάζουν με ΚΑΝΕΝΑΝ δικαστή του circuit (π.χ. D.D. Pregerson ≠ Harry Pregerson)
        # → δεν είναι δικαστής του circuit· ψάξε ως by designation
        return "conflict", allv
    return (vals[0] if len(vals) == 1 else "ambiguous"), vals


def identify_visiting(cands, d, ini=""):
    pool = [c for c in cands if active(c, d)]
    persons = {c["nid"]: c for c in pool}
    if not persons:
        return None, []
    allv = list(persons.values())
    vals = by_initials(allv, ini)
    if not vals:
        return None, allv
    return (vals[0] if len(vals) == 1 else "ambiguous"), vals


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

    own, every = load_fjc()
    jcs = load_jcs()
    print(f"FJC: CA5 {len(own[5])} · CA9 {len(own[9])} διορισμοί · όλα τα δικαστήρια {len(every)} · "
          f"JCS εγγραφές: {sum(len(v) for v in jcs.values())}")

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)

    st = {k: Counter() for k in CIRCUIT_OF}
    amb, amb_c, vis_names, miss, party_j = Counter(), {}, Counter(), Counter(), Counter()
    cmp_x, cmp_y, sign_ok, sign_n = [], [], 0, 0
    for r in rows:
        for c in NEW_COLS:
            r[c] = ""
        jur = r.get("jurisdiction")
        if jur not in CIRCUIT_OF:
            continue
        circ, s = CIRCUIT_OF[jur], st[jur]
        s["υποθέσεις"] += 1
        a_raw = r.get("author_str") or ""
        a = norm(a_raw)
        if not a:
            s["χωρίς author_str"] += 1; continue
        variants = surname_variants(a_raw, jur) | {a}
        d = parse_date(r.get("date_filed"))

        # 1. δικαστής του ίδιου circuit
        ini = r.get("author_initials") or ""
        if signed_as_district(r.get("opinion_text"), a_raw):
            # 2026-10-14 (καθηγητής): υπογραφή «District Judge» → by designation → κατευθείαν FJC
            s["υπογραφή «District Judge» → κατευθείαν by designation"] += 1
            judge, cands = "conflict", []
        else:
            judge, cands = identify_own([c for c in own[circ] if c["keys"] & variants], d, ini)
        if judge == "ambiguous":
            s["αμφίσημο στο ίδιο circuit"] += 1
            key = f"{jur} {a}" + (f" [{ini}]" if ini else ""); amb[key] += 1; amb_c[key] = sorted({c["name"] for c in cands})
            continue
        if judge == "conflict":
            if cands:
                s["αρχικά ≠ δικαστών του circuit → αναζήτηση ως by designation"] += 1
            judge = None
            jc = []          # ΟΧΙ JCS με βάση μόνο το επώνυμο (θα ήταν ο λάθος δικαστής)
        else:
            jc = [x for v in variants for x in jcs.get((circ, v), [])]
        jc = list({x[2]: x for x in jc}.values())
        hit = None
        if judge:
            same_first = [x for x in jc if x[0] and judge["first"] and x[0][:3] == judge["first"][:3]]
            hit = same_first[0] if len(same_first) == 1 else (jc[0] if not same_first and len(jc) == 1 else None)
            if hit is not None and not same_first and initials_conflict(judge["ini"], initials_of_name(hit[2].partition(",")[2])):
                hit = None   # π.χ. Holly A. Thomas (FJC) ≠ «Thomas, Sidney R.» (JCS) → όχι JCS, πάει σε κόμμα
            if hit is None and not same_first and len(jc) > 1:   # π.χ. «N. Randy» (JCS) vs «N[orman]» (FJC)
                ok = [x for x in jc if initials_ok(judge["ini"], initials_of_name(x[2].partition(",")[2]))]
                hit = ok[0] if len(ok) == 1 else None
        elif len(jc) == 1:
            hit = jc[0]
        elif len(jc) > 1 and ini:
            ok = [x for x in jc if initials_ok(ini, initials_of_name(x[2].partition(",")[2]))]
            hit = ok[0] if len(ok) == 1 else None
        if hit:
            r.update(ideology_fallback=hit[1], ideology_fallback_source="jcs", author_visiting="0")
            s["jcs"] += 1
            try:
                j = float(r.get("ideology_score") or "")
                cmp_x.append(j); cmp_y.append(hit[1]); sign_n += 1; sign_ok += (j > 0) == (hit[1] > 0)
            except ValueError:
                pass
            continue
        if judge:
            if judge["party"]:
                r.update(ideology_fallback=judge["party"], ideology_fallback_source="party", author_visiting="0")
                s["party"] += 1; party_j[f"{jur} {judge['name']} ({judge['party']})"] += 1
            else:
                s["ίδιο circuit, κόμμα όχι R/D"] += 1
            continue

        # 3. by designation — όλα τα δικαστήρια του FJC
        district = s_dist = signed_as_district(r.get("opinion_text"), a_raw)
        pool_v = [c for c in every if c["keys"] & variants]
        if district:   # «District Judge» → μόνο διορισμοί σε District Court
            pool_v = [c for c in pool_v if "district court" in c["court"].lower()]
        vjudge, vc = identify_visiting(pool_v, d, ini)
        if vjudge == "ambiguous":
            s["by designation — αμφίσημο"] += 1
            key = f"{jur} {a} (visiting)" + (f" [{ini}]" if ini else ""); amb[key] += 1; amb_c[key] = sorted({f"{c['name']} [{c['court']}]" for c in vc})[:6]
        elif vjudge and vjudge["party"]:
            r.update(ideology_fallback=vjudge["party"], ideology_fallback_source="party_fjc", author_visiting="1")
            s["party_fjc (by designation)"] += 1
            vis_names[f"{jur} {vjudge['name']} — {vjudge['court']} ({vjudge['party']})"] += 1
        elif vjudge:
            s["by designation, κόμμα όχι R/D"] += 1
        else:
            s["δεν βρέθηκε στο FJC"] += 1; miss[f"{jur} {a_raw}"] += 1

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    keys = ["υποθέσεις", "jcs", "party", "party_fjc (by designation)", "χωρίς author_str",
            "αμφίσημο στο ίδιο circuit", "by designation — αμφίσημο", "δεν βρέθηκε στο FJC",
            "ίδιο circuit, κόμμα όχι R/D", "by designation, κόμμα όχι R/D",
            "αρχικά ≠ δικαστών του circuit → αναζήτηση ως by designation",
            "υπογραφή «District Judge» → κατευθείαν by designation"]
    L = [f"# Ideology fallback — `{out.name}`", "", "| | CA5 | CA9 | Σύνολο |", "|---|---|---|---|"]
    for k in keys:
        L.append(f"| {k} | {st['CA5'][k]} | {st['CA9'][k]} | {st['CA5'][k] + st['CA9'][k]} |")
    filled = {j: st[j]["jcs"] + st[j]["party"] + st[j]["party_fjc (by designation)"] for j in CIRCUIT_OF}
    L.append(f"| **ideology_fallback συμπληρωμένο** | **{filled['CA5']}** | **{filled['CA9']}** | "
             f"**{filled['CA5'] + filled['CA9']}** |")
    r_ = pearson(cmp_x, cmp_y)
    L += ["", "## Σύγκριση με JuDJIS (υποθέσεις με JuDJIS score ΚΑΙ JCS)", "",
          f"- Ζεύγη: {len(cmp_x)}" + (f" · Pearson r = {r_:.3f}" if r_ is not None else ""),
          f"- Συμφωνία πρόσημου: {sign_ok}/{sign_n}" + (f" ({sign_ok / sign_n:.1%})" if sign_n else "")]
    if party_j:
        L += ["", "## Ίδιο circuit, όχι στο JCS → κόμμα", ""] + [f"- {k}: {v}" for k, v in party_j.most_common(15)]
    if vis_names:
        L += ["", "## By designation → party_fjc (top 25)", ""] + [f"- {k}: {v}" for k, v in vis_names.most_common(25)]
    if amb:
        L += ["", "## Αμφίσημα — με τους υποψηφίους", ""] + \
             [f"- {k}: {v} · {', '.join(amb_c.get(k, []))}" for k, v in amb.most_common(20)]
    if miss:
        L += ["", "## Δεν βρέθηκαν στο FJC (top 20)", ""] + [f"- {k}: {v}" for k, v in miss.most_common(20)]
    text = "\n".join(L)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

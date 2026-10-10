#!/usr/bin/env python3
"""
enrich_scdb.py — SCOTUS ↔ SCDB με αλυσίδα αντιστοίχισης (αίτημα Κόνιαρη, 2026-10-08)
-----------------------------------------------------------------------------------
Σειρά ΑΚΡΙΒΩΣ όπως τη ζήτησε ο καθηγητής:
  1. docket    : CourtListener dockets.docket_number  ↔  SCDB `docket`
  2. uscite    : CourtListener citations (reporter «U.S.»)  ↔  SCDB `usCite`   (αν δοθεί --citations)
  3. name_year : κανονικοποιημένο όνομα (χωρίς «Revisions: …») + έτος
Το scdb_id που έχει ήδη το CourtListener ΔΕΝ χρησιμοποιείται για αντιστοίχιση — μόνο ως
διασταύρωση στην αναφορά (πόσα από τα matches μας συμφωνούν μαζί του).
Για ΚΑΘΕ SCOTUS υπόθεση ξαναϋπολογίζει (idempotent): scdb_id, issue_area(+source=scdb),
decision_direction, ideology_score(+source=martin_quinn, majOpinWriter + term).
Χωρίς match → τα πεδία μένουν κενά. Καθόλου LLM. Τα circuits δεν αγγίζονται.

Usage:
  B=/data/mkoniaris/akar/bulk; D=2026-06-30
  python code/enrich_scdb.py --clusters $B/opinion-clusters-$D.csv.bz2 --dockets $B/dockets-$D.csv.bz2 \
         [--citations $B/citations-$D.csv.bz2]
"""
import argparse
import csv
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bulk_filter import opener, reader  # noqa: E402

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SCDB_PATH = DATA / "scdb" / "SCDB_2025_01_caseCentered_Citation.csv"
MQ_PATH = DATA / "mqscores" / "justices.csv"
FIELDS = ["scdb_id", "issue_area", "issue_area_source", "decision_direction",
          "ideology_score", "ideology_source"]


def norm_docket_tokens(s):
    """«No. 20-1199, 21-707» → {'20-1199','21-707'} · «No. 16–658.» (en dash) → {'16-658'} ·
    «141, Orig.» / «22O141» → {'141ORIG'}."""
    s = (s or "").upper()
    s = re.sub(r"[‐-―−]", "-", s)            # en/em dash, minus → «-»
    orig = re.search(r"(\d+)\s*,?\s*ORIG", s) or re.fullmatch(r"\s*\d{2}O(\d+)\s*", s)
    if orig:
        return {orig.group(1) + "ORIG"}
    s = re.sub(r"\bNOS?\.?\s*", " ", s)
    out = set()
    for tok in re.split(r"[,;&/]|\bAND\b", s):
        tok = re.sub(r"[^A-Z0-9\-]", "", tok)
        if tok:
            out.add(tok)
    return out


def norm_cite(vol, rep, page):
    page = (page or "").strip()
    if not page or "_" in page:
        return ""
    return f"{(vol or '').strip()}U.S.{page}".replace(" ", "")


def norm_name(name):
    name = re.sub(r"\s+Revisions?:.*$", "", name or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def year(s):
    m = re.search(r"(\d{4})", s or "")
    return int(m.group(1)) if m else None


def load_scdb():
    with open(SCDB_PATH, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    by_docket, by_cite, by_id, by_name = {}, {}, {}, {}
    for r in rows:
        for t in norm_docket_tokens(r.get("docket")):
            by_docket.setdefault(t, []).append(r)
        c = (r.get("usCite") or "").replace(" ", "")
        if c and "_" not in c:
            by_cite.setdefault(c, r)
        cid = (r.get("caseId") or "").strip()
        if cid:
            by_id[cid] = r
        by_name.setdefault((norm_name(r.get("caseName")), year(r.get("dateDecision"))), r)
    return by_docket, by_cite, by_id, by_name


def load_mq():
    idx = {}
    with open(MQ_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                idx[(int(r["justice"]), int(r["term"]))] = float(r["post_mn"])
            except (KeyError, ValueError):
                pass
    return idx


def stream(path, keep, label):
    """Διαβάζει bulk CSV και επιστρέφει τις γραμμές για τις οποίες keep(row) != None."""
    out, n = [], 0
    print(f"Streaming {label}: {path}")
    with opener(path) as f:
        for row in reader(f):
            n += 1
            if n % 2_000_000 == 0:
                print(f"   ...{n:,}")
            v = keep(row)
            if v is not None:
                out.append(v)
    print(f"   κράτησα {len(out)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", required=True)
    ap.add_argument("--dockets", required=True)
    ap.add_argument("--citations", default=None, help="citations-*.csv.bz2 (προαιρετικό, για usCite)")
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    inp = Path(args.input) if args.input else DATA / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp
    report = Path(args.report) if args.report else DATA / "scdb_report.md"
    bak = inp.with_name(inp.stem + ".pre_scdb.csv")
    if out == inp and not bak.exists():
        shutil.copy2(inp, bak)
        print(f"Backup → {bak}")

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in FIELDS:
        if c not in fieldnames:
            fieldnames.append(c)
    scotus = [r for r in rows if r.get("jurisdiction") == "SCOTUS"]
    want = {str(r.get("cluster_id")) for r in scotus}
    before = {k: sum(1 for r in scotus if str(r.get(k) or "").strip())
              for k in ("scdb_id", "issue_area", "ideology_score", "decision_direction")}
    print(f"Input : {inp} | SCOTUS: {len(scotus)}")

    # cluster → docket_id, CL scdb_id
    cl = {r[0]: (r[1], r[2]) for r in stream(
        args.clusters,
        lambda row: ((row.get("id") or "").strip(), (row.get("docket_id") or "").strip(),
                     (row.get("scdb_id") or "").strip())
        if (row.get("id") or "").strip() in want else None, "clusters")}
    want_d = {d for d, _ in cl.values() if d}
    dk = dict(stream(args.dockets,
                     lambda row: ((row.get("id") or "").strip(), row.get("docket_number") or "")
                     if (row.get("id") or "").strip() in want_d else None, "dockets"))
    cites = {}
    if args.citations:
        for cid, c in stream(args.citations,
                             lambda row: ((row.get("cluster_id") or "").strip(),
                                          norm_cite(row.get("volume"), row.get("reporter"), row.get("page")))
                             if (row.get("cluster_id") or "").strip() in want
                             and (row.get("reporter") or "").strip() == "U.S." else None, "citations"):
            if c:
                cites.setdefault(cid, c)

    by_docket, by_cite, by_id, by_name = load_scdb()
    mq = load_mq()
    method, agree, unmatched = Counter(), Counter(), []
    for r in scotus:
        cid = str(r.get("cluster_id"))
        docket_id, cl_sid = cl.get(cid, ("", ""))
        yr = year(r.get("date_filed"))
        hit, how = None, ""
        # 1. docket
        for t in norm_docket_tokens(dk.get(docket_id, "")):
            if by_docket.get(t):
                hit, how = by_docket[t][0], "docket"; break
        # 2. usCite
        if not hit and cites.get(cid) in by_cite:
            hit, how = by_cite[cites[cid]], "uscite"
        # 3. όνομα + έτος
        if not hit:
            s = by_name.get((norm_name(r.get("case_name")), yr))
            if s:
                hit, how = s, "name_year"
        # διασταύρωση με το scdb_id του CourtListener
        if hit and cl_sid:
            agree["συμφωνεί με CL scdb_id" if hit.get("caseId") == cl_sid else "ΔΙΑΦΩΝΕΙ με CL scdb_id"] += 1

        for k in FIELDS:
            r[k] = ""
        if not hit:
            method["χωρίς match"] += 1
            unmatched.append((r.get("case_name", ""), dk.get(docket_id, ""), r.get("date_filed", "")))
            continue
        method[how] += 1
        r["scdb_id"] = hit.get("caseId", "")
        ia = (hit.get("issueArea") or "").strip()
        if ia:
            r["issue_area"], r["issue_area_source"] = ia, "scdb"
        r["decision_direction"] = (hit.get("decisionDirection") or "").strip()
        try:
            score = mq.get((int(hit.get("majOpinWriter") or ""), int(hit.get("term") or "")))
        except ValueError:
            score = None
        if score is not None:
            r["ideology_score"], r["ideology_source"] = score, "martin_quinn"

    if "scdb_match" in fieldnames:          # παλιά (μη εγκεκριμένη) στήλη → αφαίρεση
        fieldnames.remove("scdb_match")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    after = {k: sum(1 for r in scotus if str(r.get(k) or "").strip()) for k in before}
    L = [f"# SCOTUS ↔ SCDB — `{out.name}`", "", f"**SCOTUS υποθέσεις:** {len(scotus)} · "
         f"με docket_number: {sum(1 for c in want if dk.get(cl.get(c, ('', ''))[0]))} · "
         f"με usCite: {len(cites)}" + ("" if args.citations else " (δεν δόθηκε --citations)"), "",
         "## Μέθοδος αντιστοίχισης", "", "| Μέθοδος | Υποθέσεις |", "|---|---|"]
    for k in ["docket", "uscite", "name_year", "χωρίς match"]:
        L.append(f"| {k} | {method[k]} |")
    L += ["", "## Κάλυψη πριν → μετά", "", "| Πεδίο | Πριν | Μετά |", "|---|---|---|"]
    for k in before:
        L.append(f"| {k} | {before[k]} | {after[k]} / {len(scotus)} |")
    if agree:
        L += ["", "**Διασταύρωση με το scdb_id του CourtListener:** " +
              " · ".join(f"{k} {v}" for k, v in agree.items())]
    if unmatched:
        L += ["", f"## Χωρίς match ({len(unmatched)}) — δείγμα", ""]
        L += [f"- {n[:60]} · docket `{d or '—'}` · {dt}" for n, d, dt in unmatched[:25]]
    text = "\n".join(L)
    report.write_text(text + "\n", encoding="utf-8")
    print("\n" + text + f"\n\nSaved -> {out}\nReport -> {report}")


if __name__ == "__main__":
    main()

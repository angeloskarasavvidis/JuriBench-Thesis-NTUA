#!/usr/bin/env python3
"""
enrich_scdb_ids.py
------------------
Ακριβής σύνδεση SCOTUS ↔ SCDB μέσω του `scdb_id` που ΥΠΑΡΧΕΙ ήδη στα
CourtListener bulk opinion-clusters (αντί για το εύθραυστο fuzzy match
όνομα+έτος του enrich_ideology.py, που άφηνε ~36% του SCOTUS χωρίς match).

Τι κάνει:
  1. Διαβάζει (streaming) ΜΟΝΟ το opinion-clusters bulk αρχείο και κρατά
     cluster_id -> scdb_id (+ scdb_decision_direction) για τα SCOTUS
     cluster_ids του dataset.
  2. Για κάθε SCOTUS γραμμή με scdb_id που υπάρχει στο SCDB:
       issue_area, issue_area_source="scdb", decision_direction,
       ideology_score (Martin-Quinn: majOpinWriter + term), ideology_source="martin_quinn".
     Το ακριβές match ΥΠΕΡΙΣΧΥΕΙ του fuzzy. Γραμμές χωρίς scdb_id μένουν ως έχουν.
  Καθόλου LLM (κανόνας: ιδεολογία μόνο από ακαδημαϊκές πηγές).

Usage:
  python code/enrich_scdb_ids.py --clusters /data/mkoniaris/akar/bulk/opinion-clusters-2026-06-30.csv.bz2
  (default in/out: data/juribench_cases.csv, in-place)
"""
import argparse
import bz2
import csv
import io
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SCDB_PATH = DATA / "scdb" / "SCDB_2025_01_caseCentered_Citation.csv"
MQ_PATH = DATA / "mqscores" / "justices.csv"
SCDB_KEYS = ("caseId", "docketId", "caseIssuesId", "voteId")   # σε ποιο πεδίο αντιστοιχεί το scdb_id


def open_text(path):
    if str(path).endswith(".bz2"):
        return io.TextIOWrapper(bz2.open(path, "rb"), encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def load_scdb():
    with open(SCDB_PATH, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    idx = {}
    for r in rows:
        for k in SCDB_KEYS:
            v = (r.get(k) or "").strip()
            if v:
                idx.setdefault(v, r)
    return idx


def load_mq():
    idx = {}
    with open(MQ_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                idx[(int(r["justice"]), int(r["term"]))] = float(r["post_mn"])
            except (KeyError, ValueError):
                pass
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", required=True, help="opinion-clusters-*.csv.bz2 (bulk)")
    ap.add_argument("--input", default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    inp = Path(args.input) if args.input else DATA / "juribench_cases.csv"
    out = Path(args.output) if args.output else inp

    with open(inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in ("scdb_id", "issue_area", "issue_area_source", "decision_direction",
              "ideology_score", "ideology_source"):
        if c not in fieldnames:
            fieldnames.append(c)
    scotus = [r for r in rows if r.get("jurisdiction") == "SCOTUS"]
    want = {str(r.get("cluster_id")) for r in scotus}
    before_ideo = sum(1 for r in scotus if (r.get("ideology_score") or "").strip())
    before_ia = sum(1 for r in scotus if (r.get("issue_area") or "").strip())
    print(f"Input : {inp} | SCOTUS γραμμές: {len(scotus)}")

    # 1. streaming clusters → scdb_id
    print(f"Διαβάζω clusters (streaming): {args.clusters}")
    cmap, n = {}, 0
    with open_text(args.clusters) as f:
        rd = csv.DictReader(f, escapechar="\\", doublequote=False)
        for row in rd:
            n += 1
            if n % 1_000_000 == 0:
                print(f"   ...{n:,} clusters, βρέθηκαν {len(cmap)}")
            cid = (row.get("id") or "").strip()
            if cid in want:
                cmap[cid] = ((row.get("scdb_id") or "").strip(),
                             (row.get("scdb_decision_direction") or "").strip())
    with_id = sum(1 for v in cmap.values() if v[0])
    print(f"   SCOTUS clusters βρέθηκαν: {len(cmap)}/{len(want)} · με scdb_id: {with_id}")

    # 2. join με SCDB + Martin-Quinn
    scdb, mq = load_scdb(), load_mq()
    matched = mq_hit = 0
    for r in scotus:
        sid, cl_dir = cmap.get(str(r.get("cluster_id")), ("", ""))
        if not sid:
            continue
        r["scdb_id"] = sid
        s = scdb.get(sid)
        if not s:
            if cl_dir and not (r.get("decision_direction") or "").strip():
                r["decision_direction"] = cl_dir
            continue
        matched += 1
        ia = (s.get("issueArea") or "").strip()
        if ia:
            r["issue_area"], r["issue_area_source"] = ia, "scdb"
        r["decision_direction"] = (s.get("decisionDirection") or "").strip() or cl_dir
        try:
            score = mq.get((int(s.get("majOpinWriter") or ""), int(s.get("term") or "")))
        except ValueError:
            score = None
        if score is not None:
            r["ideology_score"], r["ideology_source"] = score, "martin_quinn"
            mq_hit += 1

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            for c in fieldnames:
                r.setdefault(c, "")
            w.writerow(r)

    after_ideo = sum(1 for r in scotus if str(r.get("ideology_score") or "").strip())
    after_ia = sum(1 for r in scotus if (r.get("issue_area") or "").strip())
    print(f"\nSCDB ακριβή matches (scdb_id): {matched} · με Martin-Quinn: {mq_hit}")
    print(f"SCOTUS ideology_score: {before_ideo} -> {after_ideo} / {len(scotus)}")
    print(f"SCOTUS issue_area    : {before_ia} -> {after_ia} / {len(scotus)}")
    print(f"Saved -> {out}")


if __name__ == "__main__":
    main()

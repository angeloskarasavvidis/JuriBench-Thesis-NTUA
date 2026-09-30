#!/usr/bin/env python3
"""
enrich_ideology.py
-------------------
Stage 2 of ideology enrichment (local joins, no network). Requires Stage 1
(enrich_authors.py) to have populated author_str for circuit rows first.

SCOTUS  : match to SCDB by usCite (fallback case_name+date_filed) ->
          majOpinWriter (int) -> Martin-Quinn justices.csv[justice==code & term]
          -> continuous ideology_score (ideology_source="martin_quinn").
          Also pulls issueArea -> issue_area (issue_area_source="scdb") and
          decisionDirection -> decision_direction. Per-curiam / unmatched ->
          ideology left blank (not gpt4o-fallbacked).

CA5/CA9 : match author_str -> JuDJIS agjudge_full.csv via Jaro-Winkler >= 0.92
          -> judjis_score -> threshold +-0.3 -> ideology/ideology_class
          (ideology_source="judjis"). Unmatched authors dropped (counted),
          NOT gpt4o-fallbacked (banned per issues.md #5).

Usage:
  python enrich_ideology.py
  python enrich_ideology.py --input data/juribench_dataset.csv --output data/juribench_dataset.csv
"""

import argparse
import csv
import sys
from pathlib import Path

import jellyfish  # Jaro-Winkler

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

SCDB_PATH  = DATA / "scdb" / "SCDB_2025_01_caseCentered_Citation.csv"
MQ_PATH    = DATA / "mqscores" / "justices.csv"
JUDJIS_PATH = DATA / "judjis" / "agjudge_full.csv"

IDEOLOGY_THRESHOLD = 0.3
JW_THRESHOLD        = 0.92

NEW_COLS = [
    "ideology", "ideology_score", "ideology_source",
    "issue_area", "issue_area_source", "decision_direction",
]


def load_scdb():
    with open(SCDB_PATH, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    by_cite, by_name_date = {}, {}
    for r in rows:
        cite = (r.get("usCite") or "").strip()
        if cite:
            by_cite[cite] = r
        key = (_norm_name(r.get("caseName", "")), _year(r.get("dateDecision", "")))
        by_name_date[key] = r
    return rows, by_cite, by_name_date


def load_mq():
    with open(MQ_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    idx = {}
    for r in rows:
        try:
            idx[(int(r["justice"]), int(r["term"]))] = float(r["post_mn"])
        except (ValueError, KeyError):
            continue
    return idx


def load_judjis():
    with open(JUDJIS_PATH, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        first = (r.get("first.name") or "").strip()
        last  = (r.get("last.name") or "").strip()
        score = r.get("judjis")
        if not last or score in (None, ""):
            continue
        try:
            score = float(score)
        except ValueError:
            continue
        out.append({
            "full_name": f"{first} {last}".strip(),
            "last_name": last,
            "court": (r.get("court") or "").strip(),
            "judjis_score": score,
        })
    return out


def _norm_name(name):
    import re
    name = re.sub(r"\s+Revisions?:.*$", "", name or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _year(date_str):
    """Pull a 4-digit year out of either M/D/YYYY (SCDB) or ISO (dataset) dates."""
    import re
    m = re.search(r"(\d{4})", date_str or "")
    return m.group(1) if m else ""


def match_scdb(row, scdb_by_cite, scdb_by_name_date):
    # CourtListener rows don't carry a citation column directly in our schema;
    # fall back to case_name+year matching. SCDB dates are M/D/YYYY, dataset
    # dates are ISO — match on normalized name + year, not the raw date string.
    key = (_norm_name(row.get("case_name", "")), _year(row.get("date_filed", "")))
    return scdb_by_name_date.get(key)


def classify(score, threshold=IDEOLOGY_THRESHOLD):
    if score is None:
        return ""
    if score < -threshold:
        return "Liberal"
    if score > threshold:
        return "Conservative"
    return "Moderate"


def match_judjis(author_str, judjis_roster, court_name):
    if not author_str:
        return None
    best, best_score = None, 0.0
    for j in judjis_roster:
        if court_name and j["court"] and court_name not in j["court"] and j["court"] not in court_name:
            continue
        s = jellyfish.jaro_winkler_similarity(author_str.lower(), j["full_name"].lower())
        s2 = jellyfish.jaro_winkler_similarity(author_str.lower(), j["last_name"].lower())
        s = max(s, s2)
        if s > best_score:
            best_score, best = s, j
    if best and best_score >= JW_THRESHOLD:
        return best
    return None


def enrich_scotus(rows, scdb_by_cite, scdb_by_name_date, mq_idx):
    matched = unmatched = no_author = 0
    for row in rows:
        if row.get("jurisdiction") != "SCOTUS":
            continue
        scdb_row = match_scdb(row, scdb_by_cite, scdb_by_name_date)
        if not scdb_row:
            unmatched += 1
            continue

        issue_area = (scdb_row.get("issueArea") or "").strip()
        if issue_area:
            row["issue_area"]        = issue_area
            row["issue_area_source"] = "scdb"
        row["decision_direction"] = (scdb_row.get("decisionDirection") or "").strip()

        maj_writer = (scdb_row.get("majOpinWriter") or "").strip()
        term       = (scdb_row.get("term") or "").strip()
        if not maj_writer or not term:
            no_author += 1
            continue
        try:
            score = mq_idx.get((int(maj_writer), int(term)))
        except ValueError:
            score = None
        if score is None:
            no_author += 1
            continue

        row["ideology_score"]  = score
        row["ideology_source"] = "martin_quinn"
        row["ideology"]        = ""  # class deferred — MQ scale threshold not yet decided
        matched += 1

    print(f"SCOTUS: {matched} ideology-matched, {no_author} no author/term match, "
          f"{unmatched} no SCDB case match")


def enrich_circuits(rows, judjis_roster):
    matched = unmatched = no_author_str = 0
    for row in rows:
        if row.get("jurisdiction") not in ("CA5", "CA9"):
            continue
        author_str = (row.get("author_str") or "").strip()
        if not author_str:
            no_author_str += 1
            continue
        hit = match_judjis(author_str, judjis_roster, row.get("court", ""))
        if not hit:
            unmatched += 1
            continue
        row["ideology_score"]  = hit["judjis_score"]
        row["ideology_source"] = "judjis"
        row["ideology"]        = classify(hit["judjis_score"])
        matched += 1

    print(f"Circuits: {matched} JuDJIS-matched, {no_author_str} missing author_str "
          f"(run enrich_authors.py first), {unmatched} no JuDJIS match >= {JW_THRESHOLD}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    input_path  = Path(args.input)  if args.input  else DATA / "juribench_dataset.csv"
    output_path = Path(args.output) if args.output else input_path

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)
    for row in rows:
        for c in NEW_COLS:
            row.setdefault(c, "")

    print(f"Input : {input_path}")
    print(f"Loaded: {len(rows)} rows\n")

    _, scdb_by_cite, scdb_by_name_date = load_scdb()
    mq_idx = load_mq()
    judjis_roster = load_judjis()
    print(f"SCDB rows: loaded | MQ entries: {len(mq_idx)} | JuDJIS judges: {len(judjis_roster)}\n")

    enrich_scotus(rows, scdb_by_cite, scdb_by_name_date, mq_idx)
    enrich_circuits(rows, judjis_roster)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    have_ideology = sum(1 for r in rows if (r.get("ideology_score") or "") != "")
    print(f"\nSaved -> {output_path}")
    print(f"  ideology_score coverage: {have_ideology}/{len(rows)} ({have_ideology/len(rows):.1%})")


if __name__ == "__main__":
    main()

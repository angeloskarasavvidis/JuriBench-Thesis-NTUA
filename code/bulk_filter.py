#!/usr/bin/env python3
"""
bulk_filter.py — Streaming φίλτρο των CourtListener bulk data.
=============================================================
Τρέχει πάνω στα ΗΔΗ κατεβασμένα bulk αρχεία (bz2/csv) και παράγει ένα μικρό
`juribench_dataset.csv` (μόνο SCOTUS/CA5/CA9), ίδιου σχήματος με τον collector,
ώστε να συνεχίσει κανονικά το υπόλοιπο pipeline (enrich_* → make_splits).

ΔΕΝ αποσυμπιέζει πλήρως τίποτα: διαβάζει «ρέοντας» (bz2 incremental) και κρατά
μόνο τις γραμμές των 3 δικαστηρίων. Peak μνήμη = μεταδεδομένα + επιλεγμένα κείμενα
(λίγες εκατοντάδες MB με cap).

Bulk αρχεία που χρειάζονται (από https://www.courtlistener.com/help/api/bulk-data/):
  - dockets  (docket → court)
  - opinion-clusters (cluster → docket, case_name, date, precedential_status, judges)
  - opinions (το μεγάλο ~54GB: cluster → text/type/author/per_curiam)

Usage:
  python bulk_filter.py \
      --dockets dockets.csv.bz2 --clusters opinion-clusters.csv.bz2 \
      --opinions opinions.csv.bz2 \
      --courts scotus,ca5,ca9 --after 2013-01-01 --before 2024-12-31 \
      --max-per-court 6000 --min-words 500 --out juribench_dataset.csv

Σημείωση: τα ονόματα στηλών των bulk CSV ανιχνεύονται αυτόματα (με fallbacks).
Στην αρχή τυπώνει τα headers κάθε αρχείου — αν κάτι δεν ταιριάζει, στείλ' τα πίσω.
"""
import argparse, bz2, csv, gzip, io, re, sys
from collections import defaultdict

csv.field_size_limit(sys.maxsize)

COURT_LABEL = {"scotus": "SCOTUS", "ca5": "CA5", "ca9": "CA9"}
FIELDNAMES = ["jurisdiction", "court_id", "cluster_id", "case_name", "date_filed",
              "court", "judge_name", "judge_id", "syllabus", "opinion_text",
              "issue_area", "issue_area_source"]
TEXT_FIELDS = ["html_with_citations", "html_columbia", "html_lawbox",
               "html_anon_2020", "html", "plain_text", "xml_harvard"]


def opener(path):
    if path.endswith(".bz2"):
        return io.TextIOWrapper(bz2.open(path, "rb"), encoding="utf-8", errors="replace")
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def reader(f):
    """CourtListener bulk CSV: παράγεται από Postgres COPY με ESCAPE '\\' (τα
    εσωτερικά εισαγωγικά γράφονται ως \\" και ΟΧΙ ως ""). Το Python csv πρέπει
    ρητά να ξέρει το escapechar + doublequote=False, αλλιώς μπερδεύει γραμμές
    στα κείμενα (opinion_text) που είναι γεμάτα εισαγωγικά."""
    return csv.DictReader(f, escapechar="\\", doublequote=False)


def g(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return ""


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def year(s):
    m = re.search(r"(\d{4})", s or "")
    return m.group(1) if m else ""


def type_priority(t):
    t = (t or "").lower()
    if "lead" in t: return 0
    if "combined" in t: return 1
    if "concurr" in t or "dissent" in t or "addendum" in t: return 3
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dockets", required=True)
    ap.add_argument("--clusters", required=True)
    ap.add_argument("--opinions", required=True)
    ap.add_argument("--courts", default="scotus,ca5,ca9")
    ap.add_argument("--after", default="2013-01-01")
    ap.add_argument("--before", default="2024-12-31")
    ap.add_argument("--max-per-court", type=int, default=6000, help="0 = χωρίς όριο")
    ap.add_argument("--min-words", type=int, default=500)
    ap.add_argument("--published-only", action="store_true", default=True)
    ap.add_argument("--out", default="juribench_dataset.csv")
    args = ap.parse_args()

    courts = set(args.courts.split(","))
    ya, yb = year(args.after), year(args.before)

    # ── Pass 1: dockets → docket_id -> court_id (μόνο για τα 3 δικαστήρια) ──
    print(f"[1/3] dockets: {args.dockets}")
    docket_court = {}
    with opener(args.dockets) as f:
        r = reader(f)
        print("      headers:", r.fieldnames[:12])
        for row in r:
            c = g(row, "court_id", "court")
            if c in courts:
                docket_court[g(row, "id", "docket_id")] = c
    print(f"      dockets στα 3 δικαστήρια: {len(docket_court)}")

    # ── Pass 2: clusters → κρατάμε published + εντός διαστήματος ──
    print(f"[2/3] clusters: {args.clusters}")
    per_court = defaultdict(list)   # court -> list of (date, cluster_id, meta)
    with opener(args.clusters) as f:
        r = reader(f)
        print("      headers:", r.fieldnames[:15])
        for row in r:
            did = g(row, "docket_id", "docket")
            court = docket_court.get(did)
            if not court:
                continue
            status = g(row, "precedential_status")
            if args.published_only and status and status.lower() != "published":
                continue
            d = g(row, "date_filed", "date_created")
            y = year(d)
            if y and ya and yb and not (ya <= y <= yb):
                continue
            cid = g(row, "id", "cluster_id")
            meta = {"case_name": g(row, "case_name", "case_name_full", "case_name_short"),
                    "date_filed": d, "judges": g(row, "judges"),
                    "syllabus": g(row, "headnotes", "syllabus", "summary"),
                    "court": court}
            per_court[court].append((d, cid, meta))
    # cap ανά δικαστήριο (νεότερα πρώτα)
    keep = {}
    for court, items in per_court.items():
        items.sort(key=lambda x: x[0], reverse=True)
        if args.max_per_court:
            items = items[: args.max_per_court]
        for _, cid, meta in items:
            keep[cid] = meta
        print(f"      {court}: κρατήθηκαν {len(items)} clusters")
    print(f"      σύνολο clusters: {len(keep)}")

    # ── Pass 3: opinions (το μεγάλο) → καλύτερο opinion ανά cluster ──
    print(f"[3/3] opinions (streaming): {args.opinions}")
    best = {}   # cluster_id -> (priority, text, author_str, per_curiam)
    seen = 0
    with opener(args.opinions) as f:
        r = reader(f)
        print("      headers:", r.fieldnames[:15])
        for row in r:
            seen += 1
            if seen % 500000 == 0:
                print(f"      ...διαβάστηκαν {seen:,} opinions, ταιριάξαν {len(best)}")
            cid = g(row, "cluster_id", "cluster")
            if cid not in keep:
                continue
            pr = type_priority(g(row, "type"))
            if cid in best and best[cid][0] <= pr:
                continue
            raw = ""
            for fld in TEXT_FIELDS:
                v = row.get(fld)
                if v:
                    raw = strip_html(v) if fld != "plain_text" else v.strip()
                    if raw:
                        break
            if not raw:
                continue
            per_curiam = str(g(row, "per_curiam")).lower() in ("true", "1", "t")
            best[cid] = (pr, raw, g(row, "author_str"), per_curiam)

    # ── Γράψιμο output ──
    written = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=FIELDNAMES)
        w.writeheader()
        for cid, meta in keep.items():
            if cid not in best:
                continue
            pr, text, author, per_curiam = best[cid]
            if per_curiam:
                continue
            if len(text.split()) < args.min_words:
                continue
            court = meta["court"]
            w.writerow({
                "jurisdiction": COURT_LABEL.get(court, court.upper()),
                "court_id": court, "cluster_id": cid,
                "case_name": meta["case_name"], "date_filed": meta["date_filed"],
                "court": court, "judge_name": meta["judges"] or author,
                "judge_id": "", "syllabus": meta["syllabus"],
                "opinion_text": text, "issue_area": "", "issue_area_source": "",
            })
            written += 1
    print(f"\n✓ Γράφτηκαν {written} υποθέσεις → {args.out}")


if __name__ == "__main__":
    main()

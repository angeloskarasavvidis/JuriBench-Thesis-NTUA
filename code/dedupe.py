#!/usr/bin/env python3
"""
dedupe.py  (reference implementation for the student's pipeline, last step)
----------------------------------------------------------------------------
Removes duplicate versions of the same opinion from juribench_cases.csv.

  1. SCOTUS compare pages: strip the CourtListener document-compare wrapper
     ("Compare Results Old File: New File: ..." / "Differences exist between
     documents ...") and the "file://NoURLProvided[...]" page stamps, so the text
     is the plain opinion (2020 wrappers have no stamp: cut at "(Slip Opinion)" /
     "Cite as:"). If a plain row of the same case exists within COMPARE_TWIN_DAYS (= MAX_GAP_DAYS),
     the compare-page row is a second copy and is dropped. Similarity can't be
     used here: the compare copy starts with the syllabus, the plain one at
     "Justice X delivered ...", so Jaccard is only ~0.2.
  2. Junk rows (CA9 vacancy announcement, Judicial Council reports) and exact-duplicate texts.
  3. Amended / reissued versions. Same court + same case name, filed
     <= MAX_GAP_DAYS apart. Drop the OLDER one if either
       (a) word 5-gram Jaccard >= SIM_THRESHOLD, or
       (b) either one opens with a revision marker (REVISED, AMENDED OPINION,
           "prior opinion is withdrawn", "is hereby amended", ...) and
           Jaccard >= MARKER_MIN_SIM. The older row can carry it too: CA9 files
           "ORDER The opinion filed ... is hereby amended" as its own row.
           The floor stops generic names ("In Re: Deepwater Horizon") from
           matching unrelated opinions.
     The latest version is kept (the amended text is the final one).

Every dropped row is logged with its reason, the kept cluster_id and the similarity.

Usage:
  python dedupe.py --input juribench_cases.csv --output juribench_cases.dedup.csv --dropped dedupe_dropped.csv
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date

csv.field_size_limit(sys.maxsize)

MAX_GAP_DAYS = 400
SIM_THRESHOLD = 0.5
MARKER_MIN_SIM = 0.05
SHINGLE_N = 5
SIM_CHARS = 20000          # compare the first N chars of each opinion
MARKER_CHARS = 3000        # look for revision markers in the opening only

JUNK_PAT = re.compile(r"VACANCY ANNOUNCEMENT|JUDICIAL COUNCIL OF THE NINTH CIRCUIT", re.IGNORECASE)   # not opinions
COMPARE_HEAD = re.compile(r"Compare Results\s+Old File:|Differences exist between documents")
COMPARE_STAMP = re.compile(r"file://NoURLProvided\[[^\]]*\]")
OPINION_START = re.compile(r"\(Slip Opinion\)|Cite as:|SUPREME COURT OF THE UNITED STATES")   # wrappers without a stamp
COMPARE_TWIN_DAYS = MAX_GAP_DAYS   # revised PDFs can come months later (Jam v. IFC: 139 days)
REVISION_MARKER = re.compile(
    r"\bREVISED\b"
    r"|AMENDED OPINION"
    r"|opinion[^.]{0,100}?\b(?:is|was) (?:hereby )?(?:amended|withdrawn)"
    r"|(?:withdraw|vacate) (?:the|our) (?:prior|previous|earlier|original) opinion"
    r"|(?:is|are) substituted|substitute the following"
    r"|motion to amend (?:the )?opinion",
    re.IGNORECASE)


def strip_compare_page(text):
    """Return (clean_text, was_compare_page)."""
    if not COMPARE_HEAD.search(text[:500]):
        return text, False
    first = COMPARE_STAMP.search(text) or OPINION_START.search(text)
    if first:
        text = text[first.start() if first.re is OPINION_START else first.end():]
    return COMPARE_STAMP.sub(" ", text).strip(), True


def drop_compare_twins(rows, compare_ids, dropped):
    """A compare-page row is a second copy if a plain row of the same case exists nearby: drop it."""
    plain = defaultdict(list)
    for row in rows:
        if row["cluster_id"] not in compare_ids:
            plain[(row["jurisdiction"], norm_name(row["case_name"]))].append(row)
    kept = []
    for row in rows:
        if row["cluster_id"] in compare_ids:
            d = date.fromisoformat(row["date_filed"])
            twins = [p for p in plain[(row["jurisdiction"], norm_name(row["case_name"]))]
                     if abs((d - date.fromisoformat(p["date_filed"])).days) <= COMPARE_TWIN_DAYS]
            if twins:
                dropped.append((row, "compare_page_copy", twins[0]["cluster_id"], ""))
                continue
        kept.append(row)
    return kept


def norm_name(name):
    name = re.sub(r"\s+Revisions?:.*$", "", name or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def shingles(text):
    words = re.sub(r"\s+", " ", (text or "")[:SIM_CHARS].lower()).split()
    return {" ".join(words[i:i + SHINGLE_N]) for i in range(max(0, len(words) - SHINGLE_N + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def sort_key(row):
    return (row["date_filed"], int(row["cluster_id"]))


def drop_junk_and_exact(rows, dropped):
    kept, seen_text = [], {}
    for row in sorted(rows, key=sort_key, reverse=True):   # latest first -> latest kept
        text = row.get("opinion_text", "")
        if JUNK_PAT.search(text[:500]):
            dropped.append((row, "junk", "", ""))
            continue
        if text in seen_text:
            dropped.append((row, "exact_duplicate", seen_text[text], "1.00"))
            continue
        seen_text[text] = row["cluster_id"]
        kept.append(row)
    return kept


def drop_amended(rows, dropped):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["jurisdiction"], norm_name(row["case_name"]))].append(row)

    drop_ids = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=sort_key, reverse=True)              # latest first
        sh = [shingles(r["opinion_text"]) for r in group]
        for i, newer in enumerate(group):
            if newer["cluster_id"] in drop_ids:
                continue
            new_marked = bool(REVISION_MARKER.search(newer["opinion_text"][:MARKER_CHARS]))
            d_new = date.fromisoformat(newer["date_filed"])
            for j in range(i + 1, len(group)):
                older = group[j]
                if older["cluster_id"] in drop_ids:
                    continue
                if (d_new - date.fromisoformat(older["date_filed"])).days > MAX_GAP_DAYS:
                    continue
                sim = jaccard(sh[i], sh[j])
                if sim >= SIM_THRESHOLD:
                    reason = "amended_earlier_version"
                elif sim >= MARKER_MIN_SIM and (
                        new_marked or REVISION_MARKER.search(older["opinion_text"][:MARKER_CHARS])):
                    # the older row can be CA9's "ORDER ... is hereby amended"
                    reason = "revised_marker"
                else:
                    continue
                drop_ids.add(older["cluster_id"])
                dropped.append((older, reason, newer["cluster_id"], f"{sim:.2f}"))
    return [r for r in rows if r["cluster_id"] not in drop_ids]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dropped", required=True)
    args = parser.parse_args()

    with open(args.input, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    compare_ids = set()
    for row in rows:
        row["opinion_text"], was = strip_compare_page(row.get("opinion_text", ""))
        if was:
            compare_ids.add(row["cluster_id"])
    n_compare = len(compare_ids)

    dropped = []
    kept = drop_compare_twins(rows, compare_ids, dropped)
    kept = drop_amended(drop_junk_and_exact(kept, dropped), dropped)
    kept.sort(key=lambda r: (r["jurisdiction"], r["date_filed"], int(r["cluster_id"])))

    with open(args.output, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)
    with open(args.dropped, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["jurisdiction", "cluster_id", "case_name", "date_filed", "reason", "kept_cluster_id", "similarity"])
        for row, reason, kept_id, sim in dropped:
            w.writerow([row["jurisdiction"], row["cluster_id"], row["case_name"], row["date_filed"], reason, kept_id, sim])

    print(f"Input : {len(rows)} rows · SCOTUS compare pages stripped: {n_compare}")
    for reason, k in Counter(d[1] for d in dropped).most_common():
        print(f"  dropped {reason}: {k}")
    print(f"Output: {len(kept)} rows {dict(Counter(r['jurisdiction'] for r in kept))} -> {args.output}")


if __name__ == "__main__":
    main()

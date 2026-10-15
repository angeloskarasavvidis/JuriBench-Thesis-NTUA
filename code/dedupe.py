#!/usr/bin/env python3
"""
dedupe.py  (reference implementation for the pipeline, last step)
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
  4. Near-duplicates under a different case name (step 3 misses them: it groups
     by exact name). The same opinion imported twice from two sources
     ("Smith v. LAUSD" / "Smith v. Los Angeles Unified School District") or an
     amended version re-captioned. Same court; candidate pairs share a docket
     number (opinion head), the LLM issue_text, or the author (<= 365 days apart,
     shared caption word); SCOTUS also the same scdb_id or the same filing day.
     Duplicate if whole-text Jaccard >= SIM_THRESHOLD (SCOTUS scdb/same-day pairs:
     >= SCOTUS_SAME_CASE_SIM, since slip and reporter copies format differently).
     Candidate pairs only limit which rows get compared; the decision is the
     similarity alone. Copies of copies collapse to one row.
     Kept: CA latest then longest; SCOTUS the reporter copy, then longest.
Step 2 also drops the WRONG_COURT_IDS (other circuits filed under CA5/CA9) and rows whose text is a separate writing ("Justice X, concurring")
instead of the majority opinion, or has one embedded later in the text
("... Reversed. Chief Justice ROBERTS, with whom ..., dissenting."): majority-only.

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
# Opinions of other circuits filed under CA5/CA9 in CourtListener (checked by hand 2026-10-14:
# 1st, 6th, 10th, Fed. Cir. panels). No pattern catches these; all CA rows were scanned once.
WRONG_COURT_IDS = {"8443025", "8695046", "8695766", "8442964", "8443224",
                   "8697334", "8695064", "8695543", "8695734", "8697254"}
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

# step 4
NEAR_GAP_DAYS = 365
SCOTUS_SAME_CASE_SIM = 0.2   # below this a shared scdb_id is a different decision (original-jurisdiction cases)
SEPARATE_WRITING = re.compile(r"^\W*(?:Chief\s+)?Justice\s[^.]{0,120}?(?:concurring|dissenting)", re.IGNORECASE)
# a separate writing starting later in the text (majority-only violated)
EMBEDDED_WRITING = re.compile(
    r"(?:Chief\s+)?Justice\s+[A-Z]{3,}[^.]{0,100}?(?:concurring|dissenting)\."                         # SCOTUS
    r"|[A-Z]{3,},?\s+(?:Senior\s+|Chief\s+)?(?:Circuit\s+|District\s+)?Judge,?\s+(?:concurring|dissenting)")   # CA
DOCKET = re.compile(r"\bNos?\.?\s*((?:\d{2}-\d{3,6})(?:\s*(?:,|and|&)\s*\d{2}-\d{3,6})*)")
CAPTION_STOP = {
    "v", "vs", "united", "states", "state", "of", "the", "in", "re", "inc", "llc", "l", "c", "co",
    "corp", "company", "incorporated", "et", "al", "and", "city", "county", "dept", "department",
    "us", "america", "american", "national", "ex", "rel", "matter", "people", "commissioner",
    "secretary", "attorney", "general", "texas", "california", "louisiana", "mississippi",
    "washington", "arizona", "oregon", "nevada", "idaho", "montana", "alaska", "hawaii", "bank",
    "insurance"}


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


def text_shingles(text):
    """Whole text, punctuation-insensitive: robust to slip vs reporter formatting."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
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
        if row["cluster_id"] in WRONG_COURT_IDS:
            dropped.append((row, "wrong_court", "", ""))
            continue
        if SEPARATE_WRITING.match(text[:400]):
            dropped.append((row, "separate_writing", "", ""))
            continue
        if EMBEDDED_WRITING.search(text[300:]):
            dropped.append((row, "embedded_separate_writing", "", ""))
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


def dockets(text):
    out = set()
    for m in DOCKET.finditer(text[:2500]):
        out.update(re.findall(r"\d{2}-\d{3,6}", m.group(1)))
    return out


def caption_words(name):
    return {t for t in re.findall(r"[a-z]{3,}", (name or "").lower()) if t not in CAPTION_STOP}


def drop_near_duplicates(rows, dropped):
    """Step 4."""
    info = {}
    for r in rows:
        info[r["cluster_id"]] = dict(
            date=date.fromisoformat(r["date_filed"]), auth=(r.get("author_str") or "").strip().lower(),
            dock=dockets(r["opinion_text"]), name=caption_words(r["case_name"]))

    cand = defaultdict(set)   # (id_a, id_b) -> reasons

    def add(members, why):
        members = sorted(set(members), key=int)
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                cand[(members[a], members[b])].add(why)

    by_court = defaultdict(list)
    for r in rows:
        by_court[r["jurisdiction"]].append(r)
    for court, group in by_court.items():
        keyed = defaultdict(list)
        for r in group:
            cid = r["cluster_id"]
            for d in info[cid]["dock"]:
                keyed[("docket", d)].append(cid)
            if r.get("issue_text"):
                keyed[("issue_text", r["issue_text"])].append(cid)
            if court == "SCOTUS":
                if r.get("scdb_id"):
                    keyed[("scdb", r["scdb_id"])].append(cid)
                keyed[("day", r["date_filed"])].append(cid)
        for (why, _), members in keyed.items():
            if len(members) < 2:
                continue
            if why == "day":   # same day only counts with a shared caption word
                for a in members:
                    for b in members:
                        if int(a) < int(b) and info[a]["name"] & info[b]["name"]:
                            cand[(a, b)].add("sameday")
            else:
                add(members, why)
        by_auth = defaultdict(list)
        for r in group:
            if info[r["cluster_id"]]["auth"]:
                by_auth[info[r["cluster_id"]]["auth"]].append(r["cluster_id"])
        for ids in by_auth.values():
            ids.sort(key=lambda c: info[c]["date"])
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    if (info[ids[b]]["date"] - info[ids[a]]["date"]).days > NEAR_GAP_DAYS:
                        break
                    if info[ids[a]]["name"] & info[ids[b]]["name"]:
                        cand[tuple(sorted((ids[a], ids[b]), key=int))].add("author_name")

    row_of = {r["cluster_id"]: r for r in rows}
    sh = {}

    def S(c):
        if c not in sh:
            sh[c] = text_shingles(row_of[c]["opinion_text"])
        return sh[c]

    sim_of = {}
    for (a, b), why in cand.items():
        sim = jaccard(S(a), S(b))
        same_case = bool(why & {"scdb", "sameday"}) and sim >= SCOTUS_SAME_CASE_SIM
        if sim >= SIM_THRESHOLD or same_case:
            sim_of[(a, b)] = sim

    # duplicate clusters (union-find over duplicate pairs)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in sim_of:
        parent[find(a)] = find(b)
    clusters = defaultdict(list)
    for c in list(parent):
        clusters[find(c)].append(c)

    def keep_key(c):
        r = row_of[c]
        if r["jurisdiction"] == "SCOTUS":
            t = r["opinion_text"]
            return (not t.startswith("(Slip Opinion)"), len(t))
        return (r["date_filed"], len(r["opinion_text"]))

    drop_ids = set()
    for cl in clusters.values():
        keep = max(cl, key=keep_key)
        for c in cl:
            if c != keep:
                drop_ids.add(c)
                s = sim_of.get((c, keep)) or sim_of.get((keep, c))
                dropped.append((row_of[c], "near_duplicate", keep, f"{s:.2f}" if s is not None else ""))
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
    kept = drop_near_duplicates(kept, dropped)
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

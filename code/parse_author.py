#!/usr/bin/env python3
"""
parse_author.py
---------------
Parse the authoring judge's surname from a CA5 / CA9 opinion text.
Replaces parse_author() in enrich_authors.py, which matched the panel line
("Before A, B, and C, Circuit Judges.") and recorded the last panel member.

  parse_author(text) -> (surname, author_source)
  author_source: "signature"  -- byline, e.g. "COSTA, Circuit Judge:"
                 "opinion_by" -- CA9 header "Opinion by Judge X" (no byline found)
                 "none"       -- unsigned (per curiam / memorandum / order) -> no ideology

Validated on juribench_cases.csv (2026-10-11): CA9 byline vs "Opinion by"
agree 99.7% (2815 cases); author is on the panel line in 99.8%.
"""

import re

AUTHOR_CHARS = 30000
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# The panel line ("Before A, Chief Judge, and B and C, Circuit Judges.") names every
# judge in signature form, so it is removed before searching for the byline.
PANEL_PAT = re.compile(r"Before:?\s.{0,400}?Judges?\s*\.", re.DOTALL)
# Byline: "COSTA, Circuit Judge:", "SOUTHWICK, Circuit Judge.", "McKEOWN Circuit Judge:",
# "OWEN, Chief Judge:", "Oldham, Circuit Judge, The ...". A comma ending is accepted
# unless it introduces a separate opinion or a joiner ("..., Circuit Judge, dissenting").
# "District Judge" only with a colon: "X, District Judge, Presiding" names the trial judge.
_NAME = r"(?<![\w'\-])([A-ZÀ-Þ][\w'\-]*[^\W\d_])(?:,? (?:Jr|JR|Sr|SR|III|II)\.?)?,?\s+"
NOT_NAMES = {"district", "circuit", "circuict", "chief", "senior", "judge", "magistrate", "bankruptcy",
             "immigration", "county", "law", "court", "states", "the", "trial", "appeals"}
SIGNATURE_PATS = [
    re.compile(_NAME + r"(?:(?:Chief|CHIEF|Senior|SENIOR)\s+)?(?:(?:Circuit|CIRCUIT|District|DISTRICT)\s+)?"
                       r"(?:Judge|JUDGE)\s*:"),
    re.compile(_NAME + r"(?:(?:Chief|CHIEF|Senior|SENIOR)\s+)?(?:(?:Circuit|CIRCUIT)\s+)?(?:Judge|JUDGE)\b\s*"
                       r"(?:\.|,(?!\s*(?i:and|with|who|joined|joins?|concurring|dissenting|sitting|presiding|by)\b))"),
]
OPINION_BY_PAT = re.compile(
    r"Opinion by (?:Chief |Senior )?(?:District )?Judge "
    r"((?:[A-Z][\w'\-\.]* )*?[A-Z][\w'\-]+)\s*(?:;|\*|\n|\d|SUMMARY|$|(?<=\s)(?=[A-Z]{2,}\b))"
)


def parse_author(text):
    """Return (surname, source) from the opinion head; source is signature / opinion_by / none."""
    head = (text or "")[:AUTHOR_CHARS]
    body = PANEL_PAT.sub(" ", head, count=1)
    hits = [next((m for m in p.finditer(body) if m.group(1).lower() not in NOT_NAMES), None)
            for p in SIGNATURE_PATS]
    hits = [m for m in hits if m]
    m = min(hits, key=lambda h: h.start()) if hits else None
    if m:
        return m.group(1), "signature"
    m = OPINION_BY_PAT.search(head)
    if m:
        words = [w for w in m.group(1).split() if w.strip(".").lower() not in NAME_SUFFIXES]
        return words[-1], "opinion_by"
    return "", "none"



#!/usr/bin/env python3
"""
judge_aliases.py — Κοινός πίνακας ταυτίσεων δικαστών (οδηγία καθηγητή, 2026-10-12)
---------------------------------------------------------------------------------
Ίδια πρόσωπα με διαφορετικό επώνυμο σε διαφορετικές πηγές (αλλαγή επωνύμου / διπλό επώνυμο).
Εφαρμόζεται ΙΔΙΟΣ σε JuDJIS (enrich_ideology), JCS και FJC (ideology_fallback).

Κάθε εγγραφή: (circuit, {όλα τα επώνυμα του ίδιου προσώπου})
  CA5 · Priscilla Richman  = Priscilla Owen        (αλλαγή επωνύμου)
  CA9 · Danielle Forrest   = Danielle Hunsaker     (αλλαγή επωνύμου)
  CA5 · Irma Ramirez       = Irma Carrillo Ramirez (διπλό επώνυμο στο JCS)
Περιορίζεται ανά circuit, ώστε π.χ. ένα «Ramirez» άλλου δικαστηρίου να μην ταυτίζεται.
"""
import re
import unicodedata

ALIASES = [
    ("CA5", {"richman", "owen"}),
    ("CA9", {"forrest", "hunsaker"}),
    ("CA5", {"ramirez", "carrilloramirez"}),
]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def surname_variants(surname, court):
    """{επώνυμο} ∪ {ταυτίσεις του για αυτό το circuit} — όλα κανονικοποιημένα (πεζά, χωρίς κενά)."""
    n = norm(surname)
    out = {n} if n else set()
    for c, group in ALIASES:
        if c == court and n in group:
            out |= group
    return out

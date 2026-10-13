#!/usr/bin/env python3
"""
judge_aliases.py — Κοινός πίνακας ταυτίσεων δικαστών (οδηγίες καθηγητή, 2026-10-12 / 2026-10-13)
-----------------------------------------------------------------------------------------------
Εφαρμόζεται ΙΔΙΟΣ σε JuDJIS (enrich_ideology), JCS και FJC (ideology_fallback).

1. ALIASES — ίδια πρόσωπα με διαφορετικό επώνυμο (ανά circuit):
     CA5 · Priscilla Richman  = Priscilla Owen        (αλλαγή επωνύμου)
     CA9 · Danielle Forrest   = Danielle Hunsaker     (αλλαγή επωνύμου)
     CA5 · Irma Ramirez       = Irma Carrillo Ramirez (διπλό επώνυμο στο JCS)
2. OCR_FIX — λάθη OCR στο επώνυμο της υπογραφής (σε όλα τα δικαστήρια). Το `author_str` ΔΕΝ
   αλλάζει· η διόρθωση χρησιμοποιείται μόνο στην αντιστοίχιση.
3. Αρχικά (2026-10-13): `initials_ok()` — όταν ένα επώνυμο αντιστοιχεί σε ≥2 δικαστές
   (Smith/Nelson/Thomas στο CA9, Friedman visiting κ.λπ.), κρατιούνται μόνο όσοι έχουν συμβατά
   αρχικά. Αν μένουν ≥2 ή 0 → κενό (όχι το πρώτο match).
"""
import re
import unicodedata

ALIASES = [
    ("CA5", {"richman", "owen"}),
    ("CA9", {"forrest", "hunsaker"}),
    ("CA5", {"ramirez", "carrilloramirez"}),
]

OCR_FIX = {
    "ikluta": "ikuta", "ieuta": "ikuta",
    "mekeown": "mckeown",
    "grajber": "graber",
    "murgia": "murguia",
    "reayley": "reavley",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def surname_variants(surname, court):
    """{επώνυμο (διορθωμένο OCR)} ∪ {ταυτίσεις για αυτό το circuit} — κανονικοποιημένα."""
    n = norm(surname)
    out = {n} if n else set()
    if n in OCR_FIX:
        out.add(OCR_FIX[n])
    for c, group in ALIASES:
        if c == court and out & group:
            out |= group
    return out


# ---------------------------------------------------------------- αρχικά
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def initials_of_name(*parts):
    """('Ryan', 'Douglas') → 'RD' · ('N[orman]', 'Randy') → 'NR' · ('Milan',) → 'M'."""
    out = ""
    for p in parts:
        for tok in re.split(r"[\s.]+", re.sub(r"[\[\]]", "", p or "")):
            if tok and tok.lower() not in SUFFIX and tok[0].isalpha():
                out += tok[0].upper()
    return out


def parse_initials(s):
    """'R.D.' → 'RD' · 'N.R.' → 'NR' · '' → ''."""
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def initials_ok(author_ini, cand_ini):
    """Συμβατά αρχικά; author_ini/cand_ini σε μορφή 'RD'. Χωρίς αρχικά (κάποιας πλευράς) → True.
    Ίδιο 1ο αρχικό (και ίδιο 2ο, αν το έχουν και οι δύο)· ή 1 αρχικό συγγραφέα = 2ο του υποψηφίου
    (δικαστές γνωστοί με το μεσαίο όνομα, π.χ. «W. Eugene Davis»)."""
    a, c = parse_initials(author_ini), parse_initials(cand_ini)
    if not a or not c:
        return True
    if a[0] == c[0]:
        return len(a) < 2 or len(c) < 2 or a[1] == c[1]
    return len(a) == 1 and len(c) >= 2 and a[0] == c[1]


def initials_conflict(author_ini, cand_ini):
    """Για ΜΟΝΑΔΙΚΟ υποψήφιο: σύγκρουση μόνο αν ΚΑΝΕΝΑ αρχικό του συγγραφέα δεν υπάρχει στα αρχικά
    του υποψηφίου (π.χ. H.A. Thomas vs Sidney Thomas στο JuDJIS, που έχει μόνο τον Sidney).
    Ανεκτικό, ώστε «W.E. Davis» να ταιριάζει και με «Eugene Davis»."""
    a, c = parse_initials(author_ini), parse_initials(cand_ini)
    return bool(a and c and not set(a) & set(c))

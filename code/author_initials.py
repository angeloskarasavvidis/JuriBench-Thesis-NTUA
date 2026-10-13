#!/usr/bin/env python3
"""
author_initials.py — Αρχικά του συγγραφέα (οδηγία καθηγητή, 2026-10-13)
----------------------------------------------------------------------
Το `parse_author.py` (καθηγητή) ΔΕΝ αλλάζει: δίνει μόνο το επώνυμο. Εδώ βρίσκουμε τα αρχικά του
ΙΔΙΟΥ δικαστή, για να ξεχωρίζουν συνωνυμίες (M. Smith / N.R. Smith, R. Nelson / D.W. Nelson,
S.R. Thomas / H.A. Thomas, visiting Friedman κ.λπ.). Σειρά πηγών:

  1. signature  : ακριβώς η υπογραφή που βρήκε το parse_author (ίδια patterns, με τη γραμμή
                  «Before» αφαιρεμένη) → τα ονόματα ΠΡΙΝ το επώνυμο: «N.R. SMITH, Circuit Judge:»
                  → N.R. · «W. EUGENE DAVIS, Circuit Judge:» → W.E.
  2. opinion_by : «Opinion by Judge Milan D. Smith, Jr.» → M.D.
  3. panel      : γραμμή «Before: …» ή υποσημείωση «The Honorable … sitting by designation» —
                  ΜΟΝΟ αν υπάρχει ένα όνομα με αυτό το επώνυμο → «Ryan D. Nelson» → R.D.
Αλλιώς κενό. Αποτέλεσμα σε μορφή «R.D.» και πηγή (signature / opinion_by / panel / "").
"""
import re

from parse_author import AUTHOR_CHARS, NOT_NAMES, OPINION_BY_PAT, PANEL_PAT, SIGNATURE_PATS

STOP = {"opinion", "order", "memorandum", "per", "curiam", "summary", "judge", "judges", "honorable",
        "the", "by", "and", "chief", "senior", "circuit", "district", "court", "concurrence", "dissent",
        "amended", "filed", "before", "with", "of", "for", "en", "banc", "panel", "justice", "hon"} | NOT_NAMES
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}
INITIAL = re.compile(r"^(?:[A-Z]\.){1,3}$")
WORD = re.compile(r"^[A-Z][A-Za-z'’\-]*[A-Za-z]$")   # όχι «O’» / «D'» (μέρος επωνύμου: O’SCANNLAIN)


def _fmt(letters):
    return "".join(f"{c}." for c in letters) if letters else ""


def _tokens_to_initials(tokens, upper_style):
    """Λίστα tokens (με τη σειρά) → 'RD'. upper_style: αν το επώνυμο είναι ΚΕΦΑΛΑΙΑ, δέχεται μόνο
    ΚΕΦΑΛΑΙΕΣ λέξεις (π.χ. «W. EUGENE DAVIS»)· αλλιώς λέξεις Title-case («Milan D. Smith»)."""
    out = ""
    for t in tokens:
        if INITIAL.match(t):
            out += t.replace(".", "")
        elif WORD.match(t) and t.lower() not in SUFFIX:
            if upper_style != t.isupper():
                return None
            out += t[0]
        else:
            return None
    return out


def _before(text_before, surname):
    """Τα tokens ΑΚΡΙΒΩΣ πριν από το επώνυμο (έως 3), σταματώντας σε στίξη / stop-word."""
    toks = text_before.split()
    picked = []
    for t in reversed(toks[-3:]):
        if t.endswith((",", ":", ";", ")")) or t.strip(".").lower() in STOP or t.lower().strip(".") in SUFFIX:
            break
        if not (INITIAL.match(t) or WORD.match(t)):
            break
        picked.insert(0, t)
    return picked


def _from_signature(body, surname):
    hits = [next((m for m in p.finditer(body) if m.group(1).lower() not in NOT_NAMES), None)
            for p in SIGNATURE_PATS]
    hits = [m for m in hits if m]
    if not hits:
        return ""
    m = min(hits, key=lambda h: h.start())
    if m.group(1) != surname:
        return ""
    toks = _before(body[max(0, m.start() - 80):m.start()], surname)
    # το μεγαλύτερο «δεξί» κομμάτι που είναι έγκυρο όνομα (π.χ. «… Thomas H.A.» → «H.A.»)
    for k in range(len(toks), 0, -1):
        ini = _tokens_to_initials(toks[-k:], surname.isupper())
        if ini:
            return ini
    return ""


def _style_initials(toks):
    words = [t for t in toks if WORD.match(t)]
    return _tokens_to_initials(toks, bool(words) and all(t.isupper() for t in words))


def _from_opinion_by(head, surname):
    m = OPINION_BY_PAT.search(head)
    if not m:
        return ""
    words = [w for w in m.group(1).split() if w.strip(".").lower() not in SUFFIX]
    if not words or words[-1].lower() != surname.lower():
        return ""
    toks = [w + "." if re.match(r"^[A-Z]$", w) else w for w in words[:-1]]
    return (_style_initials(toks) or "") if toks else ""


def _from_panel(head, surname):
    """Γραμμή «Before:» + υποσημειώσεις «The Honorable … SURNAME» — μόνο αν 1 διακριτό όνομα."""
    s = r"(?i:" + re.escape(surname) + r")\b"
    zones = []
    pm = PANEL_PAT.search(head)
    if pm:
        zones.append(pm.group(0))
    zones += [m.group(0) for m in re.finditer(r"The\s+Honorable\s+(?:[A-Z][\w.'’\-]*\s+){0,3}" + s, head)]
    found = set()
    for z in zones:
        zz = re.sub(r"\s+", " ", z)
        for m in re.finditer(s, zz):
            toks = _before(zz[max(0, m.start() - 80):m.start()], surname)
            ini = _style_initials(toks) if toks else ""
            if ini:
                found.add(ini)
    return found.pop() if len(found) == 1 else ""


def author_initials(text, surname, source):
    """→ (initials 'R.D.', πηγή) ή ('', '')."""
    if not surname:
        return "", ""
    head = (text or "")[:AUTHOR_CHARS]
    if source == "signature":
        body = PANEL_PAT.sub(" ", head, count=1)
        ini = _from_signature(body, surname)
        if ini:
            return _fmt(ini), "signature"
    ini = _from_opinion_by(head, surname)
    if ini:
        return _fmt(ini), "opinion_by"
    ini = _from_panel(head, surname)
    if ini:
        return _fmt(ini), "panel"
    return "", ""

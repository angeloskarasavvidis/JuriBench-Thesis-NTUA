#!/usr/bin/env python3
"""
enrich_case_fields.py
---------------------
ΕΠΕΚΤΑΣΗ του pipeline (πέρα από τα scripts του καθηγητή). Παράγει τα πεδία
που λείπουν για το task "δίνω υπόθεση -> παράγω πόρισμα + έκβαση":

  INPUT (conditioning):  issue_text  (το νομικό ερώτημα)
                         facts       (τα πραγματικά περιστατικά)
  OUTCOME (target/label): disposition        (affirmed/reversed/vacated/remanded/...)
                          prevailing_party    (appellant/appellee/petitioner/respondent/...)

Ομοιόμορφα για ΟΛΑ τα courts (SCOTUS + CA5 + CA9), εξαγωγή απευθείας από το
opinion_text με LLM. ΔΕΝ βασίζεται στο stub syllabus (που βρέθηκε ~15 λέξεις).

Σημείωση για την "έκβαση":
  - Εδώ `disposition`/`prevailing_party` = ΔΙΑΔΙΚΑΣΤΙΚΗ έκβαση (ποιος κέρδισε /
    affirm-reverse), ομοιόμορφη σε όλα τα courts -> κατάλληλη ως target/label.
  - Το υπάρχον `decision_direction` (από enrich_ideology, SCDB, ΜΟΝΟ SCOTUS) είναι
    η ΙΔΕΟΛΟΓΙΚΗ κατεύθυνση (conservative/liberal) — διαφορετικό πράγμα, μένει ως έχει.

Backend: OpenAI-compatible chat API (π.χ. OpenRouter), ρυθμιζόμενο από .env:
  LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
(Εναλλακτικά μπορείς να συνδέσεις τοπικό HF μοντέλο — δες generate() παρακάτω.)

Resumable: rerun αγνοεί γραμμές που ήδη έχουν issue_text ΚΑΙ facts.
Γράφει incrementally (κάθε N γραμμές) ώστε διακοπή να μη χάνει δουλειά.

Usage:
  python enrich_case_fields.py
  python enrich_case_fields.py --input data/juribench_dataset.csv --output data/juribench_cases.csv
  python enrich_case_fields.py --limit 20        # μικρό pilot για έλεγχο ποιότητας
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import requests

csv.field_size_limit(sys.maxsize)

NEW_COLS = [
    "issue_text", "issue_text_source",
    "facts", "facts_source",
    "disposition", "prevailing_party", "outcome_source",
]

# opinion head (issue+facts συνήθως μπροστά) + tail (disposition συνήθως στο τέλος)
HEAD_CHARS = 8000
TAIL_CHARS = 2000

SYSTEM_PROMPT = (
    "You are a legal analyst. You read a U.S. court opinion and extract structured "
    "fields. Base everything ONLY on the opinion text provided. Do not invent facts, "
    "citations, or holdings. If a field is not determinable, use an empty string for "
    "text fields or \"unclear\" for the categorical fields. Respond with STRICT JSON only."
)

USER_TEMPLATE = """Read the following court opinion (may be truncated) and return JSON with keys:

- "issue_text": 1-3 sentences stating the legal question(s) the court decided (neutral, no answer).
- "facts": 2-5 sentences of the factual/procedural background, WITHOUT revealing the court's holding or outcome.
- "disposition": one of ["affirmed","reversed","vacated","remanded","affirmed_in_part","dismissed","denied","granted","mixed","other","unclear"].
- "prevailing_party": one of ["appellant","appellee","petitioner","respondent","plaintiff","defendant","government","mixed","unclear"].

IMPORTANT: "issue_text" and "facts" must NOT leak the outcome/holding (they are model inputs; the outcome is the label).

OPINION:
\"\"\"
{body}
\"\"\"

JSON:"""


def build_body(opinion_text):
    t = (opinion_text or "").strip()
    if len(t) <= HEAD_CHARS + TAIL_CHARS:
        return t
    return t[:HEAD_CHARS] + "\n...\n" + t[-TAIL_CHARS:]


def generate(body, model, base_url, api_key, timeout=90):
    """OpenAI-compatible chat completion. Returns dict parsed from JSON, or {}.

    Για τοπικό HF μοντέλο: αντικατέστησε το σώμα αυτής της συνάρτησης με μια κλήση
    στο δικό σου pipeline (π.χ. ίδιο μοτίβο με lawma_label.py) και επίστρεψε το dict.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(body=body)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(1, 5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                wait = attempt * 10
                print(f"    HTTP {r.status_code} — wait {wait}s ({attempt}/4)")
                time.sleep(wait)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except json.JSONDecodeError:
            # μοντέλο δεν επέστρεψε καθαρό JSON — προσπάθησε να απομονώσεις το block
            try:
                s = content[content.index("{"): content.rindex("}") + 1]
                return json.loads(s)
            except Exception:
                return {}
        except requests.RequestException as e:
            wait = attempt * 10
            print(f"    {type(e).__name__} — wait {wait}s ({attempt}/4)")
            time.sleep(wait)
    return {}


VALID_DISPOSITION = {"affirmed","reversed","vacated","remanded","affirmed_in_part",
                     "dismissed","denied","granted","mixed","other","unclear"}
VALID_PARTY = {"appellant","appellee","petitioner","respondent","plaintiff",
               "defendant","government","mixed","unclear"}


def apply_result(row, res):
    row["issue_text"]        = (res.get("issue_text") or "").strip()
    row["issue_text_source"] = "llm_extract" if row["issue_text"] else ""
    row["facts"]             = (res.get("facts") or "").strip()
    row["facts_source"]      = "llm_extract" if row["facts"] else ""
    disp = (res.get("disposition") or "unclear").strip().lower()
    row["disposition"]       = disp if disp in VALID_DISPOSITION else "other"
    party = (res.get("prevailing_party") or "unclear").strip().lower()
    row["prevailing_party"]  = party if party in VALID_PARTY else "unclear"
    row["outcome_source"]    = "llm_extract"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--limit",  type=int, default=0, help="process at most N to-do rows (pilot)")
    ap.add_argument("--flush-every", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds between calls (μόνο για --workers 1· αγνοείται στο parallel)")
    ap.add_argument("--workers", type=int, default=8,
                    help="ταυτόχρονες κλήσεις LLM (1 = παλιά σειριακή συμπεριφορά)")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    data = root / "data"
    input_path  = Path(args.input)  if args.input  else data / "juribench_dataset.csv"
    output_path = Path(args.output) if args.output else data / "juribench_cases.csv"

    model    = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
    base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    api_key  = os.environ.get("LLM_API_KEY", "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")
    if not api_key:
        raise SystemExit("Set LLM_API_KEY in .env (see .env.example).")

    # resume από υπάρχον output αν υπάρχει, αλλιώς από input
    src = output_path if output_path.exists() else input_path
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())
    for c in NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)
    for row in rows:
        for c in NEW_COLS:
            row.setdefault(c, "")

    def is_done(r):
        return (r.get("issue_text") or "").strip() and (r.get("facts") or "").strip()

    todo = [r for r in rows if not is_done(r)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Input : {src}")
    print(f"Loaded: {len(rows)} rows | to-do: {len(todo)} | model: {model}")

    save_lock = threading.Lock()

    def save():
        # κλείδωμα: πολλά threads μπορεί να ζητήσουν save ταυτόχρονα
        with save_lock:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader(); w.writerows(rows)

    def work(row):
        """Μία υπόθεση: κλήση LLM + εφαρμογή αποτελέσματος πάνω στο row. Thread-safe:
        κάθε thread γράφει ΜΟΝΟ στο δικό του row (χωριστά dict keys)."""
        body = build_body(row.get("opinion_text"))
        if not body:
            return None
        res = generate(body, model, base_url, api_key)
        apply_result(row, res)
        return row

    done = 0
    if args.workers <= 1:
        # ── σειριακό (παλιά συμπεριφορά) ──
        for i, row in enumerate(todo, 1):
            r = work(row)
            if r is None:
                continue
            done += 1
            print(f"  [{i}/{len(todo)}] {row.get('case_name','')[:45]:<45} "
                  f"disp={row['disposition']:<10} issue={'Y' if row['issue_text'] else '-'} "
                  f"facts={'Y' if row['facts'] else '-'}")
            if done % args.flush_every == 0:
                save()
            time.sleep(args.sleep)
    else:
        # ── παράλληλο: πολλές ταυτόχρονες κλήσεις LLM ──
        print(f"Parallel mode: {args.workers} workers")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(work, row): row for row in todo}
            for fut in as_completed(futures):
                row = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    print(f"    worker error: {type(e).__name__}: {e}")
                    r = None
                if r is None:
                    continue
                done += 1
                print(f"  [{done}/{len(todo)}] {row.get('case_name','')[:45]:<45} "
                      f"disp={row['disposition']:<10} issue={'Y' if row['issue_text'] else '-'} "
                      f"facts={'Y' if row['facts'] else '-'}")
                if done % args.flush_every == 0:
                    save()

    save()
    have_issue = sum(1 for r in rows if (r.get("issue_text") or "").strip())
    have_facts = sum(1 for r in rows if (r.get("facts") or "").strip())
    print(f"\nSaved -> {output_path}")
    print(f"  issue_text: {have_issue}/{len(rows)} ({have_issue/len(rows):.1%})")
    print(f"  facts     : {have_facts}/{len(rows)} ({have_facts/len(rows):.1%})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
validate_classifier.py
-----------------------
Validate GPT issue_area classification accuracy against SCDB ground truth.
Evaluates on SCOTUS cases (which carry SCDB labels) from the juribench CSV.

Usage:
  python validate_classifier.py [options]

Options:
  --input FILE    CSV path (default: juribench_dataset_04_06_2026.csv)
  --model MODEL   OpenRouter model ID (default: openai/gpt-4o)
  --sample N      Max SCOTUS cases to evaluate (default: 100, 0 = all)
  --output FILE   Save per-case results to a CSV (optional)
  --collapse      Map 14 SCDB categories -> 6 merged categories (easier task)
  --sleep SECS    Pause between API calls (default: 0.5)

API key — set once in .env at the project root (git-ignored):
  OPENROUTER_KEY=sk-or-v1-...

Or via environment variable (overrides .env):
  Windows PowerShell : $env:OPENROUTER_KEY = "sk-or-v1-..."
  bash/zsh           : export OPENROUTER_KEY="sk-or-v1-..."

Requires: pip install requests python-dotenv
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())  # walks up from CWD until it finds .env

csv.field_size_limit(sys.maxsize)

# ── SCDB issue_area taxonomy ───────────────────────────────────────────────────
ISSUE_AREA_LABELS = {
    1:  "Criminal Procedure",
    2:  "Civil Rights",
    3:  "First Amendment",
    4:  "Due Process",
    5:  "Privacy",
    6:  "Attorneys' Fees",
    7:  "Unions",
    8:  "Economic Activity",
    9:  "Judicial Power",
    10: "Federalism",
    11: "Interstate Relations",
    12: "Federal Taxation",
    13: "Miscellaneous",
    14: "Private Action",
}

# 14 → 6 collapsed categories (covers ~85% of circuit caseload)
COLLAPSE_MAP = {
    1: 1, 2: 2, 3: 3,
    4: 4, 5: 4,                   # Due Process + Privacy
    6: 5, 7: 5, 8: 5, 12: 5,     # Economic / Labor / Tax
    9: 6, 10: 6, 11: 6, 13: 6, 14: 6,  # Judicial / Other
}
COLLAPSE_LABELS = {
    1: "Criminal Procedure",
    2: "Civil Rights",
    3: "First Amendment",
    4: "Due Process / Privacy",
    5: "Economic / Labor / Tax",
    6: "Judicial / Other",
}

# ── Prompts ───────────────────────────────────────────────────────────────────
PROMPT_14 = """\
You are a legal classifier using the SCDB (Supreme Court Database) issueArea coding scheme. \
Classify this US court opinion into exactly ONE of the 14 codes below.

IMPORTANT: Use SCDB conventions, not intuitive category names. Key rules:
- Economic Activity (8): use broadly — includes antitrust, business regulation, bankruptcy, \
corporate law, labor/employment outside unions, financial regulation, and commercial disputes.
- Judicial Power (9): only when the PRIMARY holding is about the court's own authority \
(standing, mootness, jurisdiction) — not when jurisdiction is merely a threshold issue.
- Federalism (10): only when the central question is the federal-state power balance; \
regulatory disputes with a federal agency are usually Economic Activity (8).
- Civil Rights (2): discrimination and equal protection; Criminal Procedure (1): \
mechanics of prosecution, evidence, sentencing — pick based on the PRIMARY issue.
- Miscellaneous (13): Indian affairs, patents, admiralty only — do NOT use for unusual facts.

Categories:
 1  Criminal Procedure     8  Economic Activity
 2  Civil Rights           9  Judicial Power
 3  First Amendment       10  Federalism
 4  Due Process           11  Interstate Relations
 5  Privacy               12  Federal Taxation
 6  Attorneys' Fees       13  Miscellaneous
 7  Unions                14  Private Action

Output ONLY valid JSON — no markdown fences, no text outside the JSON object.

Output format:
{{"issueArea": <int 1-14>, "confidence": <float 0.0-1.0>, "rationale": "<one sentence>"}}

Case name: {case_name}
Issue description: {issue_text}
Opinion excerpt:
{opinion_excerpt}"""

PROMPT_6 = """\
You are a legal classifier. Classify this US court opinion into exactly ONE of 6 categories.

Categories:
 1  Criminal Procedure      — arrests, searches, trials, sentencing, prisons
 2  Civil Rights            — discrimination, voting rights, civil liberties
 3  First Amendment         — speech, religion, press, assembly
 4  Due Process / Privacy   — procedural/substantive due process, takings, personal autonomy
 5  Economic / Labor / Tax  — business regulation, antitrust, unions, labor, federal taxation
 6  Judicial / Other        — jurisdiction, federalism, Indian affairs, patents, admiralty, misc

Output ONLY valid JSON:
{{"issueArea": <int 1-6>, "confidence": <float 0.0-1.0>, "rationale": "<one sentence>"}}

Case name: {case_name}
Issue description: {issue_text}
Opinion excerpt:
{opinion_excerpt}"""


# ── API call ──────────────────────────────────────────────────────────────────
def classify(case_name, issue_text, opinion_text, *, model, api_key, collapse):
    n_cats = 6 if collapse else 14
    prompt = (PROMPT_6 if collapse else PROMPT_14).format(
        case_name=case_name,
        issue_text=(issue_text or "").strip()[:600],
        opinion_excerpt=(opinion_text or "").strip()[:4000],
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
        data = json.loads(clean)
        area = int(data["issueArea"])
        conf = float(data.get("confidence", 0.0))
        if 1 <= area <= n_cats:
            return area, conf
        print(f"    out-of-range issueArea={area}", end=" ")
    except Exception as e:
        print(f"    API error: {e}", end=" ")
    return None, None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _normalize_name(name):
    return re.sub(r"\s+Revisions?:.*$", "", name or "", flags=re.IGNORECASE).strip()

def dedup_cases(rows):
    seen = set()
    out = []
    for r in rows:
        norm = _normalize_name(r.get("case_name", ""))
        key = norm or r.get("cluster_id") or r.get("date_filed", "")
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def majority_baseline(rows, collapse):
    counts = defaultdict(int)
    for r in rows:
        ia = int(r["issue_area"])
        cat = COLLAPSE_MAP.get(ia, ia) if collapse else ia
        counts[cat] += 1
    top_cat, top_n = max(counts.items(), key=lambda x: x[1])
    total = sum(counts.values())
    labs = COLLAPSE_LABELS if collapse else ISSUE_AREA_LABELS
    return top_n / total, labs.get(top_cat, str(top_cat)), dict(counts)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Validate GPT issue_area classifier on juribench data")
    default_csv = Path(__file__).parent.parent / "data" / "juribench_dataset_04_06_2026.csv"
    parser.add_argument("--input",    default=str(default_csv))
    parser.add_argument("--model",    default="openai/gpt-4o")
    parser.add_argument("--sample",   type=int, default=100, help="0 = all unique SCOTUS cases")
    parser.add_argument("--output",   default="", help="Save per-case CSV here")
    parser.add_argument("--collapse", action="store_true", help="Use 6-category mode")
    parser.add_argument("--sleep",    type=float, default=0.5)
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_KEY not found.")
        print("  Option 1 — edit .env at the project root:")
        print("             OPENROUTER_KEY=sk-or-v1-...")
        print("  Option 2 — set env var: $env:OPENROUTER_KEY = 'sk-or-v1-...'")
        sys.exit(1)

    labels = COLLAPSE_LABELS if args.collapse else ISSUE_AREA_LABELS

    print(f"Model  : {args.model}")
    print(f"Mode   : {'collapsed (6 categories)' if args.collapse else 'full (14 categories)'}")
    print(f"Input  : {args.input}")

    with open(args.input, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"Loaded : {len(all_rows)} rows")

    scotus_gt = [
        r for r in all_rows
        if r.get("jurisdiction") == "SCOTUS"
        and r.get("issue_area", "").strip()
        and r.get("issue_area_source") == "scdb"
    ]
    unique = dedup_cases(scotus_gt)
    sample = unique[: args.sample] if args.sample else unique
    print(f"SCOTUS : {len(scotus_gt)} rows → {len(unique)} unique → evaluating {len(sample)}")

    maj_acc, maj_label, cat_dist = majority_baseline(sample, args.collapse)
    print(f"Baseline (majority='{maj_label}'): {maj_acc:.1%}")
    print()

    results = []
    correct = 0
    skipped = 0

    for i, row in enumerate(sample, 1):
        case_name      = row.get("case_name", "Unknown")
        true_raw       = int(row["issue_area"])
        true_issue     = COLLAPSE_MAP.get(true_raw, true_raw) if args.collapse else true_raw
        issue_text     = row.get("issue_text", "")
        opinion        = row.get("opinion_text", "")
        syllabus       = row.get("syllabus", "")
        combined       = f"{syllabus}\n\n{opinion}".strip() if syllabus else opinion

        print(
            f"  [{i:3d}/{len(sample)}] {case_name[:52]:<52}"
            f" | true={true_issue:2d} ({labels.get(true_issue, '?')[:18]})",
            end=" ", flush=True,
        )

        pred, conf = classify(
            case_name, issue_text, combined,
            model=args.model, api_key=api_key, collapse=args.collapse,
        )

        if pred is None:
            print("→ SKIP")
            skipped += 1
        else:
            match = pred == true_issue
            correct += int(match)
            print(f"→ pred={pred:2d} ({'✓' if match else '✗'}) conf={conf:.2f}")

        results.append({
            "case_name":     case_name,
            "true_issue_raw": true_raw,
            "true_issue":    true_issue,
            "true_label":    labels.get(true_issue, "?"),
            "pred_issue":    pred,
            "pred_label":    labels.get(pred, "?") if pred else "",
            "correct":       pred == true_issue if pred is not None else False,
            "confidence":    conf,
        })

        time.sleep(args.sleep)

    # ── Summary ───────────────────────────────────────────────────────────────
    evaluated = len(sample) - skipped
    accuracy  = correct / evaluated if evaluated > 0 else 0.0

    print()
    print("=" * 65)
    print("VALIDATION RESULTS")
    print("=" * 65)
    print(f"  Model     : {args.model}")
    print(f"  Evaluated : {evaluated}  ({skipped} skipped)")
    print(f"  Correct   : {correct}")
    print(f"  Accuracy  : {accuracy:.1%}  {'✓ PASS (≥85%)' if accuracy >= 0.85 else '✗ FAIL (<85%)'}")
    print(f"  Baseline  : {maj_acc:.1%}  (majority class = '{maj_label}')")
    print()

    by_cat = defaultdict(lambda: {"total": 0, "correct": 0, "conf_sum": 0.0})
    confusion = defaultdict(int)
    for r in results:
        if r["pred_issue"] is None:
            continue
        cat = r["true_issue"]
        by_cat[cat]["total"]   += 1
        by_cat[cat]["correct"] += int(r["correct"])
        by_cat[cat]["conf_sum"] += r["confidence"] or 0.0
        if not r["correct"]:
            confusion[(r["true_issue"], r["pred_issue"])] += 1

    print("Per-category accuracy:")
    for cat in sorted(by_cat):
        t = by_cat[cat]["total"]
        c = by_cat[cat]["correct"]
        avg_conf = by_cat[cat]["conf_sum"] / t if t else 0.0
        bar = "█" * c + "░" * (t - c)
        print(f"  {cat:2d} {labels.get(cat, '?'):<24} {c}/{t:<3}  {bar:<24}  conf={avg_conf:.2f}")

    if confusion:
        print()
        print("Top misclassifications:")
        for (true, pred), count in sorted(confusion.items(), key=lambda x: -x[1])[:10]:
            print(
                f"  {labels.get(true, '?'):<24} → {labels.get(pred, '?'):<24} × {count}"
            )

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        print(f"\nPer-case results saved → {args.output}")

    if accuracy < 0.85:
        print()
        print("Next steps:")
        if "mini" in args.model:
            print("  1. Upgrade model : --model openai/gpt-4o")
        if not args.collapse:
            print("  2. Easier task   : --collapse  (6-class mode)")
        print("  3. Extend ground truth: human-label CA5/CA9 rows (currently 0 labels)")


if __name__ == "__main__":
    main()

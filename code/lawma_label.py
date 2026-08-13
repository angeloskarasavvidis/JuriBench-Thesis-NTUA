#!/usr/bin/env python3
"""
lawma_label.py
--------------
Use Lawma 70B to assign issue_area labels to CA5/CA9 cases (no SCDB ground truth).
Also runs validation on SCOTUS cases (which have SCDB labels) so you can report accuracy.

Model: ricdomolm/lawma-70b  (Llama 3 70B fine-tuned on 260 SCDB/Songer tasks)
Format: MMLU multiple-choice — model outputs a single letter (A–N).

Usage:
  python lawma_label.py                        # label CA5/CA9, validate on SCOTUS
  python lawma_label.py --validate-only        # SCOTUS validation only (no labeling)
  python lawma_label.py --model lawma-8b       # use 8B model instead

Requirements:
  pip install transformers torch accelerate bitsandbytes

Output:
  data/juribench_labeled.csv   — full dataset with issue_area filled in for CA5/CA9
  data/lawma_validation.csv    — SCOTUS per-case results vs SCDB ground truth
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

csv.field_size_limit(sys.maxsize)

# ── SCDB issue_area mapping ────────────────────────────────────────────────────
LETTERS = list("ABCDEFGHIJKLMN")   # A=1 … N=14

CHOICES = {
    "A": (1,  "Criminal Procedure"),
    "B": (2,  "Civil Rights"),
    "C": (3,  "First Amendment"),
    "D": (4,  "Due Process"),
    "E": (5,  "Privacy"),
    "F": (6,  "Attorneys"),
    "G": (7,  "Unions"),
    "H": (8,  "Economic Activity"),
    "I": (9,  "Judicial Power"),
    "J": (10, "Federalism"),
    "K": (11, "Interstate Relations"),
    "L": (12, "Federal Taxation"),
    "M": (13, "Miscellaneous"),
    "N": (14, "Private Action"),
}

CHOICE_BLOCK = "\n".join(f"{k}. {v[1]}" for k, v in CHOICES.items())

# ── Prompt (exact Lawma format) ────────────────────────────────────────────────
def build_prompt(row):
    opinion   = (row.get("opinion_text", "") or "").strip()
    syllabus  = (row.get("syllabus", "") or "").strip()
    issue_txt = (row.get("issue_text", "") or "").strip()

    # Compose text: syllabus → issue_text → opinion (trimmed)
    parts = []
    if syllabus:   parts.append(syllabus[:500])
    if issue_txt:  parts.append(issue_txt[:300])
    if opinion:    parts.append(opinion[:3000])
    body = "\n\n".join(parts)

    return (
        f"{body}\n\n"
        f"Question: What is the issue area of the decision?\n"
        f"{CHOICE_BLOCK}\n"
        f"Answer:"
    )


# ── Model loader ───────────────────────────────────────────────────────────────
def load_model(model_id):
    print(f"Loading {model_id} …")
    tokenizer = AutoTokenizer.from_pretrained(model_id)

    # GB10 / unified-memory systems: bitsandbytes cannot query VRAM via nvidia-smi,
    # so device_map="auto" incorrectly offloads layers to CPU.
    # Force everything onto cuda:0 — unified memory has 128GB so 70B in bfloat16
    # (~140GB) is tight; use 4-bit (~35GB) with explicit device placement.
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb,
        device_map={"": "cuda:0"},   # force all layers onto GPU 0
        torch_dtype=torch.bfloat16,
    )
    model.eval()
    print("Model ready.\n")
    return tokenizer, model


# ── Single inference — returns predicted letter via next-token logits ──────────
def predict(prompt, tokenizer, model):
    # Get token IDs for each answer letter
    letter_ids = [tokenizer.encode(f" {l}", add_special_tokens=False)[-1] for l in LETTERS]

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    # Logits of the very next token (after "Answer:")
    next_logits = outputs.logits[0, -1, :]
    letter_logits = torch.tensor([next_logits[i].item() for i in letter_ids])
    best = letter_logits.argmax().item()
    predicted_letter = LETTERS[best]

    # Softmax over the 14 choices → confidence
    probs = torch.softmax(letter_logits, dim=0)
    confidence = probs[best].item()

    issue_num, issue_label = CHOICES[predicted_letter]
    return issue_num, issue_label, predicted_letter, round(confidence, 3)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",         default=None,         help="CSV path (auto-detected if omitted)")
    parser.add_argument("--model",         default="ricdomolm/lawma-70b")
    parser.add_argument("--validate-only", action="store_true",  help="Only run SCOTUS validation, skip labeling")
    parser.add_argument("--output-csv",    default=None,         help="Labeled CSV (default: data/juribench_labeled.csv)")
    parser.add_argument("--val-csv",       default=None,         help="Validation CSV (default: data/lawma_validation.csv)")
    args = parser.parse_args()

    root     = Path(__file__).parent.parent
    data_dir = root / "data"

    input_path  = Path(args.input) if args.input else data_dir / "juribench_dataset.csv"
    output_path = Path(args.output_csv) if args.output_csv else data_dir / "juribench_labeled.csv"
    val_path    = Path(args.val_csv)    if args.val_csv    else data_dir / "lawma_validation.csv"

    print(f"Input : {input_path}")

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded: {len(rows)} rows\n")

    scotus_rows  = [r for r in rows
                    if r.get("jurisdiction") == "SCOTUS"
                    and r.get("issue_area", "").strip()
                    and r.get("issue_area_source") == "scdb"]
    circuit_rows = [r for r in rows if r.get("jurisdiction") in ("CA5", "CA9")]
    print(f"SCOTUS : {len(scotus_rows)} rows with SCDB ground truth")
    print(f"CA5/CA9: {len(circuit_rows)} rows (no ground truth — will be labeled)")

    tokenizer, model = load_model(args.model)

    # ── Dedup SCOTUS by normalized case name ─────────────────────────────────
    def _normalize(name):
        import re as _re
        return _re.sub(r"\s+Revisions?:.*$", "", name or "", flags=_re.IGNORECASE).strip()

    seen, unique_scotus = set(), []
    for r in scotus_rows:
        key = _normalize(r.get("case_name", "")) or r.get("cluster_id", "")
        if key not in seen:
            seen.add(key)
            unique_scotus.append(r)
    print(f"SCOTUS : {len(scotus_rows)} rows → {len(unique_scotus)} unique cases (after dedup)")

    # ── Validation on SCOTUS ──────────────────────────────────────────────────
    print("\n── SCOTUS validation ──────────────────────────────────────────")
    if not unique_scotus:
        print("Skipped: no SCOTUS rows with issue_area_source == 'scdb' (SCDB join not yet run).")
    else:
        val_results = []
        correct = 0
        for i, row in enumerate(unique_scotus, 1):
            true_issue = row.get("issue_area", "").strip()
            true_num   = int(true_issue) if true_issue else None
            prompt     = build_prompt(row)

            t0 = time.time()
            pred_num, pred_label, pred_letter, conf = predict(prompt, tokenizer, model)
            elapsed = time.time() - t0

            match = (pred_num == true_num) if true_num else None
            if match: correct += 1

            true_label = CHOICES.get(LETTERS[true_num - 1], ("?", "?"))[1] if true_num else "?"
            symbol = "✓" if match else ("?" if match is None else "✗")
            print(f"  [{i:3d}/{len(unique_scotus)}] {row.get('case_name','')[:50]:<50} "
                  f"true={true_num or '?':>2} → pred={pred_num:2d} {symbol}  conf={conf:.2f}  ({elapsed:.1f}s)")

            val_results.append({
                "case_name":   row.get("case_name", ""),
                "jurisdiction": row.get("jurisdiction", ""),
                "true_issue":  true_num,
                "true_label":  true_label,
                "pred_issue":  pred_num,
                "pred_label":  pred_label,
                "pred_letter": pred_letter,
                "correct":     match,
                "confidence":  conf,
            })

        evaluated = sum(1 for r in val_results if r["correct"] is not None)
        accuracy  = correct / evaluated if evaluated else 0
        print(f"\nSCOTUS accuracy: {correct}/{evaluated} = {accuracy:.1%}")

        with open(val_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(val_results[0].keys()))
            w.writeheader(); w.writerows(val_results)
        print(f"Validation saved → {val_path}")

    if args.validate_only:
        return

    # ── Label CA5/CA9 ─────────────────────────────────────────────────────────
    print("\n── CA5/CA9 labeling ────────────────────────────────────────────")
    label_results = {}
    for i, row in enumerate(circuit_rows, 1):
        key    = row.get("cluster_id") or row.get("case_name", "")
        prompt = build_prompt(row)

        t0 = time.time()
        pred_num, pred_label, pred_letter, conf = predict(prompt, tokenizer, model)
        elapsed = time.time() - t0

        print(f"  [{i:3d}/{len(circuit_rows)}] {row.get('case_name','')[:50]:<50} "
              f"→ {pred_num:2d} ({pred_label})  conf={conf:.2f}  ({elapsed:.1f}s)")

        label_results[key] = {"issue_area": pred_num, "issue_area_source": "lawma-70b", "lawma_conf": conf}

    # ── Write labeled CSV ─────────────────────────────────────────────────────
    fieldnames = list(rows[0].keys())
    if "issue_area_source" not in fieldnames: fieldnames.append("issue_area_source")
    if "lawma_conf"        not in fieldnames: fieldnames.append("lawma_conf")

    out_rows = []
    for row in rows:
        r = dict(row)
        if r.get("jurisdiction") in ("CA5", "CA9"):
            key = r.get("cluster_id") or r.get("case_name", "")
            if key in label_results:
                r["issue_area"]        = label_results[key]["issue_area"]
                r["issue_area_source"] = label_results[key]["issue_area_source"]
                r["lawma_conf"]        = label_results[key]["lawma_conf"]
        out_rows.append(r)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(out_rows)
    print(f"\nLabeled dataset saved → {output_path}")
    print(f"  SCOTUS: labels unchanged (SCDB ground truth kept)")
    print(f"  CA5/CA9: {len(circuit_rows)} rows labeled by Lawma 70B")


if __name__ == "__main__":
    main()

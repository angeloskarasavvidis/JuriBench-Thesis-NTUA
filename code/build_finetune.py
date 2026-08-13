#!/usr/bin/env python3
"""
build_finetune.py
-----------------
Στάδιο 1: μετατρέπει τα splits (data/splits/{train,val,test}.jsonl) σε chat *messages*
μορφή, ΕΤΟΙΜΗ για QLoRA/LoRA με HF TRL SFTTrainer (tokenizer.apply_chat_template).
Model-agnostic: βγάζει {"messages":[{role,content}...]} — κάθε chat μοντέλο εφαρμόζει
το δικό του template στο training. Δεν κουμπώνει σε συγκεκριμένο tokenizer.

Δύο task variants:
  generation : input(facts+issue+court) -> σκεπτικό/opinion + "Disposition: X"
  predict    : input(facts+issue+court) -> μόνο το disposition label   (LJP benchmark)

Παράμετροι:
  --task {generation,predict,both}   (default both)
  --max-target-chars N               cap μήκους opinion (granularity· 0 = χωρίς cap)
  --include-ideology                 βάλε το ideology στο prompt (default: OFF, eval-only)
  --outdir DIR                       default data/finetune

Έξοδος:
  data/finetune/<task>/{train,val,test}.jsonl
  Κάθε γραμμή: {"messages":[...], "meta":{id,jurisdiction,disposition,ideology,...}}

Usage:
  python build_finetune.py
  python build_finetune.py --task generation --max-target-chars 8000
"""

import argparse
import json
from pathlib import Path

DISPOSITIONS = ["affirmed", "reversed", "vacated", "remanded", "affirmed_in_part",
                "dismissed", "denied", "granted", "mixed", "other", "unclear"]

GEN_SYSTEM = (
    "You are a U.S. appellate judge. Given the facts of a case and the legal question "
    "presented, write the court's reasoned opinion in the appropriate judicial register, "
    "then state the disposition on a final line as 'Disposition: <label>'."
)
PRED_SYSTEM = (
    "You are a legal judgment predictor for U.S. appellate cases. Given the facts and the "
    "legal question, respond with ONLY the case disposition, chosen from: "
    + ", ".join(DISPOSITIONS) + "."
)


def user_prompt(rec, include_ideology):
    inp = rec["input"]
    parts = [f"Court: {inp.get('court','')}"]
    if include_ideology:
        ide = rec.get("eval_meta", {}).get("ideology", "")
        if ide:
            parts.append(f"Authoring judge ideology: {ide}")
    parts.append(f"\nQuestion presented:\n{inp.get('issue_text','').strip()}")
    parts.append(f"\nFacts:\n{inp.get('facts','').strip()}")
    return "\n".join(parts).strip()


def gen_target(rec, max_chars):
    t = rec["targets"]
    op = t.get("opinion_text_capped") or t.get("opinion_text") or ""
    if max_chars and len(op) > max_chars:
        op = op[:max_chars]
    disp = t.get("disposition", "unclear")
    return f"{op.strip()}\n\nDisposition: {disp}"


def meta_of(rec):
    em = rec.get("eval_meta", {})
    return {
        "id": rec.get("id", ""),
        "jurisdiction": rec.get("jurisdiction", ""),
        "case_name": rec.get("case_name", ""),
        "disposition": rec["targets"].get("disposition", ""),
        "prevailing_party": rec["targets"].get("prevailing_party", ""),
        "ideology": em.get("ideology", ""),
        "ideology_score": em.get("ideology_score", ""),
        "issue_area": em.get("issue_area", ""),
        "decision_direction": em.get("decision_direction", ""),
        "outcome_usable": rec.get("outcome_usable", True),
    }


def build_record(rec, task, max_chars, include_ideology):
    up = user_prompt(rec, include_ideology)
    if task == "generation":
        msgs = [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": up + "\n\nWrite the opinion."},
            {"role": "assistant", "content": gen_target(rec, max_chars)},
        ]
    else:  # predict
        msgs = [
            {"role": "system", "content": PRED_SYSTEM},
            {"role": "user", "content": up + "\n\nDisposition:"},
            {"role": "assistant", "content": rec["targets"].get("disposition", "unclear")},
        ]
    return {"messages": msgs, "meta": meta_of(rec)}


def process(task, splits_dir, outdir, max_chars, include_ideology):
    d = outdir / task
    d.mkdir(parents=True, exist_ok=True)
    counts = {}
    for split in ("train", "val", "test"):
        src = splits_dir / f"{split}.jsonl"
        recs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
        with open(d / f"{split}.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(build_record(r, task, max_chars, include_ideology),
                                   ensure_ascii=False) + "\n")
        counts[split] = len(recs)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--task", choices=["generation", "predict", "both"], default="both")
    ap.add_argument("--max-target-chars", type=int, default=0)
    ap.add_argument("--include-ideology", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    splits_dir = Path(args.splits) if args.splits else root / "data" / "splits"
    outdir = Path(args.outdir) if args.outdir else root / "data" / "finetune"

    tasks = ["generation", "predict"] if args.task == "both" else [args.task]
    for task in tasks:
        c = process(task, splits_dir, outdir, args.max_target_chars, args.include_ideology)
        print(f"[{task}] train {c['train']} · val {c['val']} · test {c['test']} "
              f"-> {outdir/task}")
    print("Done. Έτοιμα για TRL SFTTrainer (apply_chat_template).")


if __name__ == "__main__":
    main()

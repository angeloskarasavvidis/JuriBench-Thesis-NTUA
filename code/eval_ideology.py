#!/usr/bin/env python3
"""
eval_ideology.py — Στάδιο 4 (ιδεολογική πιστότητα, E2)
------------------------------------------------------
Ερώτημα: κρατάει το ΠΑΡΑΓΟΜΕΝΟ opinion το ιδεολογικό «lean» του πραγματικού
συγγραφέα δικαστή; Ένας classifier-LLM διαβάζει το παραγόμενο κείμενο (χωρίς να
ξέρει τον δικαστή) και το ταξινομεί Liberal/Conservative/Moderate. Το συγκρίνουμε
με το gold `ideology` (από enrich_ideology, μόνο όπου υπάρχει).

Μετρικές: accuracy + macro-F1 (3 τάξεις) και 2-way (Liberal vs Conservative).
Έξοδος: results/ideology/<preds-stem>.json  + cache ανά υπόθεση.

Usage:
  python code/eval_ideology.py --preds preds/llama31_gen.jsonl
  python code/eval_ideology.py --preds preds/llama31_gen.jsonl --max-samples 40
"""
import argparse, json
from collections import Counter
from pathlib import Path

from llm_client import chat_json

LABELS = ["Liberal", "Conservative", "Moderate"]

SYSTEM = ("You are a political-science annotator of U.S. judicial opinions. "
          "Judge the ideological lean of the OPINION's reasoning. Respond STRICT JSON.")

TEMPLATE = """Classify the ideological lean of the following court opinion's reasoning as
exactly one of: Liberal, Conservative, Moderate.

Return JSON: {{"ideology":"Liberal|Conservative|Moderate","confidence":0-1}}

OPINION:
\"\"\"
{gen}
\"\"\"
"""


def norm(label):
    if not label:
        return None
    s = str(label).strip().lower()
    for L in LABELS:
        if L.lower() in s:
            return L
    return None


def macro_f1(gold, pred, labels):
    f1s = []
    for lab in labels:
        tp = sum(1 for g, p in zip(gold, pred) if g == lab and p == lab)
        fp = sum(1 for g, p in zip(gold, pred) if g != lab and p == lab)
        fn = sum(1 for g, p in zip(gold, pred) if g == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-samples", type=int, default=0)
    args = ap.parse_args()

    recs = [json.loads(l) for l in open(args.preds, encoding="utf-8") if l.strip()]
    # μόνο γραμμές με gold ideology (Liberal/Conservative/Moderate)
    recs = [r for r in recs if (r.get("ideology") or "").strip() in LABELS]
    if args.max_samples:
        recs = recs[: args.max_samples]
    print(f"Γραμμές με gold ideology: {len(recs)}")

    stem = Path(args.preds).stem
    out = Path(args.out) if args.out else Path("results/ideology") / f"{stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_path = out.with_suffix(".cache.jsonl")
    done = {}
    if cache_path.exists():
        for l in open(cache_path, encoding="utf-8"):
            if l.strip():
                c = json.loads(l); done[str(c["id"])] = c
    cache_f = open(cache_path, "a", encoding="utf-8")

    gold, pred = [], []
    for i, r in enumerate(recs, 1):
        rid = str(r["id"])
        g = r["ideology"]
        if rid in done:
            p = done[rid]["pred"]
        else:
            res = chat_json([{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": TEMPLATE.format(gen=(r.get("generated_text","") or "")[:6000])}])
            p = norm(res.get("ideology"))
            cache_f.write(json.dumps({"id": rid, "gold": g, "pred": p}, ensure_ascii=False) + "\n"); cache_f.flush()
        if p:
            gold.append(g); pred.append(p)
        if i % 10 == 0:
            print(f"  classified {i}/{len(recs)}")
    cache_f.close()

    n = len(gold)
    acc = sum(1 for g, p in zip(gold, pred) if g == p) / n if n else None
    # 2-way (Lib vs Cons)
    two = [(g, p) for g, p in zip(gold, pred) if g in ("Liberal", "Conservative")]
    acc2 = (sum(1 for g, p in two if g == p) / len(two)) if two else None

    summary = {
        "preds": args.preds, "n_evaluated": n,
        "accuracy_3way": round(acc, 4) if acc is not None else None,
        "macro_f1_3way": round(macro_f1(gold, pred, LABELS), 4) if n else None,
        "accuracy_2way_libcons": round(acc2, 4) if acc2 is not None else None,
        "gold_dist": dict(Counter(gold)), "pred_dist": dict(Counter(pred)),
    }
    json.dump(summary, open(out, "w"), indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n✓ ideology results -> {out}")


if __name__ == "__main__":
    main()

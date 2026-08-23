#!/usr/bin/env python3
"""
eval_judge.py — Στάδιο 4 (LLM-as-judge για ποιότητα λόγου)
----------------------------------------------------------
Βαθμολογεί τα ΠΑΡΑΓΟΜΕΝΑ opinions (από generate.py, task=generation) με έναν
κριτή-LLM, σε ρουμπρίκα 1–5 ανά άξονα:

  coherence               επιχειρηματολογική συνοχή / λογική ροή
  terminology             ορολογική ακρίβεια (σωστή νομική γλώσσα)
  institutional_fit       θεσμική συνέπεια (μοιάζει με απόφαση αυτού του δικαστηρίου)
  faithfulness            πιστότητα στα facts/issue, χωρίς επινοημένα γεγονότα/παραπομπές

Ενώνει με το test split (μέσω id) για να δώσει στον κριτή facts + issue_text.
Χρησιμοποιεί OpenAI-compatible API (LLM_* στο .env) μέσω llm_client.

Έξοδος: results/judge/<preds-stem>.json  (μέσοι όροι ανά άξονα) + cache ανά υπόθεση.

Usage:
  python code/eval_judge.py --preds preds/llama31_gen.jsonl
  python code/eval_judge.py --preds preds/llama31_gen.jsonl --max-samples 30
"""
import argparse, json
from pathlib import Path
from statistics import mean

from llm_client import chat_json

AXES = ["coherence", "terminology", "institutional_fit", "faithfulness"]

SYSTEM = (
    "You are a strict legal writing evaluator. You grade a machine-generated U.S. court "
    "opinion against the case's question and facts. Grade ONLY on what is shown. "
    "Respond with STRICT JSON."
)

TEMPLATE = """Score the GENERATED opinion on a 1-5 integer scale for each axis (5 = best):
- coherence: is the legal argument logically structured and internally consistent?
- terminology: is the legal terminology accurate and appropriate?
- institutional_fit: does it read like a real opinion of court "{court}"?
- faithfulness: does it stay faithful to the facts/question WITHOUT inventing facts or citations?

Return JSON: {{"coherence":int,"terminology":int,"institutional_fit":int,"faithfulness":int,"comment":str}}

QUESTION PRESENTED:
{issue}

FACTS:
{facts}

GENERATED OPINION:
\"\"\"
{gen}
\"\"\"
"""


def load_inputs(split):
    """id -> (issue_text, facts) από το splits, για να τα δει ο κριτής."""
    p = Path("data/splits") / f"{split}.jsonl"
    out = {}
    if p.exists():
        for l in open(p, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                out[str(r["id"])] = (r["input"].get("issue_text", ""), r["input"].get("facts", ""))
    return out


def clamp(v):
    try:
        return max(1, min(5, int(round(float(v)))))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-samples", type=int, default=0)
    args = ap.parse_args()

    recs = [json.loads(l) for l in open(args.preds, encoding="utf-8") if l.strip()]
    if args.max_samples:
        recs = recs[: args.max_samples]
    inputs = load_inputs(args.split)

    stem = Path(args.preds).stem
    out = Path(args.out) if args.out else Path("results/judge") / f"{stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_path = out.with_suffix(".cache.jsonl")
    done = {}
    if cache_path.exists():
        for l in open(cache_path, encoding="utf-8"):
            if l.strip():
                c = json.loads(l); done[str(c["id"])] = c

    scored = []
    cache_f = open(cache_path, "a", encoding="utf-8")
    for i, r in enumerate(recs, 1):
        rid = str(r["id"])
        if rid in done:
            scored.append(done[rid]); continue
        issue, facts = inputs.get(rid, ("", ""))
        prompt = TEMPLATE.format(court=r.get("jurisdiction", ""), issue=issue[:2000],
                                 facts=facts[:2000], gen=(r.get("generated_text", "") or "")[:6000])
        res = chat_json([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt}])
        row = {"id": rid, "jurisdiction": r.get("jurisdiction", "")}
        for ax in AXES:
            row[ax] = clamp(res.get(ax))
        scored.append(row)
        cache_f.write(json.dumps(row, ensure_ascii=False) + "\n"); cache_f.flush()
        if i % 10 == 0:
            print(f"  judged {i}/{len(recs)}")
    cache_f.close()

    summary = {"preds": args.preds, "n": len(scored), "task": "generation-judge"}
    for ax in AXES:
        vals = [s[ax] for s in scored if s.get(ax) is not None]
        summary[ax] = round(mean(vals), 3) if vals else None
    overall = [summary[ax] for ax in AXES if summary[ax] is not None]
    summary["overall"] = round(mean(overall), 3) if overall else None

    json.dump(summary, open(out, "w"), indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n✓ judge results -> {out}")


if __name__ == "__main__":
    main()

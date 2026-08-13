#!/usr/bin/env python3
"""
evaluate.py  — Στάδιο 4
-----------------------
Μετρικές πάνω στις προβλέψεις του generate.py.

Core (χωρίς GPU, ελαφριές εξαρτήσεις):
  • Ορθότητα έκβασης: accuracy + macro-F1 (disposition), ανά court breakdown
  • Ποιότητα λόγου (generation): μήκος, μέσο μήκος πρότασης, TTR, Flesch-Kincaid,
    παραγόμενο vs αυθεντικό (join με data/splits/<split>.jsonl μέσω id)

Optional (flags):
  --bertscore   BERTScore παραγόμενο vs αυθεντικό   (pip install bert-score)
  --citations   citation-hallucination rate μέσω CourtListener citation-lookup API
                (θέλει CL_API_TOKEN στο περιβάλλον/env + δίκτυο)

Usage:
  python code/evaluate.py --preds preds/smoke.jsonl --task predict
  python code/evaluate.py --preds preds/llama31_gen.jsonl --task generation --bertscore
"""
import argparse, json, re, os
from collections import Counter, defaultdict
from pathlib import Path

DISPOSITIONS = ["affirmed", "reversed", "vacated", "remanded", "affirmed_in_part",
                "dismissed", "denied", "granted", "mixed", "other", "unclear"]


# ---------- outcome ----------
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


def outcome_metrics(recs):
    gold = [r["gold_disposition"] for r in recs]
    pred = [r["pred_disposition"] for r in recs]
    labels = sorted(set(gold) | set(pred))
    acc = sum(1 for g, p in zip(gold, pred) if g == p) / len(recs)
    out = {"n": len(recs), "accuracy": round(acc, 4),
           "macro_f1": round(macro_f1(gold, pred, labels), 4)}
    by = defaultdict(lambda: [0, 0])
    for r in recs:
        by[r["jurisdiction"]][1] += 1
        by[r["jurisdiction"]][0] += (r["gold_disposition"] == r["pred_disposition"])
    out["accuracy_by_court"] = {k: round(c/n, 4) for k, (c, n) in by.items()}
    return out


# ---------- text stats ----------
def syllables(w):
    w = re.sub(r"[^a-z]", "", w.lower())
    return max(1, len(re.findall(r"[aeiouy]+", w))) if w else 0


def text_stats(text):
    words = re.findall(r"[A-Za-z']+", text)
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    nw, ns = len(words), max(1, len(sents))
    if nw == 0:
        return {"words": 0}
    syl = sum(syllables(w) for w in words)
    fk = 0.39 * (nw / ns) + 11.8 * (syl / nw) - 15.59   # Flesch-Kincaid grade
    ttr = len(set(w.lower() for w in words)) / nw
    return {"words": nw, "avg_sent_len": round(nw / ns, 2),
            "ttr": round(ttr, 4), "flesch_kincaid": round(fk, 2)}


def avg(dicts, key):
    vs = [d[key] for d in dicts if key in d]
    return round(sum(vs) / len(vs), 3) if vs else None


def load_authentic(task, split):
    p = Path("data/splits") / f"{split}.jsonl"
    if not p.exists():
        return {}
    out = {}
    for l in open(p, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            out[str(r["id"])] = r["targets"].get("opinion_text", "")
    return out


# ---------- citations (optional) ----------
def citation_hallucination(recs, token):
    import urllib.request
    url = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
    total = bad = 0
    for r in recs:
        txt = r.get("generated_text", "")
        if not txt.strip():
            continue
        data = ("text=" + urllib.parse.quote(txt[:50000])).encode()
        req = urllib.request.Request(url, data=data,
              headers={"Authorization": f"Token {token}",
                       "Content-Type": "application/x-www-form-urlencoded"})
        try:
            res = json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            print("  citation API error:", e); continue
        for c in res:
            total += 1
            # status 200 + clusters => βρέθηκε· αλλιώς αγνώστου/λάθος
            if c.get("status") != 200 or not c.get("clusters"):
                bad += 1
    return {"citations_found": total, "hallucinated": bad,
            "hallucination_rate": round(bad/total, 4) if total else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--task", choices=["generation", "predict"], required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--bertscore", action="store_true")
    ap.add_argument("--citations", action="store_true")
    args = ap.parse_args()

    recs = [json.loads(l) for l in open(args.preds, encoding="utf-8") if l.strip()]
    results = {"preds": args.preds, "task": args.task, "n": len(recs)}

    results["outcome"] = outcome_metrics(recs)

    if args.task == "generation":
        authentic = load_authentic(args.task, args.split)
        gen_stats = [text_stats(r.get("generated_text", "")) for r in recs]
        auth_stats = [text_stats(authentic.get(str(r["id"]), "")) for r in recs
                      if str(r["id"]) in authentic]
        results["discourse"] = {
            "generated": {k: avg(gen_stats, k) for k in ("words", "avg_sent_len", "ttr", "flesch_kincaid")},
            "authentic": {k: avg(auth_stats, k) for k in ("words", "avg_sent_len", "ttr", "flesch_kincaid")},
        }
        if args.bertscore:
            from bert_score import score
            ids = [str(r["id"]) for r in recs if str(r["id"]) in authentic]
            cand = [r["generated_text"] for r in recs if str(r["id"]) in authentic]
            ref = [authentic[i] for i in ids]
            P, R, F = score(cand, ref, lang="en", rescale_with_baseline=True)
            results["bertscore_f1"] = round(float(F.mean()), 4)

    if args.citations:
        token = os.environ.get("CL_API_TOKEN", "")
        if not token:
            print("  (skip citations: no CL_API_TOKEN)")
        else:
            results["citation_hallucination"] = citation_hallucination(recs, token)

    out = args.out or f"results/{Path(args.preds).stem}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(out, "w"), indent=2, ensure_ascii=False)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n✓ results -> {out}")


if __name__ == "__main__":
    main()

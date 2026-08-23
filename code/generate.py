#!/usr/bin/env python3
"""
generate.py  — Στάδιο 3 (Colab, GPU)
------------------------------------
Inference στο test split με ένα (fine-tuned) μοντέλο. Παίρνει τα messages, κόβει το
assistant, παράγει, και σώζει προβλέψεις ευθυγραμμισμένες με το gold (μέσω id).

SMOKE:
  python code/generate.py --model Qwen/Qwen2.5-1.5B-Instruct --adapter adapters/smoke \
      --task predict --max-samples 16 --out preds/smoke.jsonl

FULL:
  python code/generate.py --model meta-llama/Meta-Llama-3.1-8B-Instruct \
      --adapter adapters/llama31_gen --task generation --out preds/llama31_gen.jsonl
"""
import argparse, json, re
from pathlib import Path

DISPOSITIONS = ["affirmed_in_part", "affirmed", "reversed", "vacated", "remanded",
                "dismissed", "denied", "granted", "mixed", "other", "unclear"]


def parse_disposition(text):
    t = text.lower()
    m = re.search(r"disposition\s*[:\-]\s*([a-z_]+)", t)
    cand = m.group(1) if m else t
    for d in DISPOSITIONS:            # affirmed_in_part πριν το affirmed (σειρά λίστας)
        if d in cand:
            return d
    return "unclear"


def merge_system(msgs):
    sys_txt = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
    out = []
    for m in msgs:
        if m["role"] == "system":
            continue
        if m["role"] == "user" and sys_txt and not any(o["role"] == "user" for o in out):
            out.append({"role": "user", "content": sys_txt + "\n\n" + m["content"]})
        else:
            out.append(m)
    return out


def encode_prompt(tok, msgs):
    msgs = [m for m in msgs if m["role"] != "assistant"]
    try:
        return tok.apply_chat_template(msgs, add_generation_prompt=True,
                                       return_tensors="pt", return_dict=True)
    except Exception:
        return tok.apply_chat_template(merge_system(msgs), add_generation_prompt=True,
                                       return_tensors="pt", return_dict=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", default=None, help="PEFT adapter dir (προαιρετικό: base-only)")
    ap.add_argument("--task", choices=["generation", "predict"], default="predict")
    ap.add_argument("--data-dir", default="data/finetune")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=None)
    ap.add_argument("--max-samples", type=int, default=0)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    max_new = args.max_new_tokens or (16 if args.task == "predict" else 1200)
    src = Path(args.data_dir) / args.task / f"{args.split}.jsonl"
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    if args.max_samples:
        rows = rows[: args.max_samples]

    tok = AutoTokenizer.from_pretrained(args.adapter or args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16)
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            enc = encode_prompt(tok, r["messages"])
            enc = {k: v.to(model.device) for k, v in enc.items()}
            plen = enc["input_ids"].shape[1]
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                                     pad_token_id=tok.pad_token_id)
            gen = tok.decode(out[0][plen:], skip_special_tokens=True).strip()
            meta = r["meta"]
            rec = {
                "id": meta["id"], "jurisdiction": meta["jurisdiction"],
                "gold_disposition": meta["disposition"],
                "pred_disposition": parse_disposition(gen),
                "gold_prevailing_party": meta.get("prevailing_party", ""),
                "ideology": meta.get("ideology", ""),
                "generated_text": gen,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 20 == 0:
                print(f"  {i}/{len(rows)}")
    print(f"✓ preds saved -> {args.out}")


if __name__ == "__main__":
    main()

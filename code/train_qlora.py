#!/usr/bin/env python3
"""
train_qlora.py  — Στάδιο 2 (Colab, GPU)
---------------------------------------
QLoRA (4-bit) supervised fine-tuning ενός chat μοντέλου πάνω στα messages-JSONL
που παράγει το build_finetune.py. Ίδιο script για smoke (tiny μοντέλο, λίγα steps)
και για τα πραγματικά μοντέλα.

Ανθεκτικό σε διαφορετικές εκδόσεις TRL (τα ονόματα params άλλαξαν μεταξύ εκδόσεων:
max_seq_length↔max_length, eval_strategy↔evaluation_strategy, tokenizer↔processing_class).

SMOKE:
  python code/train_qlora.py --model Qwen/Qwen2.5-1.5B-Instruct --task predict \
      --max-train 64 --max-eval 16 --max-steps 10 --out adapters/smoke

FULL:
  python code/train_qlora.py --model meta-llama/Meta-Llama-3.1-8B-Instruct \
      --task generation --epochs 2 --max-seq-len 4096 --out adapters/llama31_gen

Απαιτεί: torch transformers trl peft bitsandbytes accelerate datasets
"""
import argparse, inspect, json
from pathlib import Path


def load_messages(path, limit=0):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return rows[:limit] if limit else rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF model id")
    ap.add_argument("--task", choices=["generation", "predict"], default="predict")
    ap.add_argument("--data-dir", default="data/finetune")
    ap.add_argument("--out", required=True, help="output dir για το adapter")
    ap.add_argument("--max-seq-len", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--max-train", type=int, default=0)
    ap.add_argument("--max-eval", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=-1)
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, prepare_model_for_kbit_training
    from trl import SFTTrainer, SFTConfig

    if not torch.cuda.is_available():
        raise SystemExit(
            "Δεν βρέθηκε GPU. Στο Colab: Runtime → Change runtime type → GPU (T4/L4/A100), "
            "και ξανατρέξε. (QLoRA χρειάζεται CUDA.)")
    # T4 (Turing) δεν υποστηρίζει bf16· A100/L4 (Ampere+) υποστηρίζουν.
    use_bf16 = torch.cuda.is_bf16_supported()
    compute_dtype = torch.bfloat16 if use_bf16 else torch.float16
    print(f"GPU: {torch.cuda.get_device_name(0)} | bf16={use_bf16} (αλλιώς fp16)")

    data_dir = Path(args.data_dir) / args.task
    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def _merge_system(msgs):
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

    def _render_one(msgs):
        try:
            return tok.apply_chat_template(msgs, tokenize=False)
        except Exception:
            return tok.apply_chat_template(_merge_system(msgs), tokenize=False)

    def render(rows):
        texts = [_render_one(r["messages"]) for r in rows]
        return Dataset.from_dict({"text": texts})

    train_ds = render(load_messages(data_dir / "train.jsonl", args.max_train))
    eval_ds  = render(load_messages(data_dir / "val.jsonl",   args.max_eval))
    print(f"train {len(train_ds)} · val {len(eval_ds)} · task={args.task} · model={args.model}")

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=compute_dtype)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map="auto")
    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    peft_cfg = LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
                          bias="none", task_type="CAUSAL_LM", target_modules="all-linear")

    # ── SFTConfig ανθεκτικό στις εκδόσεις: κράτα μόνο τα υποστηριζόμενα ονόματα ──
    sig = set(inspect.signature(SFTConfig.__init__).parameters)
    desired = dict(
        output_dir=args.out, num_train_epochs=args.epochs, max_steps=args.max_steps,
        per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, warmup_ratio=0.03, lr_scheduler_type="cosine",
        logging_steps=5, save_strategy="epoch", bf16=use_bf16, fp16=not use_bf16, packing=False,
        dataset_text_field="text", report_to="none",
    )
    # seq length: max_seq_length (παλιό) ή max_length (νέο)
    if "max_seq_length" in sig: desired["max_seq_length"] = args.max_seq_len
    elif "max_length" in sig:   desired["max_length"] = args.max_seq_len
    # eval strategy: eval_strategy (νέο) ή evaluation_strategy (παλιό)
    if "eval_strategy" in sig:        desired["eval_strategy"] = "epoch"
    elif "evaluation_strategy" in sig: desired["evaluation_strategy"] = "epoch"
    cfg = SFTConfig(**{k: v for k, v in desired.items() if k in sig})

    # ── SFTTrainer: processing_class (νέο) ή tokenizer (παλιό) ──
    tsig = set(inspect.signature(SFTTrainer.__init__).parameters)
    tkw = dict(model=model, args=cfg, train_dataset=train_ds,
               eval_dataset=eval_ds, peft_config=peft_cfg)
    if "processing_class" in tsig: tkw["processing_class"] = tok
    elif "tokenizer" in tsig:      tkw["tokenizer"] = tok
    trainer = SFTTrainer(**tkw)

    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    with open(Path(args.out) / "run_config.json", "w") as f:
        json.dump(vars(args), f, indent=2)
    print(f"✓ adapter saved -> {args.out}")


if __name__ == "__main__":
    main()

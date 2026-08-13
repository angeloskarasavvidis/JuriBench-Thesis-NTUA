# RUN — Πλήρεις οδηγίες εκτέλεσης (smoke → full)

Φιλοσοφία: πρώτα **smoke test** (μικρό μοντέλο + λίγα δείγματα) για να δεις ότι όλα τρέχουν
end-to-end χωρίς σφάλματα· μετά τα κανονικά μοντέλα. Όλες οι εντολές τρέχουν από τη ρίζα `JuriBench/`.

---

## A. Τοπικά (Mac) — 1 φορά, χωρίς GPU

Το data pipeline έχει ήδη τρέξει. Αν αλλάξουν τα δεδομένα, ξαναφτιάξε τα finetune αρχεία:

```bash
python3 code/build_finetune.py --max-target-chars 8000
```

Παράγει `data/finetune/{generation,predict}/{train,val,test}.jsonl`. Αυτά ανεβαίνουν στο Colab.

---

## B. Google Colab — setup (κάθε session)

1. Colab → **Runtime → Change runtime type → GPU** (T4 free, ή L4/A100 με Pro).
2. Φέρε το `JuriBench/` μέσα στο Colab. Δύο τρόποι:

   **(i) Google Drive** (απλό): ανέβασε τον φάκελο `JuriBench` στο Drive σου, μετά:
   ```python
   from google.colab import drive; drive.mount('/content/drive')
   %cd /content/drive/MyDrive/JuriBench
   ```

   **(ii) Git** (αν το έχεις σε repo): `!git clone <repo> && %cd JuriBench`

3. Εξαρτήσεις:
   ```python
   !pip install -q -r requirements-train.txt
   ```

4. (Μόνο για Llama, που είναι gated) Hugging Face login + αποδοχή license στη σελίδα του μοντέλου:
   ```python
   from huggingface_hub import login; login()   # βάλε HF token
   ```

---

## C. SMOKE TEST (τρέχει σε λεπτά, ακόμη και σε free T4)

Σκοπός: επιβεβαίωση ότι φορτώνει → εκπαιδεύεται → σώζει → παράγει → αξιολογεί.

```python
# 1) train tiny model, predict task, λίγα δείγματα/steps
!python code/train_qlora.py --model Qwen/Qwen2.5-1.5B-Instruct --task predict \
    --max-train 64 --max-eval 16 --max-steps 10 --out adapters/smoke

# 2) generate σε 16 test δείγματα
!python code/generate.py --model Qwen/Qwen2.5-1.5B-Instruct --adapter adapters/smoke \
    --task predict --max-samples 16 --out preds/smoke.jsonl

# 3) evaluate (outcome μετρικές)
!python code/evaluate.py --preds preds/smoke.jsonl --task predict
```

Αν δεις accuracy/macro_f1 να τυπώνονται χωρίς σφάλμα → **το pipeline δουλεύει**. (Τα νούμερα δεν
έχουν σημασία εδώ — είναι tiny μοντέλο/λίγα steps.)

Προαιρετικά smoke και για generation:
```python
!python code/train_qlora.py --model Qwen/Qwen2.5-1.5B-Instruct --task generation \
    --max-train 64 --max-eval 16 --max-steps 10 --max-seq-len 2048 --out adapters/smoke_gen
!python code/generate.py --model Qwen/Qwen2.5-1.5B-Instruct --adapter adapters/smoke_gen \
    --task generation --max-samples 8 --out preds/smoke_gen.jsonl
!python code/evaluate.py --preds preds/smoke_gen.jsonl --task generation
```

---

## D. FULL RUN (τα 3 μοντέλα)

Για κάθε μοντέλο, 2 tasks (generation + predict). Παράδειγμα με ένα μοντέλο:

```python
M="meta-llama/Meta-Llama-3.1-8B-Instruct"; TAG="llama31"
# generation
!python code/train_qlora.py --model $M --task generation --epochs 2 --max-seq-len 4096 \
    --out adapters/{TAG}_gen
!python code/generate.py --model $M --adapter adapters/{TAG}_gen --task generation \
    --out preds/{TAG}_gen.jsonl
!python code/evaluate.py --preds preds/{TAG}_gen.jsonl --task generation --bertscore --citations
# predict (LJP)
!python code/train_qlora.py --model $M --task predict --epochs 3 --out adapters/{TAG}_pred
!python code/generate.py --model $M --adapter adapters/{TAG}_pred --task predict \
    --out preds/{TAG}_pred.jsonl
!python code/evaluate.py --preds preds/{TAG}_pred.jsonl --task predict
```

Επανάλαβε με:
- `Qwen/Qwen3-8B` (TAG=qwen3)
- `Equall/SaulLM-7B` (TAG=saul)   ← νομικό

Για το `--citations` χρειάζεται `CL_API_TOKEN` στο περιβάλλον:
```python
import os; os.environ["CL_API_TOKEN"]="<το token σου>"
```

---

## E. Πού βγαίνουν τα αποτελέσματα
- `adapters/<tag>_<task>/` — τα LoRA adapters (σώσε τα στο Drive!)
- `preds/<tag>_<task>.jsonl` — προβλέψεις + παραγόμενα κείμενα
- `results/<tag>_<task>.json` — μετρικές

Σύγκρινε τα `results/*.json` των 3 μοντέλων (outcome accuracy/F1, discourse, hallucination).

---

## F. Troubleshooting
- **OOM (CUDA out of memory):** μείωσε `--max-seq-len` (π.χ. 2048), κράτα `--batch 1`,
  αύξησε `--grad-accum`. Στο generation μείωσε `--max-new-tokens`.
- **Llama gated / 401:** κάνε login + αποδοχή license στη σελίδα του μοντέλου στο HF.
- **Colab αποσύνδεση:** σώζε adapters/preds στο Google Drive· τα scripts γράφουν σε φακέλους
  που μπορείς να βάλεις μέσα στο mounted Drive.
- **CourtListener 429:** το citation API έχει όριο· τρέξε το `--citations` σε υποσύνολο ή αργά.
- **SaulLM chat template:** αν λείπει, το `apply_chat_template` μπορεί να χρειαστεί fallback —
  πες μου να προσθέσω template handling αν σκάσει.
```

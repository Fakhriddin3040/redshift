"""LLM-2: LoRA fine-tuning of a chat model on the alert-explanation dataset.

This script is independent of the application: it does not import vigil, the
application never imports it, and its libraries live in their own requirements
file (ml/requirements-finetune.txt). Nothing here names a model: the base model,
the data and every training parameter come from outside.

Configuration: environment variables, optionally a JSON file (--config), and
command-line options. Later sources win: defaults < FT_* env < --config < options.

    FT_BASE_MODEL       base model: a Hugging Face id or a local directory   (required)
    FT_DATASET          training file, chat-format JSONL                     (required)
    FT_VALID_DATASET    validation file, same format                         (optional)
    FT_OUTPUT_DIR       where results go; a new directory per run            (required)
    FT_EXPORT           adapter | merged | both                              (adapter)
    FT_EPOCHS, FT_LEARNING_RATE, FT_BATCH_SIZE, FT_GRAD_ACCUM, FT_MAX_SEQ_LEN,
    FT_LORA_R, FT_LORA_ALPHA, FT_LORA_DROPOUT, FT_LOAD_4BIT, FT_SEED

    python ml/finetune_llm.py --dry-run          # show the resolved configuration, check the data
    python ml/finetune_llm.py                    # train

Result, in FT_OUTPUT_DIR:
    adapter/     the LoRA adapter + tokenizer (small; load on top of the base model)
    merged/      the base model with the adapter merged in (with FT_EXPORT=merged|both):
                 a plain model directory that any server for this model family can load
    run.json     configuration and training metrics of this run

Deployment is a separate step and uses no code from here: serve `merged/` (or the
base model + `adapter/`) with any OpenAI-compatible server, then point the
application at it with LLM_BASE_URL and LLM_MODEL.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    base_model: str = ""
    dataset: str = ""
    valid_dataset: str = ""
    output_dir: str = ""
    export: str = "adapter"
    epochs: float = 3.0
    learning_rate: float = 2e-4
    batch_size: int = 4
    grad_accum: int = 4
    max_seq_len: int = 768
    lora_r: int = 16
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    load_4bit: bool = False
    seed: int = 2026


def _cast(name: str, raw: object) -> object:
    kind = type(getattr(Config(), name))
    if kind is bool:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return kind(raw)


def resolve(argv: list[str]) -> tuple[Config, bool]:
    ap = argparse.ArgumentParser(
        description="LoRA fine-tuning; configured from outside (FT_* env, --config, options)."
    )
    ap.add_argument("--config", help="JSON file with any of the settings")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the configuration and check the data; do not train")  # fmt: skip
    for f in fields(Config):
        ap.add_argument(f"--{f.name.replace('_', '-')}", dest=f.name, default=None)
    args = ap.parse_args(argv)

    values: dict[str, object] = {}
    for f in fields(Config):
        env = os.environ.get(f"FT_{f.name.upper()}")
        if env not in (None, ""):
            values[f.name] = env
    if args.config:
        values |= json.loads(Path(args.config).read_text())
    for f in fields(Config):
        if getattr(args, f.name) is not None:
            values[f.name] = getattr(args, f.name)
    unknown = set(values) - {f.name for f in fields(Config)}
    if unknown:
        raise SystemExit(f"unknown settings: {sorted(unknown)}")
    cfg = Config(**{k: _cast(k, v) for k, v in values.items()})

    missing = [
        f"FT_{n.upper()}"
        for n in ("base_model", "dataset", "output_dir")
        if not getattr(cfg, n)
    ]
    if missing:
        raise SystemExit(f"not set: {', '.join(missing)} (see the top of this file)")
    if cfg.export not in ("adapter", "merged", "both"):
        raise SystemExit("FT_EXPORT must be adapter, merged or both")
    return cfg, args.dry_run


def read_chats(path: str) -> list[list[dict]]:
    """Chat-format JSONL: {"messages": [{"role", "content"}, ...]} per line; the last
    message must be the assistant's answer."""
    chats = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        messages = json.loads(line).get("messages")
        if not messages or messages[-1].get("role") != "assistant":
            raise SystemExit(
                f"{path}:{n}: expected 'messages' ending with an assistant message"
            )
        chats.append([{"role": m["role"], "content": m["content"]} for m in messages])
    if not chats:
        raise SystemExit(f"{path}: no examples")
    return chats


def train(cfg: Config) -> dict:
    # Imported here, so --dry-run and --help work without the training libraries.
    import torch
    from datasets import Dataset
    from peft import (
        LoraConfig,
        PeftModel,
        get_peft_model,
        prepare_model_for_kbit_training,
    )
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(cfg.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def encode(chat: list[dict]) -> dict:
        # The loss is computed on the assistant's answer only.
        prompt = tokenizer.apply_chat_template(
            chat[:-1], tokenize=False, add_generation_prompt=True
        )
        full = tokenizer.apply_chat_template(chat, tokenize=False)
        ids = tokenizer(
            full, add_special_tokens=False, truncation=True, max_length=cfg.max_seq_len
        )["input_ids"]
        n_prompt = min(
            len(tokenizer(prompt, add_special_tokens=False)["input_ids"]), len(ids)
        )
        return {"input_ids": ids, "attention_mask": [1] * len(ids),
                "labels": [-100] * n_prompt + ids[n_prompt:]}  # fmt: skip

    def dataset(path: str) -> Dataset:
        return Dataset.from_list([encode(c) for c in read_chats(path)])

    train_ds = dataset(cfg.dataset)
    valid_ds = dataset(cfg.valid_dataset) if cfg.valid_dataset else None

    load_kwargs: dict = {
        "torch_dtype": torch.bfloat16 if torch.cuda.is_available() else torch.float32
    }
    if cfg.load_4bit:
        from transformers import BitsAndBytesConfig

        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )  # fmt: skip
    if torch.cuda.is_available():
        load_kwargs["device_map"] = "auto"
    model = AutoModelForCausalLM.from_pretrained(cfg.base_model, **load_kwargs)
    if cfg.load_4bit:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout,
                   target_modules="all-linear", task_type="CAUSAL_LM"),
    )  # fmt: skip
    model.print_trainable_parameters()

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(out / "checkpoints"),
            num_train_epochs=cfg.epochs,
            learning_rate=cfg.learning_rate,
            per_device_train_batch_size=cfg.batch_size,
            per_device_eval_batch_size=cfg.batch_size,
            gradient_accumulation_steps=cfg.grad_accum,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            logging_steps=10,
            eval_strategy="epoch" if valid_ds is not None else "no",
            save_strategy="no",
            seed=cfg.seed,
            report_to=[],
        ),
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        data_collator=DataCollatorForSeq2Seq(
            tokenizer, padding=True, label_pad_token_id=-100
        ),
    )
    started = time.time()
    result = trainer.train()
    metrics = {"train_loss": result.training_loss, "train_seconds": round(time.time() - started),
               "train_examples": len(train_ds)}  # fmt: skip
    if valid_ds is not None:
        metrics |= {
            "valid_loss": trainer.evaluate()["eval_loss"],
            "valid_examples": len(valid_ds),
        }

    exported = {}
    if cfg.export in ("adapter", "both"):
        model.save_pretrained(out / "adapter")
        tokenizer.save_pretrained(out / "adapter")
        exported["adapter"] = str(out / "adapter")
    if cfg.export in ("merged", "both"):
        if cfg.load_4bit:
            # A 4-bit model cannot be merged: reload the base in full precision.
            model.save_pretrained(out / "adapter")
            base = AutoModelForCausalLM.from_pretrained(
                cfg.base_model, torch_dtype=torch.float16
            )
            model = PeftModel.from_pretrained(base, out / "adapter")
        merged = model.merge_and_unload()
        merged.save_pretrained(out / "merged")
        tokenizer.save_pretrained(out / "merged")
        exported["merged"] = str(out / "merged")
    return {"metrics": metrics, "exported": exported}


def main(argv: list[str]) -> int:
    cfg, dry_run = resolve(argv)
    print("configuration:")
    for key, value in asdict(cfg).items():
        print(f"  {key:<14} {value}")
    n_train = len(read_chats(cfg.dataset))
    n_valid = len(read_chats(cfg.valid_dataset)) if cfg.valid_dataset else 0
    print(f"data: {n_train} training examples, {n_valid} validation examples")
    if dry_run:
        print("dry run: nothing was trained")
        return 0

    out = Path(cfg.output_dir)
    if (out / "run.json").exists():
        raise SystemExit(
            f"{out} already holds a finished run; choose a new FT_OUTPUT_DIR"
        )
    result = train(cfg)
    (out / "run.json").write_text(
        json.dumps({"config": asdict(cfg), **result}, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))
    print(f"\nDone. Results are in {out}/. To use the model: serve it with any "
          "OpenAI-compatible server and set LLM_BASE_URL and LLM_MODEL for the application.")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

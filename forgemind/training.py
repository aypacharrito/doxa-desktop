from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forgemind.config import app_data_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class TrainingLab:
    """Build reviewed training assets without silently changing model weights."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else app_data_dir() / "training"
        self.examples_path = self.root / "reviewed_examples.jsonl"
        self.exports_dir = self.root / "exports"
        self.plans_dir = self.root / "plans"
        self.adapters_path = self.root / "adapters.json"
        self.root.mkdir(parents=True, exist_ok=True)

    def load_examples(self) -> list[dict[str, Any]]:
        if not self.examples_path.exists():
            return []
        examples: list[dict[str, Any]] = []
        for line in self.examples_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                examples.append(item)
        return examples

    def add_reviewed_example(
        self,
        instruction: str,
        ideal_response: str,
        source: str = "owner-reviewed",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        instruction = instruction.strip()
        ideal_response = ideal_response.strip()
        if not instruction or not ideal_response:
            raise ValueError("Both an instruction and an ideal answer are required.")
        digest = hashlib.sha256(
            (instruction + "\0" + ideal_response).encode("utf-8")
        ).hexdigest()[:16]
        if any(item.get("id") == digest for item in self.load_examples()):
            raise ValueError("That reviewed example is already in the training set.")
        item = {
            "id": digest,
            "instruction": instruction,
            "ideal_response": ideal_response,
            "source": source,
            "tags": sorted(set(tags or [])),
            "reviewed": True,
            "created_at": _now(),
        }
        self.examples_path.parent.mkdir(parents=True, exist_ok=True)
        with self.examples_path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def validate_dataset(self, minimum_examples: int = 20) -> dict[str, Any]:
        examples = self.load_examples()
        errors: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        valid = 0
        for index, item in enumerate(examples, start=1):
            instruction = item.get("instruction")
            response = item.get("ideal_response")
            if not isinstance(instruction, str) or not instruction.strip():
                errors.append(f"Example {index} has no instruction.")
                continue
            if not isinstance(response, str) or not response.strip():
                errors.append(f"Example {index} has no ideal answer.")
                continue
            key = hashlib.sha256((instruction.strip() + "\0" + response.strip()).encode("utf-8")).hexdigest()
            if key in seen:
                warnings.append(f"Example {index} duplicates an earlier example.")
                continue
            seen.add(key)
            valid += 1
        if valid < minimum_examples:
            warnings.append(
                f"Collect at least {minimum_examples} reviewed examples before a trial run; "
                "hundreds of diverse examples are better for a useful adapter."
            )
        return {
            "ready_for_trial": not errors and valid >= minimum_examples,
            "valid_examples": valid,
            "total_examples": len(examples),
            "errors": errors,
            "warnings": warnings,
        }

    def export_chat_jsonl(self, destination: Path | None = None) -> Path:
        destination = destination or (
            self.exports_dir / f"forgemind-reviewed-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        )
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            for item in self.load_examples():
                if not item.get("reviewed"):
                    continue
                record = {
                    "messages": [
                        {"role": "user", "content": item["instruction"]},
                        {"role": "assistant", "content": item["ideal_response"]},
                    ],
                    "metadata": {
                        "id": item.get("id"),
                        "source": item.get("source"),
                        "tags": item.get("tags", []),
                    },
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
        temporary.replace(destination)
        return destination

    def create_lora_plan(
        self,
        base_model_path: str,
        vram_mb: int = 8188,
        context_size: int = 2048,
        epochs: int = 2,
    ) -> Path:
        model_name = Path(base_model_path).name if base_model_path else "not-selected"
        plan = {
            "schema_version": 1,
            "created_at": _now(),
            "status": "plan_only_not_started",
            "goal": "Create a small reviewed LoRA/QLoRA adapter without replacing the base model.",
            "base_inference_model": model_name,
            "hardware": {"vram_mb": vram_mb},
            "recommended_recipe": {
                "method": "QLoRA",
                "maximum_practical_base_size": "7B-8B on approximately 8 GB VRAM",
                "weight_loading": "4-bit",
                "micro_batch_size": 1,
                "gradient_accumulation_steps": 16,
                "sequence_length": min(max(512, context_size), 2048),
                "epochs": min(max(1, epochs), 5),
                "gradient_checkpointing": True,
                "validation_split": 0.1,
            },
            "gates": [
                "Dataset passes validation and contains only owner-reviewed examples.",
                "A compatible original training checkpoint is selected.",
                "Baseline evaluations are recorded before training.",
                "Candidate adapter is activated only if evaluations do not regress.",
            ],
            "important_limit": (
                "The selected GGUF is optimized for inference. Most QLoRA trainers require the original "
                "Transformers/safetensors checkpoint and tokenizer; this plan does not train or download them."
            ),
            "dataset": str(self.examples_path),
        }
        destination = self.plans_dir / f"lora-plan-{datetime.now():%Y%m%d-%H%M%S}.json"
        _atomic_json(destination, plan)
        return destination

    def list_adapters(self) -> list[dict[str, Any]]:
        if not self.adapters_path.exists():
            return []
        try:
            value = json.loads(self.adapters_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def register_adapter(
        self,
        adapter_path: str,
        base_model: str,
        benchmark_score: float,
        status: str = "candidate",
    ) -> dict[str, Any]:
        if status not in {"candidate", "verified", "rejected", "active"}:
            raise ValueError("Unknown adapter status.")
        record = {
            "id": hashlib.sha256((adapter_path + "\0" + _now()).encode("utf-8")).hexdigest()[:16],
            "path": adapter_path,
            "base_model": base_model,
            "benchmark_score": float(benchmark_score),
            "status": status,
            "created_at": _now(),
        }
        adapters = self.list_adapters()
        adapters.append(record)
        _atomic_json(self.adapters_path, adapters)
        return record

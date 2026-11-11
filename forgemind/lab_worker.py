"""Trusted tiny-model training adapters. No model-generated Python is executed here."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from .research_lab import atomic_json, validate_spec


def split_corpus(data: bytes) -> tuple[bytes, bytes, bytes]:
    if len(data) < 4096:
        raise ValueError("Corpus needs at least 4 KB.")
    train_end, validation_end = int(len(data) * 0.8), int(len(data) * 0.9)
    return data[:train_end], data[train_end:validation_end], data[validation_end:]


def ngram_train(train: bytes, order: int, stopped=lambda: False) -> dict:
    counts = defaultdict(Counter)
    for index in range(order, len(train)):
        if index % 4096 == 0 and stopped():
            raise InterruptedError("Owner paused training.")
        counts[train[index-order:index].hex()][train[index]] += 1
    return {key: {str(token): count for token, count in values.items()} for key, values in counts.items()}


def ngram_score(counts: dict, data: bytes, order: int) -> float:
    loss = 0.0
    for index in range(order, len(data)):
        values = counts.get(data[index-order:index].hex(), {})
        total = sum(values.values())
        probability = (values.get(str(data[index]), 0) + 0.1) / (total + 25.6)
        loss -= math.log(probability)
    return loss / (len(data) - order)


def build_model(torch, spec: dict, sequence_length: int):
    nn = torch.nn
    class ByteModel(nn.Module):
        def __init__(self):
            super().__init__()
            width = spec["width"]
            self.embedding = nn.Embedding(256, width)
            if spec["family"] == "gru":
                self.core = nn.GRU(width, width, spec["layers"], batch_first=True)
            else:
                self.position = nn.Embedding(sequence_length, width)
                block = nn.TransformerEncoderLayer(width, spec["heads"], width * 4,
                    dropout=0.0, batch_first=True, norm_first=False)
                self.core = nn.TransformerEncoder(block, spec["layers"], enable_nested_tensor=False)
            self.output = nn.Linear(width, 256)

        def forward(self, tokens):
            embedded = self.embedding(tokens)
            if spec["family"] == "gru":
                hidden, _ = self.core(embedded)
            else:
                length = tokens.shape[1]
                embedded = embedded + self.position(torch.arange(length, device=tokens.device))
                mask = torch.triu(torch.ones(length, length, device=tokens.device, dtype=torch.bool), diagonal=1)
                hidden = self.core(embedded, mask=mask)
            return self.output(hidden)
    return ByteModel()


def batch(torch, data, sequence_length: int, batch_size: int, generator, device):
    offsets = torch.randint(len(data) - sequence_length, (batch_size,), generator=generator)
    inputs = torch.stack([data[offset:offset+sequence_length] for offset in offsets])
    targets = torch.stack([data[offset+1:offset+sequence_length+1] for offset in offsets])
    return inputs.to(device), targets.to(device)


def evaluate(torch, model, data: bytes, job: dict, device):
    # This split is never used in optimizer steps. Fixed windows enable comparable validation.
    tensor = torch.tensor(list(data), dtype=torch.long)
    generator = torch.Generator().manual_seed(7621)
    model.eval()
    values = []
    with torch.no_grad():
        for _ in range(12):
            inputs, targets = batch(torch, tensor, job["sequence_length"], job["batch_size"], generator, device)
            values.append(torch.nn.functional.cross_entropy(model(inputs).reshape(-1, 256), targets.reshape(-1)).item())
    return sum(values) / len(values)


def run_job(path: Path, *, audit: bool = False) -> dict:
    folder = path.parent
    job = json.loads(path.read_text(encoding="utf-8"))
    spec = validate_spec(job["spec"])
    data = Path(job["corpus"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != job["digest"]:
        raise ValueError("Dataset snapshot no longer matches its recorded hash.")
    train, validation, test = split_corpus(data)
    started = time.monotonic()
    stopped = lambda: (folder / "STOP").exists()
    atomic_json(folder / "progress.json", {"message": "Loading training adapter…"})
    if spec["family"] == "ngram":
        target = folder / "ngram.json"
        if audit:
            counts = json.loads(target.read_text(encoding="utf-8"))
            return {"test_nll": ngram_score(counts, test, spec["order"]), "protocol": job["protocol"]}
        counts = ngram_train(train, spec["order"], stopped)
        if stopped():
            raise InterruptedError("Owner paused training.")
        atomic_json(target, counts)
        return {"status": "completed", "validation_nll": ngram_score(counts, validation, spec["order"]),
            "parameters": sum(len(values) for values in counts.values()), "checkpoint": target.name,
            "elapsed_seconds": time.monotonic()-started, "device": "cpu (non-neural baseline)",
            "training_bytes": len(train), "protocol": job["protocol"], "steps": 1}

    # Separate process avoids competing CUDA DLL paths with llama.cpp in the desktop app.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch training runtime missing. Run INSTALL_RESEARCH_GPU.bat first.") from exc
    device = job["device"]
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA training is unavailable. Install the GPU runtime/check the driver or explicitly select CPU.")
    random.seed(job["seed"])
    torch.manual_seed(job["seed"])
    torch.set_num_threads(max(1, min(4, int(os.environ.get('FORGEMIND_RESEARCH_THREADS','4')), os.cpu_count() or 1)))
    torch.use_deterministic_algorithms(True, warn_only=True)
    model = build_model(torch, spec, job["sequence_length"]).to(device)
    inherited_tensors = 0
    parent_path = Path(job['parent_checkpoint']) if job.get('parent_checkpoint') else None
    if parent_path and not (folder/'weights.pt').exists():
        if not parent_path.is_file() or hashlib.sha256(parent_path.read_bytes()).hexdigest() != job.get('parent_sha256'):
            raise ValueError('The parent checkpoint is missing or changed.')
        parent = torch.load(parent_path, map_location=device, weights_only=True)
        if parent.get('digest') != job['digest'] or parent.get('spec',{}).get('family') != spec['family']:
            raise ValueError('Parent checkpoint has a different dataset or architecture family.')
        current = model.state_dict()
        compatible = {key:value for key,value in parent['model'].items()
                      if key in current and current[key].shape == value.shape}
        model.load_state_dict(compatible, strict=False)
        inherited_tensors = len(compatible)
    optimizer = torch.optim.AdamW(model.parameters(), lr=spec["learning_rate"])
    generator = torch.Generator().manual_seed(job["seed"])
    step, prior_elapsed = 0, 0.0
    checkpoint = folder / "weights.pt"
    if checkpoint.exists():
        saved = torch.load(checkpoint, map_location=device, weights_only=True)
        if saved["spec"] != spec or saved["digest"] != job["digest"]:
            raise ValueError("Checkpoint architecture or dataset mismatch.")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        generator.set_state(saved["generator"].cpu())
        torch.set_rng_state(saved["torch_rng"].cpu())
        if device == "cuda" and saved.get("cuda_rng") is not None:
            torch.cuda.set_rng_state(saved["cuda_rng"].cpu())
        step, prior_elapsed = saved["step"], saved["elapsed_seconds"]
        inherited_tensors = saved.get('inherited_tensors', 0)
    if audit:
        if not checkpoint.exists():
            raise ValueError("There is no trained checkpoint to audit.")
        return {"test_nll": evaluate(torch, model, test, job, device), "protocol": job["protocol"]}

    tensor = torch.tensor(list(train), dtype=torch.long)
    parameters = sum(parameter.numel() for parameter in model.parameters())
    before = evaluate(torch, model, validation, job, device) if step == 0 else saved["initial_validation_nll"]
    training_started = time.monotonic()

    def save():
        if device == "cuda":
            torch.cuda.synchronize()
        temporary = checkpoint.with_suffix(".tmp")
        torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(), spec=spec,
            digest=job["digest"], generator=generator.get_state(), torch_rng=torch.get_rng_state(),
            cuda_rng=torch.cuda.get_rng_state() if device == "cuda" else None,
            step=step, elapsed_seconds=prior_elapsed+time.monotonic()-training_started,
            initial_validation_nll=before, inherited_tensors=inherited_tensors), temporary)
        temporary.replace(checkpoint)

    while step < job["steps"] and prior_elapsed + time.monotonic()-training_started < job["seconds"]:
        if stopped():
            save()
            return {"status": "paused", "steps": step, "checkpoint": checkpoint.name,
                    "error": "Owner paused; optimizer, weights and random states were saved."}
        model.train()
        inputs, targets = batch(torch, tensor, job["sequence_length"], job["batch_size"], generator, device)
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.cross_entropy(model(inputs).reshape(-1, 256), targets.reshape(-1))
        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite training loss; candidate rejected.")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        step += 1
        if step % 10 == 0:
            atomic_json(folder / "progress.json", {"message": f"{spec['family']} · step {step}/{job['steps']} · loss {loss.item():.3f}"})
        if step % 50 == 0:
            save()
    save()
    score = evaluate(torch, model, validation, job, device)
    sample = list(b"def calculate")
    model.eval()
    with torch.no_grad():
        for _ in range(120):
            context = torch.tensor([sample[-job["sequence_length"]:]], device=device)
            sample.append(int(model(context)[0, -1].argmax()))
    (folder / "sample.txt").write_text(bytes(sample).decode("utf-8", errors="replace"), encoding="utf-8")
    return {"status": "completed", "validation_nll": score, "initial_validation_nll": before,
        "parameters": parameters, "checkpoint": checkpoint.name, "steps": step,
        "elapsed_seconds": time.monotonic()-started, "training_bytes": len(train), "device": device,
        "hardware": torch.cuda.get_device_name() if device == "cuda" else "CPU",
        "peak_vram_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else 0,
        "torch_version": str(torch.__version__), "protocol": job["protocol"],
        "inherited_tensors": inherited_tensors}


def main():
    path = Path(sys.argv[1]).resolve()
    audit = "--audit" in sys.argv[2:]
    try:
        result = run_job(path, audit=audit)
    except InterruptedError as exc:
        result = {"status": "paused", "error": str(exc)}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    atomic_json(path.parent / ("audit.json" if audit else "result.json"), result)
    print(json.dumps(result, allow_nan=False))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())

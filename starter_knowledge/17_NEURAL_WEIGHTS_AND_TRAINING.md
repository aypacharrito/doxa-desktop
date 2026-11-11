# Neural weights, 7B models, and local training

## What neural weights are

A language model is a mathematical network containing learned numbers called parameters or weights.
Training adjusts those numbers so the model becomes better at predicting useful continuations. Application
code can add tools, memory, retrieval, interfaces, and workflows, but changing that Python code does not by
itself change the model's neural weights.

## What 7B and Q4 mean

`7B` means approximately seven billion learned parameters. It describes model size, not a version number and
not the size of ForgeMind's Python application. `Q4` means the weights were compressed to roughly four bits
per parameter for efficient inference. Quantization is why a 7B GGUF can be around five gigabytes rather than
requiring the much larger memory used by full-precision training weights.

## Why a blank model is not a self-growing shortcut

An untrained model produces noise. Useful language and coding ability comes from pretraining on enormous,
carefully processed datasets using large compute systems. Letting a model repeatedly train on arbitrary web
pages or its own unverified output can teach errors, overwrite useful capabilities, amplify bias, and cause
model collapse. Internet access supplies information; it is not automatically good training data.

Start from a capable pretrained model. Use retrieval for changing facts, reviewed memory for preferences, and
tools for actions. Use weight training only for repeated behaviors or a narrow specialty that examples can
measure.

## The safe local path: LoRA or QLoRA

LoRA trains small adapter weights while keeping the base model mostly fixed. QLoRA combines an adapter with a
low-bit base model to reduce memory use. On a laptop RTX 4070 with about 8 GB of VRAM, a carefully configured
7B or 8B QLoRA experiment can be practical with a short sequence length, micro-batch size one, gradient
accumulation, and gradient checkpointing. It will be much slower and more memory-demanding than ordinary
inference.

The GGUF file used by ForgeMind is optimized for inference. Most common QLoRA training stacks require the
original model checkpoint and tokenizer in a trainable format such as Transformers/safetensors. A training
adapter must also match its exact base model.

## A useful training cycle

1. Define one narrow, measurable behavior.
2. Collect diverse examples with an instruction and an owner-reviewed ideal answer.
3. Split examples into training and validation sets.
4. Record the base model's benchmark before training.
5. Train a small adapter with checkpoints.
6. Compare the candidate against the untouched base on held-out tests.
7. Activate it only when the target improves without unacceptable regressions.
8. Keep the base model and a rollback record.

Do not automatically train on every conversation, every downloaded page, secrets, copyrighted material that
cannot be used for training, or the model's own unreviewed answers. Retrieval is the correct mechanism for most
new facts because it is immediate, attributable, editable, and does not damage the base model.

## Hardware reality

More VRAM allows larger models, longer training sequences, and larger batches. Training speed also depends on
memory bandwidth, tensor throughput, cooling, system RAM, storage, and software support. Frontier models are
trained using large distributed accelerator clusters plus major investments in datasets, research,
networking, storage, evaluation, and operations. One stronger GPU improves local options but does not reproduce
that entire system.

"""Measure Doxa's answer speed on this PC: old 1.10 settings vs new 1.11 settings.

Run BENCHMARK_SPEED.bat with Doxa closed (both need the GPU). Takes about a minute.
Results are printed and saved to benchmark-results.txt beside this file.
"""
from __future__ import annotations

import gc
import time
from pathlib import Path

from forgemind.config import SYSTEM_PROMPT, Settings, system_prompt_for
from forgemind.runtime import prepare_windows_dlls

QUESTION = "Hey Doxa, what should I focus on this afternoon to follow up with my insurance leads?"
HISTORY = [
    {"role": "user", "content": "Remind me what we talked about with the Mercury quotes yesterday."},
    {"role": "assistant", "content": "We went over three pending Mercury auto quotes and agreed to call the two "
                                     "customers whose renewals are coming up first, then email the third."},
]


def run(model_path, n_batch, n_ubatch, system_text, repeats=3):
    from llama_cpp import Llama

    llm = Llama(model_path=model_path, n_ctx=8192, n_gpu_layers=-1, flash_attn=True, n_batch=n_batch,
                n_ubatch=n_ubatch, n_threads=4, use_mmap="qwen3.5" not in Path(model_path).name.lower(), verbose=False)
    messages = [{"role": "system", "content": system_text}, *HISTORY, {"role": "user", "content": QUESTION}]
    prompt_tokens = sum(len(llm.tokenize(m["content"].encode(), add_bos=False)) for m in messages)
    firsts, rates = [], []
    for _ in range(repeats):
        llm.reset()
        started = time.perf_counter()
        first, count = None, 0
        for part in llm.create_chat_completion(messages=messages, max_tokens=120, temperature=0.2, stream=True):
            if part["choices"][0]["delta"].get("content"):
                count += 1
                if first is None:
                    first = time.perf_counter() - started
        total = time.perf_counter() - started
        firsts.append(first or total)
        rates.append(count / max(0.001, total - (first or 0)))
    llm.close()
    del llm
    gc.collect()
    return prompt_tokens, sorted(firsts)[len(firsts) // 2], sorted(rates)[len(rates) // 2]


def main():
    prepare_windows_dlls()
    model = Settings.load().model_path
    if not model or not Path(model).is_file():
        raise SystemExit("No local model is set in Doxa settings.")
    lines = [f"Model: {Path(model).name}", f"Question: {QUESTION}", ""]
    old_prompt = SYSTEM_PROMPT[:4000]  # 1.10 sent up to ~1000 tokens of the full prompt
    cases = [("1.10 (batch 256/128, full prompt)", 256, 128, old_prompt),
             ("1.11 (batch 1024/512, trimmed prompt)", 1024, 512, system_prompt_for(QUESTION))]
    for label, nb, nu, system_text in cases:
        print("Measuring", label, "…", flush=True)
        try:
            tokens, first, rate = run(model, nb, nu, system_text)
            lines.append(f"{label}: prompt {tokens} tokens · first word {first:.2f} s · {rate:.0f} tokens/s")
        except Exception as exc:
            lines.append(f"{label}: could not run ({exc}). Doxa 1.11 falls back to 256/128 automatically.")
    report = "\n".join(lines)
    print("\n" + report)
    Path(__file__).with_name("benchmark-results.txt").write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

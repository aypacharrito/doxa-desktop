from __future__ import annotations

import gc
import threading
import json
import re
from dataclasses import replace
from collections.abc import Iterator
from pathlib import Path

from .config import SYSTEM_PROMPT, Settings, system_prompt_for
from .runtime import prepare_windows_dlls
from .web import SearchResult
from .answer_filter import AnswerFilter
from .workspace import personal_context


class LocalEngine:
    def __init__(self) -> None:
        self._model = None
        self._path = ""
        self._context_size = 8192
        self._lock = threading.Lock()
        self._reasoning_model = False
        self._hybrid_model = False
        self.batch_sizes = (256, 128)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def model_name(self) -> str:
        return Path(self._path).name if self._path else "No model loaded"

    def load(self, model_path: str, context_size: int = 8192) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Model not found: {model_path}")
        prepare_windows_dlls()
        from llama_cpp import Llama

        with self._lock:
            if self._model is not None:
                self._model.close()
                self._model = None
                gc.collect()
            # Larger batches read the prompt several times faster on the GPU. If the
            # bigger compute buffer doesn't fit in VRAM, fall back to the old safe sizes.
            last_error = None
            for n_batch, n_ubatch in ((1024, 512), (256, 128)):
                try:
                    self._model = Llama(
                        model_path=model_path,
                        n_ctx=context_size,
                        n_gpu_layers=-1,
                        n_threads=max(2, (__import__("os").cpu_count() or 4) // 2),
                        flash_attn=True,
                        n_batch=n_batch,
                        n_ubatch=n_ubatch,
                        use_mmap='qwen3.5' not in Path(model_path).name.lower(),
                        verbose=False,
                    )
                    self.batch_sizes = (n_batch, n_ubatch)
                    break
                except Exception as exc:  # usually out of GPU memory
                    last_error = exc
                    gc.collect()
            if self._model is None:
                raise last_error
            self._path = model_path
            self._context_size = context_size
            self._reasoning_model = 'qwen3' in str(self._model.metadata.get('general.architecture','')).lower()
            self._hybrid_model = str(self._model.metadata.get('general.architecture','')).lower() in {'qwen35','qwen35moe','qwen3next'}
            self._set_thinking(False)

    def _set_thinking(self, enabled):
        if not self._reasoning_model:
            return
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter
        template=self._model.metadata.get('tokenizer.chat_template')
        if not template:
            raise ValueError('The new model is missing its chat template.')
        def token(identifier):
            return self._model.detokenize([identifier],special=True).decode('utf-8') if identifier >= 0 else ''
        formatter=Jinja2ChatFormatter(
            template='{% set enable_thinking = '+('true' if enabled else 'false')+' %}\n'+template,
            eos_token=token(self._model.token_eos()),bos_token=token(self._model.token_bos()),
            stop_token_ids=[self._model.token_eos()])
        self._model.chat_handler=formatter.to_chat_handler()

    def unload(self) -> None:
        """Release the text model so another local GPU model can run."""
        with self._lock:
            model = self._model
            self._model = None
            if model is not None and hasattr(model, "close"):
                model.close()
        gc.collect()

    @staticmethod
    def build_context(memories: list[dict[str, str]], web: list[SearchResult]) -> str:
        sections: list[str] = []
        if memories:
            body = []
            total = 0
            for item in memories:
                piece = f"SOURCE: {item['source']}\n{item['content']}"
                if total + len(piece) > 15000:
                    break
                body.append(piece)
                total += len(piece)
            sections.append("LOCAL KNOWLEDGE AND MEMORY:\n" + "\n\n".join(body))
        if web:
            body = [
                f"[{i}] {r.title}\nURL: {r.url}\n{r.evidence or r.snippet}"
                for i, r in enumerate(web, 1)
            ]
            sections.append("CURRENT WEB SEARCH RESULTS:\n" + "\n\n".join(body))
        return "\n\n".join(sections)

    def _token_count(self, text: str) -> int:
        return len(self._model.tokenize(text.encode("utf-8"), add_bos=False, special=False))

    def _clip_text(self, text: str, max_tokens: int, keep_ends: bool = False) -> str:
        tokens = self._model.tokenize(text.encode("utf-8"), add_bos=False, special=False)
        if len(tokens) <= max_tokens:
            return text
        marker = "\n\n[…content shortened to fit the model context…]\n\n"
        marker_tokens = self._model.tokenize(marker.encode("utf-8"), add_bos=False, special=False)
        available = max(32, max_tokens - len(marker_tokens))
        if keep_ends:
            head_size = max(16, available // 3)
            clipped = tokens[:head_size] + marker_tokens + tokens[-(available - head_size):]
        else:
            clipped = tokens[:available] + marker_tokens
        return self._model.detokenize(clipped).decode("utf-8", errors="replace")

    def _prepare_messages(
        self,
        history: list[dict[str, str]],
        user_text: str,
        settings: Settings,
        memories: list[dict[str, str]],
        web: list[SearchResult],
    ) -> tuple[list[dict[str, str]], int]:
        output_limit = min(settings.max_tokens, max(256, settings.context_size // 4))
        input_budget = max(1024, settings.context_size - output_limit - 512)
        base = self._clip_text(system_prompt_for(user_text, bool(web)), min(1500, input_budget // 4))
        user_limit = max(700, min(3500, input_budget // 2))
        user = self._clip_text(user_text, user_limit, keep_ends=True)
        used = self._token_count(base) + self._token_count(user) + 96
        remaining = max(0, input_budget - used)

        context = personal_context(settings) + '\n\n' + self.build_context(memories, web)
        context_limit = min(2200, max(0, remaining * 2 // 3))
        context = self._clip_text(context, context_limit) if context and context_limit >= 64 else ""
        used += self._token_count(context) if context else 0
        remaining = max(0, input_budget - used)

        kept_history: list[dict[str, str]] = []
        for item in reversed(history[-12:]):
            if remaining < 80:
                break
            content = self._clip_text(item["content"], min(450, remaining), keep_ends=True)
            cost = self._token_count(content) + 16
            if cost > remaining:
                continue
            kept_history.append({"role": item["role"], "content": content})
            remaining -= cost
        kept_history.reverse()

        system = base + (f"\n\n{context}" if context else "")
        messages = [{"role": "system", "content": system}, *kept_history, {"role": "user", "content": user}]
        return messages, output_limit

    def stream(
        self,
        history: list[dict[str, str]],
        user_text: str,
        settings: Settings,
        memories: list[dict[str, str]],
        web: list[SearchResult],
        stop_event=None,
    ) -> Iterator[str]:
        if self._model is None:
            raise RuntimeError("Choose and load a GGUF model first.")
        deep=self._reasoning_model and bool(re.search(
            r'\b(?:think deeply|think carefully|reason carefully|prove|step by step|discount|tax|probability|logically|therefore)\b',
            user_text,re.I))
        effective=replace(settings,max_tokens=max(settings.max_tokens,2048)) if deep else settings
        messages, output_limit = self._prepare_messages(history, user_text, effective, memories, web)
        with self._lock:
            # Everyday voice turns stay quick. Explicit deep requests can spend more tokens.
            self._set_thinking(deep)
            if self._hybrid_model:
                self._model.reset()  # A fresh recurrent state is required for a changed conversation.
            visible=AnswerFilter(thinking=deep)
            response = self._model.create_chat_completion(
                messages=messages,
                temperature=settings.temperature,
                max_tokens=output_limit,
                stream=True,
            )
            try:
                for part in response:
                    if stop_event is not None and stop_event.is_set():
                        break
                    delta = part.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        value=visible.feed(delta) if self._reasoning_model else delta
                        if value:
                            yield value
                if self._reasoning_model and not (stop_event and stop_event.is_set()):
                    tail=visible.finish()
                    if tail:
                        yield tail
            finally:
                if hasattr(response, "close"):
                    response.close()

    def generate_json(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 3000,
        temperature: float = 0.1,
    ) -> dict:
        if self._model is None:
            raise RuntimeError("Choose and load a GGUF model first.")
        # Code patches need more output than ordinary chat. Reserve up to half the
        # actual context, leaving the rest for the goal and source excerpts.
        output_limit = min(max_tokens, max(512, self._context_size // 2))
        input_budget = max(1024, self._context_size - output_limit - 384)
        fitted_system = self._clip_text(system, min(900, max(256, input_budget // 4)))
        remaining = max(256, input_budget - self._token_count(fitted_system) - 32)
        fitted_prompt = self._clip_text(prompt, remaining, keep_ends=True)
        with self._lock:
            self._set_thinking(False)
            if self._hybrid_model:
                self._model.reset()
            response = self._model.create_chat_completion(
                messages=[
                    {"role": "system", "content": fitted_system},
                    {"role": "user", "content": fitted_prompt},
                ],
                temperature=temperature,
                max_tokens=output_limit,
                response_format={"type": "json_object"},
                stream=False,
            )
        choice = response.get("choices", [{}])[0]
        if choice.get("finish_reason") == "length":
            raise ValueError(f"Structured output was truncated at {output_limit} tokens. "
                             "Use a smaller edit or fewer files; no partial patch was accepted.")
        content = choice.get("message", {}).get("content", "")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("The model did not return a JSON object.") from exc
            value = json.loads(content[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("The model response was not a JSON object.")
        return value

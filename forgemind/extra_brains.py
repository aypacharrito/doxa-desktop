"""Gemini and Kimi as extra brains for Doxa (the owner 2026-11-08: "add both those AIs, everything we can get to spread
out workflows").

- **Gemini** (Google AI Studio key, has a free tier): streaming `streamGenerateContent`, optional **Google Search
  grounding** (`tools: [{google_search: {}}]`) for research with real source links. Good, cheap bulk research.
- **Kimi** (Moonshot AI platform key, pay-as-you-go): OpenAI-compatible `/chat/completions` streaming. Strong, cheap
  writing/drafting.
- **OpenCode Go** ($10/month subscription, one key for Kimi, DeepSeek, Qwen, GLM…; usage limits per 5 h/week/month):
  the same OpenAI-compatible protocol at `https://opencode.ai/zen/go/v1`. Prefers the newest Kimi model it offers.

Both pick their model from the account's own model list (`/models`), so nothing here hard-codes a model that may not
exist; Settings can pin one. Keys are pasted in Settings → AI brains, stored DPAPI-encrypted for this Windows account
(never in chat or a file in clear). Each has its own monthly budget; costs are estimates from token counts at the
prices in Settings (unverified list prices — the budget is a safety cap, not a bill).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import requests

from .windows_credentials import windows_key


class KeyedBrain:
    provider_id = ""
    display_name = ""
    key_file = ""
    key_pattern = re.compile(r"^\S{20,}$")
    local = False

    def __init__(self, root, budget, model="", price=(0.5, 2.5), transport=None):
        self.root = Path(root)
        self.budget = budget
        self.pinned = model
        self.price = price  # USD per million input/output tokens (estimate for the budget)
        self.transport = transport or requests
        self._model = ""
        self._lock = threading.Lock()

    @property
    def key_path(self) -> Path:
        return self.root / self.key_file

    @property
    def loaded(self) -> bool:
        return self.key_path.is_file()

    @property
    def model_name(self) -> str:
        return self._model or self.pinned or self.display_name

    def save_key(self, key: str) -> None:
        key = (key or "").strip()
        if not self.key_pattern.match(key):
            raise ValueError(f"That doesn't look like a {self.display_name} API key.")
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(windows_key(key.encode("utf-8"), True))
        self._model = ""

    def forget_key(self) -> None:
        self.key_path.unlink(missing_ok=True)
        self._model = ""

    def _key(self) -> str:
        try:
            return windows_key(self.key_path.read_bytes(), False).decode("utf-8")
        except Exception:
            raise ValueError(f"Windows couldn't unlock the {self.display_name} key. Re-enter it in AI brains.") from None

    def _fail(self, response) -> ValueError:
        code = getattr(response, "status_code", 0)
        if code in (401, 403):
            return ValueError(f"{self.display_name} rejected the key (or it has no access). Check it in AI brains.")
        if code == 429:
            return ValueError(f"{self.display_name} is rate-limiting or out of credit/free quota right now.")
        if code in (500, 502, 503, 504):
            return ValueError(f"{self.display_name} is overloaded right now (HTTP {code}); try again in a few minutes.")
        if code == 404:
            return ValueError(f"{self.display_name} doesn't offer the model {self.model_name} to this key.")
        return ValueError(f"{self.display_name} request failed (HTTP {code}).")

    def _settle(self, identifier, state, prompt_chars, out_chars, usage=None):
        tokens_in = (usage or {}).get("in") or prompt_chars / 4
        tokens_out = (usage or {}).get("out") or out_chars / 4
        usd = (tokens_in * self.price[0] + tokens_out * self.price[1]) / 1_000_000
        try:
            self.budget.settle(identifier, state, usd)
        except Exception:
            pass

    @staticmethod
    def _sse(response):
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except ValueError:
                continue


class GeminiBrain(KeyedBrain):
    provider_id, display_name, key_file = "gemini", "Gemini", "gemini-key.dpapi"
    BASE = "https://generativelanguage.googleapis.com/v1beta"
    key_pattern = re.compile(r"^[A-Za-z0-9_.\-]{30,}$")  # classic AIza… keys and the newer AQ.… keys

    def pick_model(self) -> str:
        """The newest Flash model this key can use (fast, cheap, free-tier friendly), unless one is pinned."""
        if self.pinned:
            return self.pinned
        with self._lock:
            if self._model:
                return self._model
            response = self.transport.get(f"{self.BASE}/models", headers={"x-goog-api-key": self._key()},
                                          params={"pageSize": 200}, timeout=(5, 15))
            if not response.ok:
                raise self._fail(response)
            names = [m.get("name", "").split("/")[-1] for m in response.json().get("models", [])
                     if "generateContent" in (m.get("supportedGenerationMethods") or [])]
            self._model = choose_model(names, r"^gemini-(\d+(?:\.\d+)?)-flash$", r"^gemini-.*flash", r"^gemini-")
            if not self._model:
                raise ValueError("This Gemini key has no text models available.")
            return self._model

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000, search=False):
        if not self.loaded:
            raise ValueError("Connect Gemini in Settings → AI brains first.")
        model = self.pick_model()
        identifier = self.budget.reserve(2)
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])}]}
                    for m in messages]
        body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if search:
            body["tools"] = [{"google_search": {}}]
        state, out, usage, sources = "interrupted", 0, {}, []
        prompt_chars = len(system or "") + sum(len(str(m["content"])) for m in messages)
        try:
            response = self.transport.post(f"{self.BASE}/models/{model}:streamGenerateContent",
                                           params={"alt": "sse"}, headers={"x-goog-api-key": self._key()},
                                           json=body, stream=True, timeout=(5, 60))
            if not response.ok:
                state = "failed"
                raise self._fail(response)
            for event in self._sse(response):
                if stop_event is not None and stop_event.is_set():
                    state = "stopped"
                    return
                for candidate in event.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        text = part.get("text")
                        if text:
                            out += len(text)
                            yield text
                    for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
                        web = chunk.get("web") or {}
                        if web.get("uri") and web["uri"] not in [s[0] for s in sources]:
                            sources.append((web["uri"], web.get("title", "")))
                meta = event.get("usageMetadata") or {}
                if meta:
                    usage = {"in": meta.get("promptTokenCount"), "out": meta.get("candidatesTokenCount")}
            if sources:
                yield "\n\nSources (Google Search):\n" + "\n".join(f"- {title or uri}: {uri}" for uri, title in sources[:20])
            state = "completed"
        except requests.Timeout:
            state = "uncertain"
            raise ValueError("Gemini stopped answering (no reply for a minute); it's probably overloaded.") from None
        except requests.RequestException:
            state = "uncertain"
            raise ValueError("Couldn't reach Gemini.") from None
        finally:
            self._settle(identifier, state, prompt_chars, out, usage)


class KimiBrain(KeyedBrain):
    provider_id, display_name, key_file = "kimi", "Kimi", "kimi-key.dpapi"
    BASE = "https://api.moonshot.ai/v1"
    key_pattern = re.compile(r"^sk-\S{20,}$")
    PREFER = (r"^(?:[\w.-]+/)?kimi-k(\d+(?:\.\d+)?)", r"^(?:[\w.-]+/)?kimi-", r"^moonshot-")

    def pick_model(self) -> str:
        """The newest Kimi K-series chat model on this account (no vision/thinking variants), unless one is pinned."""
        if self.pinned:
            return self.pinned
        with self._lock:
            if self._model:
                return self._model
            response = self.transport.get(f"{self.BASE}/models", headers={"Authorization": "Bearer " + self._key()},
                                          timeout=(5, 15))
            if not response.ok:
                raise self._fail(response)
            names = [m.get("id", "") for m in response.json().get("data", [])]
            plain = [n for n in names if not re.search(r"vision|thinking|embedding|-free$", n)]
            self._model = choose_model(plain, *self.PREFER) or (plain[0] if plain else names[0] if names else "")
            if not self._model:
                raise ValueError(f"This {self.display_name} key has no chat models available.")
            return self._model

    def _headers(self, session: str = "") -> dict:
        return {"Authorization": "Bearer " + self._key()}

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000, session=""):
        if not self.loaded:
            raise ValueError(f"Connect {self.display_name} in Settings → AI brains first.")
        model = self.pick_model()
        identifier = self.budget.reserve(3)
        chat = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])}
            for m in messages]
        state, out, usage = "interrupted", 0, {}
        prompt_chars = sum(len(str(m["content"])) for m in chat)
        try:
            response = self.transport.post(f"{self.BASE}/chat/completions",
                                           headers=self._headers(session),
                                           json={"model": model, "messages": chat, "stream": True, "max_tokens": max_tokens},
                                           stream=True, timeout=(5, 180))
            if not response.ok:
                state = "failed"
                raise self._fail(response)
            for event in self._sse(response):
                if stop_event is not None and stop_event.is_set():
                    state = "stopped"
                    return
                for choice in event.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        out += len(text)
                        yield text
                    if choice.get("usage"):
                        usage = {"in": choice["usage"].get("prompt_tokens"), "out": choice["usage"].get("completion_tokens")}
                if event.get("usage"):
                    usage = {"in": event["usage"].get("prompt_tokens"), "out": event["usage"].get("completion_tokens")}
            state = "completed"
        except requests.RequestException:
            state = "uncertain"
            raise ValueError(f"Couldn't reach {self.display_name}.") from None
        finally:
            self._settle(identifier, state, prompt_chars, out, usage)


class OpenCodeGoBrain(KimiBrain):
    """OpenCode Go: flat $10/month, one key for several open models (Kimi first, then DeepSeek, Qwen, GLM…).
    The Doxa budget here counts estimated usage against the plan's included allowance, not extra spending."""
    provider_id, display_name, key_file = "opencode", "OpenCode Go", "opencode-key.dpapi"
    BASE = "https://opencode.ai/zen/go/v1"
    key_pattern = re.compile(r"^\S{20,}$")
    PREFER = (r"^(?:[\w.-]+/)?kimi-k(\d+(?:\.\d+)?)", r"^(?:[\w.-]+/)?kimi-", r"^(?:[\w.-]+/)?deepseek",
              r"^(?:[\w.-]+/)?qwen", r"^(?:[\w.-]+/)?glm")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import uuid
        self.default_session = "doxa-" + uuid.uuid4().hex  # one per Doxa run, unless a caller names a conversation

    def _headers(self, session: str = "") -> dict:
        # OpenCode Go's docs: send a stable session ID in x-opencode-session for each conversation (routing + caching).
        return {"Authorization": "Bearer " + self._key(), "x-opencode-session": session or self.default_session}

    def _fail(self, response) -> ValueError:
        if getattr(response, "status_code", 0) == 429:
            return ValueError("OpenCode Go hit its plan's usage limit for now (it resets every few hours/weekly).")
        return super()._fail(response)


def choose_model(names, versioned: str, *fallbacks: str) -> str:
    """Highest version among names matching `versioned` (group 1 = version), else the first fallback match.
    Previews/experimental models lose to stable ones of the same version."""
    best, best_key = "", None
    for name in names:
        match = re.match(versioned, name)
        if not match:
            continue
        version = tuple(int(p) for p in match.group(1).split("."))
        stable = 0 if re.search(r"preview|exp|latest", name) else 1
        key = (version, stable, -len(name))
        if best_key is None or key > best_key:
            best, best_key = name, key
    if best:
        return best
    for pattern in fallbacks:
        for name in names:
            if re.match(pattern, name):
                return name
    return ""

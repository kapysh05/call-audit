"""LLM backends and answer parsing.

Two backends, both spoken to over plain HTTP so the package has no vendor SDK
dependency:

* ``ollama``  — a local server (the default; nothing leaves the machine).
* ``openai``  — any OpenAI-compatible ``/chat/completions`` endpoint, which
  covers hosted APIs as well as vLLM, LM Studio, llama.cpp and friends.

Both are asked for JSON, and both are still capable of wrapping it in prose or
a markdown fence, so :func:`extract_json` is deliberately forgiving.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Config

DEFAULT_OLLAMA_URL = "http://localhost:11434"


@dataclass(frozen=True)
class ChatResult:
    text: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    elapsed_sec: float = 0.0

    @property
    def tokens_per_sec(self) -> float | None:
        if self.tokens_out and self.elapsed_sec > 0:
            return round(self.tokens_out / self.elapsed_sec, 1)
        return None


def extract_json(text: str) -> dict | None:
    """Parse a JSON object out of a model answer, tolerating the usual mess."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```\s*$", "", candidate)
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} span in the answer.
    match = re.search(r"\{[\s\S]*\}", candidate)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _post_json(url: str, payload: dict, headers: dict[str, str],
               timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach {url}: {exc.reason}") from exc


class OllamaClient:
    """Local Ollama server."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.base_url = (cfg.llm.base_url or DEFAULT_OLLAMA_URL).rstrip("/")

    def chat(self, messages: list[dict]) -> ChatResult:
        started = time.time()
        data = _post_json(
            f"{self.base_url}/api/chat",
            {
                "model": self.cfg.llm.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self.cfg.llm.temperature,
                    "num_predict": self.cfg.llm.max_output_tokens,
                    "num_ctx": self.cfg.llm.num_ctx,
                },
            },
            headers={},
            timeout=self.cfg.llm.timeout_sec,
        )
        return ChatResult(
            text=(data.get("message") or {}).get("content", ""),
            tokens_in=data.get("prompt_eval_count"),
            tokens_out=data.get("eval_count"),
            elapsed_sec=round(time.time() - started, 1),
        )


class OpenAICompatClient:
    """Any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, cfg: Config, api_key: str = "") -> None:
        self.cfg = cfg
        if not cfg.llm.base_url:
            raise ValueError("llm.base_url is required for the 'openai' backend")
        self.base_url = cfg.llm.base_url.rstrip("/")
        self.api_key = api_key

    def chat(self, messages: list[dict]) -> ChatResult:
        started = time.time()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post_json(
            f"{self.base_url}/chat/completions",
            {
                "model": self.cfg.llm.model,
                "messages": messages,
                "temperature": self.cfg.llm.temperature,
                "max_tokens": self.cfg.llm.max_output_tokens,
                "response_format": {"type": "json_object"},
            },
            headers=headers,
            timeout=self.cfg.llm.timeout_sec,
        )
        choices = data.get("choices") or [{}]
        usage = data.get("usage") or {}
        return ChatResult(
            text=(choices[0].get("message") or {}).get("content", ""),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            elapsed_sec=round(time.time() - started, 1),
        )


def build_client(cfg: Config, api_key: str = "") -> OllamaClient | OpenAICompatClient:
    backend = cfg.llm.backend.lower()
    if backend == "ollama":
        return OllamaClient(cfg)
    if backend in {"openai", "openai-compatible"}:
        return OpenAICompatClient(cfg, api_key=api_key)
    raise ValueError(f"unsupported llm.backend: {cfg.llm.backend}")

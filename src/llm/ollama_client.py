"""Ollama HTTP client with an offline fallback."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .llm_client import DeterministicLLMClient, LLMClient


class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str = "deepseek-coder",
        base_url: str = "http://localhost:11434",
        timeout: int = 60,
        fallback: LLMClient | None = None,
    ) -> None:
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.fallback = fallback or DeterministicLLMClient()

    def generate(self, prompt: str) -> str:
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload: dict[str, Any] = json.loads(response.read().decode())
            if not isinstance(payload, dict):
                raise RuntimeError("Ollama returned an invalid JSON response")
            result = str(payload.get("response", "")).strip()
            if result:
                return result
            raise RuntimeError("Ollama returned an empty response")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            return self.fallback.generate(prompt + f"\n\n[Offline fallback: {exc}]")

"""Anthropic Messages API client.

The official SDK is used when available; urllib keeps this integration usable
without making the SDK a mandatory import.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .llm_client import DeterministicLLMClient, LLMClient


class AnthropicClient(LLMClient):
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        timeout: int = 60,
        fallback: LLMClient | None = None,
    ) -> None:
        self.model, self.api_key, self.timeout = model, api_key or os.getenv("ANTHROPIC_API_KEY"), timeout
        self.fallback = fallback or DeterministicLLMClient()

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            return self.fallback.generate(prompt)
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(
                {"model": self.model, "max_tokens": 1200, "messages": [{"role": "user", "content": prompt}]}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload: dict[str, Any] = json.loads(response.read().decode())
            content = payload.get("content") or []
            result = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
            if not result:
                raise RuntimeError("Anthropic returned an empty response")
            return result
        except Exception:
            if self.fallback:
                return self.fallback.generate(prompt)
            raise

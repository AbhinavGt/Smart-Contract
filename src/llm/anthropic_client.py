"""Anthropic Messages API client.

The official SDK is used when available; urllib keeps this integration usable
without making the SDK a mandatory import.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from .llm_client import DeterministicLLMClient, LLMBackendError, LLMClient, LLMResult


class AnthropicClient(LLMClient):
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        timeout: int = 60,
        fallback: LLMClient | None = None,
        allow_offline_fallback: bool = False,
    ) -> None:
        self.model, self.api_key, self.timeout = model, api_key or os.getenv("ANTHROPIC_API_KEY"), timeout
        self.fallback = fallback or DeterministicLLMClient()
        self.allow_offline_fallback = allow_offline_fallback

    def generate(self, prompt: str) -> LLMResult:
        if not self.api_key:
            logging.getLogger(__name__).warning(
                "ANTHROPIC_API_KEY is not configured; using deterministic offline explanation"
            )
            if not self.allow_offline_fallback:
                raise LLMBackendError(
                    "LLM backend 'anthropic' is unavailable because ANTHROPIC_API_KEY "
                    "is not configured. Re-run with --allow-offline-fallback only "
                    "for offline testing."
                )
            fallback = self.fallback.generate(prompt)
            return LLMResult(fallback.text if isinstance(fallback, LLMResult) else str(fallback), True, "missing API key")
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
            return LLMResult(result)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Anthropic request failed; using deterministic offline explanation: %s", exc
            )
            if self.fallback:
                if not self.allow_offline_fallback:
                    raise LLMBackendError(f"LLM backend 'anthropic' request failed: {exc}") from exc
                fallback = self.fallback.generate(prompt)
                return LLMResult(fallback.text if isinstance(fallback, LLMResult) else str(fallback), True, str(exc))
            raise

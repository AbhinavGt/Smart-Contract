"""Ollama HTTP client with an offline fallback."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .llm_client import DeterministicLLMClient, LLMBackendError, LLMClient, LLMResult


class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        base_url: str = "http://localhost:11434",
        timeout: int = 60,
        fallback: LLMClient | None = None,
        allow_offline_fallback: bool = False,
    ) -> None:
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.fallback = fallback or DeterministicLLMClient()
        self.allow_offline_fallback = allow_offline_fallback

    def check_available(self) -> None:
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 5)):
                return
        except (OSError, urllib.error.URLError) as exc:
            raise LLMBackendError(
                f"LLM backend 'ollama' is unreachable ({exc}). Start it with "
                "`ollama serve` and ensure the configured model is pulled, or "
                "re-run with --allow-offline-fallback to use a deterministic "
                "rule-based fallback for testing purposes (NOT equivalent to real model output)."
            ) from exc

    def generate(self, prompt: str) -> LLMResult:
        # --- TEMPORARY DIAGNOSTIC: log the exact prompt being sent ---
        with open("/tmp/ollama_prompt_debug.txt", "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(prompt)
            f.write("\n")
        # --- end temporary diagnostic ---

        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(
                {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 500,
                        "temperature": 0.2,
                        "stop": ["### Response", "```\n\n###"],
                        "repeat_penalty": 1.3,
                    },
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_bytes = response.read()
                payload: dict[str, Any] = json.loads(raw_bytes.decode())

            # --- TEMPORARY DIAGNOSTIC: log the full raw payload, untouched ---
            with open("/tmp/ollama_raw_debug.json", "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                json.dump(payload, f, indent=2)
                f.write("\n")
            print(f"[DIAGNOSTIC] Raw Ollama response appended to /tmp/ollama_raw_debug.json "
                  f"(response length: {len(str(payload.get('response', '')))} chars)")
            # --- end temporary diagnostic ---

            if not isinstance(payload, dict):
                raise RuntimeError("Ollama returned an invalid JSON response")
            result = str(payload.get("response", "")).strip()
            if result:
                return LLMResult(result)
            raise RuntimeError("Ollama returned an empty response")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            logging.getLogger(__name__).warning(
                "Ollama unavailable; using deterministic offline explanation: %s", exc
            )
            if not self.allow_offline_fallback:
                raise LLMBackendError(
                    f"LLM backend 'ollama' is unreachable ({exc}). Re-run with "
                    "--allow-offline-fallback only for offline testing."
                ) from exc
            fallback = self.fallback.generate(prompt + f"\n\n[Offline fallback: {exc}]")
            if isinstance(fallback, LLMResult):
                return LLMResult(fallback.text, True, str(exc))
            return LLMResult(str(fallback), True, str(exc))

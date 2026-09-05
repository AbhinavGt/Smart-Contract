"""LLM client interface and offline fallback."""

from __future__ import annotations

from typing import Any


class LLMClient:
    def generate(self, prompt: str) -> str:
        """Generate text for a prompt."""
        raise NotImplementedError


class DeterministicLLMClient(LLMClient):
    """Useful offline response when no LLM service is available."""

    def generate(self, prompt: str) -> str:
        return (
            "### Assessment\n"
            "Likely true positive based on the static-analysis evidence; review the "
            "reported code path and any guards before deploying.\n\n"
            "### Risk\n"
            "An attacker may trigger the affected path under unexpected conditions, "
            "potentially causing loss of funds or unauthorized state changes.\n\n"
            "### Exploit example\n"
            "An adversary supplies crafted input or calls the function in an unsafe "
            "order to reach the flagged operation.\n\n"
            "### Suggested fix\n"
            "Apply checks-effects-interactions, explicit access control, and safe "
            "validation appropriate to the detector, then add a regression test.\n"
        )


def config_value(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value

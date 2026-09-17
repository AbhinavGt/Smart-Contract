"""LLM client interface and offline fallback."""

from __future__ import annotations

import re
from typing import Any


class LLMClient:
    def generate(self, prompt: str) -> str:
        """Generate text for a prompt."""
        raise NotImplementedError


class DeterministicLLMClient(LLMClient):
    """Useful offline response when no LLM service is available."""

    def generate(self, prompt: str) -> str:
        if "Output ONLY the corrected version of this function" in prompt:
            return self._generate_fix(prompt)
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

    @staticmethod
    def _generate_fix(prompt: str) -> str:
        """Return a conservative fix for the common sample vulnerabilities.

        This keeps the v4 CLI usable without Ollama while still requiring all
        normal compiler, ABI, and static-analysis gates before reporting success.
        """
        match = re.search(r"Original function:\s*```solidity\s*(.*?)```", prompt, re.DOTALL)
        if not match:
            return ""
        function = re.sub(r"(?m)^\s*\d+:\s?", "", match.group(1)).strip()
        target = re.search(r"Target function:\s*([A-Za-z_]\w*)", prompt)
        target_name = target.group(1) if target else ""
        function_start = (
            function.find(f"function {target_name}")
            if target_name
            else function.find("function ")
        )
        if function_start == -1:
            return ""
        function = function[function_start:]
        opening_brace = function.find("{")
        if opening_brace == -1:
            return ""
        depth = 0
        end = None
        for index in range(opening_brace, len(function)):
            if function[index] == "{":
                depth += 1
            elif function[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            return ""
        function = function[:end]
        if "call{value:" not in function or "-=" not in function:
            return function

        state_update = re.search(
            r"(?m)^(?P<indent>\s*)(?P<statement>[A-Za-z_]\w*\[[^\n;]+\]\s*-\=\s*[^;]+;)\s*$",
            function,
        )
        external_call = re.search(r"(?m)^(?P<indent>\s*)\(bool\s+\w+.*?call\{value:", function)
        if not state_update or not external_call:
            return function

        update_line = state_update.group(0)
        function_without_update = function[: state_update.start()] + function[state_update.end() :]
        call_position = re.search(r"(?m)^\s*\(bool\s+\w+.*$", function_without_update)
        if not call_position:
            return function
        insertion = update_line.rstrip() + "\n"
        return (
            function_without_update[: call_position.start()]
            + insertion
            + function_without_update[call_position.start() :]
        ).strip()


def config_value(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value

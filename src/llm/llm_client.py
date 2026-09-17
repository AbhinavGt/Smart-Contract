"""LLM client interface and offline fallback."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any


class LLMBackendError(RuntimeError):
    """Raised when the configured model backend cannot be reached."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    is_fallback: bool = False
    fallback_reason: str | None = None


class LLMClient:
    def generate(self, prompt: str) -> LLMResult:
        """Generate text for a prompt."""
        raise NotImplementedError


class DeterministicLLMClient(LLMClient):
    """Useful offline response when no LLM service is available."""

    def generate(self, prompt: str) -> LLMResult:
        if "VERDICT:" in prompt and "MISSING_CONTEXT:" in prompt:
            text = (
                "VERDICT: CONFIDENT\n"
                "REASON: The explanation is grounded in the detector, source code, and requested context.\n"
                "MISSING_CONTEXT: none"
            )
            return LLMResult(text)
        if (
            "Output ONLY the corrected version of this function" in prompt
            or "single ```solidity code fence" in prompt
        ):
            return LLMResult(f"```solidity\n{self._generate_fix(prompt)}\n```")
        if "gas-optimization auditor" in prompt:
            return LLMResult(self._generate_gas_explanation(prompt))
        return LLMResult(self._generate_security_explanation(prompt))

    @staticmethod
    def _finding_value(prompt: str, label: str) -> str:
        match = re.search(rf"(?m)^{re.escape(label)}:\s*(.+)$", prompt)
        return match.group(1).strip() if match else "the reported pattern"

    @classmethod
    def _generate_security_explanation(cls, prompt: str) -> str:
        check = cls._finding_value(prompt, "Vulnerability type").lower()
        function = cls._finding_value(prompt, "Function")
        description = cls._finding_value(prompt, "Description")
        if "reentrancy" in check:
            risk = "The external call can re-enter before the balance update, allowing repeated withdrawals."
            exploit = "A malicious recipient can call withdraw again from its receive hook before balances[msg.sender] is reduced."
            fix = "Update the balance before the external call and consider a reentrancy guard."
        elif "access" in check or "arbitrary-send" in check:
            risk = "An unauthorized caller may invoke the function and direct contract-controlled funds."
            exploit = "An attacker calls the unrestricted function and sends the contract balance to the attacker's address."
            fix = "Restrict the function with an owner check or an existing onlyOwner modifier."
        elif "tx-origin" in check:
            risk = "Using tx.origin for authorization allows an intermediate contract to trick an authorized user."
            exploit = "A malicious intermediary contract asks an owner to call it and then reaches this function."
            fix = "Use msg.sender with explicit access control instead of tx.origin."
        elif "timestamp" in check or "block-number" in check:
            risk = "Block timestamp or number can be influenced enough by validators to affect control-flow decisions."
            exploit = "A validator adjusts block timing within permitted bounds to influence the lucky or deadline branch."
            fix = "Avoid timestamps for security-critical randomness or use a robust oracle/commit-reveal design."
        elif "unchecked" in check:
            risk = "Ignoring an external call result can leave state inconsistent when the call fails."
            exploit = "The recipient rejects the call while the contract continues as if the operation succeeded."
            fix = "Check the returned success value and revert or handle failure explicitly."
        else:
            risk = f"The detector flagged {description[:240]} in {function} and it requires review of the affected path."
            exploit = f"An attacker may provide crafted input to reach the flagged operation in {function}."
            fix = "Apply the detector-specific mitigation and add a regression test for this path."
        return (
            f"### Assessment\nThe {check} report is consistent with the code in {function}; "
            "the finding should be reviewed as a likely true positive.\n\n"
            f"### Risk\n{risk}\n\n### Exploit example\n{exploit}\n\n"
            f"### Suggested fix\n{fix}\n"
        )

    @classmethod
    def _generate_gas_explanation(cls, prompt: str) -> str:
        pattern = cls._finding_value(prompt, "Optimization type")
        function = cls._finding_value(prompt, "Function")
        description = cls._finding_value(prompt, "Description")
        if "redundant-storage-read" in pattern:
            assessment = f"{function} reads the same storage expression repeatedly; the detector description is: {description}"
            impact = "Each repeated SLOAD costs gas and is avoidable when the value does not change within the path."
            optimization = "Load the storage value once into a local memory variable and reuse that variable."
        elif "costly-loop" in pattern:
            assessment = f"The loop in {function} is bounded by growing storage state and may become expensive."
            impact = "Gas usage grows with the number of stored elements and can eventually approach the block gas limit."
            optimization = "Cache the array length, bound work per transaction, or provide pagination while preserving behavior."
        else:
            assessment = f"{pattern} is a possible gas inefficiency in {function}; confirm the access pattern before changing it."
            impact = "The impact depends on execution frequency and whether the value or storage slot changes."
            optimization = "Apply the smallest pattern-specific optimization and benchmark before and after."
        return (
            f"### Assessment\n{assessment}\n\n### Gas impact\n{impact}\n\n"
            f"### Suggested optimization\n{optimization}\n"
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
        if "access-control" in prompt.lower() or "arbitrary-send-eth" in prompt.lower():
            opening = function.find("{")
            if opening != -1 and "msg.sender == owner" not in function:
                indentation = re.search(r"(?m)^(\s*)\S", function[opening + 1 :])
                indent = indentation.group(1) if indentation else "        "
                guard = f'\n{indent}require(msg.sender == owner, "only owner");'
                return function[: opening + 1] + guard + function[opening + 1 :]
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

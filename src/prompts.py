"""Prompt templates used by the analysis pipeline."""

from __future__ import annotations

from typing import Any


def build_explanation_prompt(
    code_snippet: str, finding: dict[str, Any], retrieved_context: list[str] | str
) -> str:
    context = "\n\n".join(retrieved_context) if isinstance(retrieved_context, list) else retrieved_context
    return f"""You are a smart contract security auditor. A static analysis tool flagged the following issue.

Vulnerability type: {finding.get("check", "unknown")}
Severity: {finding.get("impact", "unknown")}
Function: {finding.get("function_name", "contract scope")}
Description: {finding.get("description", "")}

Code:
```solidity
{code_snippet}
```

Relevant background on this vulnerability class:
{context}

Tasks:
1. State whether this appears to be a true positive or likely false positive, and why.
2. Explain the risk in plain language, specific to this function.
3. Give a concrete example of how this could be exploited.
4. Suggest a specific code fix.

Respond in structured markdown with exactly these four sections:
### Assessment
### Risk
### Exploit example
### Suggested fix
"""


def build_critique_prompt(
    code_snippet: str, finding: dict[str, Any], explanation: str
) -> str:
    """Build a strict, machine-parseable review prompt."""
    return f"""You are reviewing a security explanation for accuracy before it is shown to a developer.

Original code:
```solidity
{code_snippet}
```

Static analysis finding: {finding.get("check", "unknown")}

Explanation given:
{explanation}

Check the explanation against the actual code. Respond in this exact format:
VERDICT: CONFIDENT or UNCERTAIN
REASON: <one or two sentences>
MISSING_CONTEXT: <what additional information, if any, would help verify this — e.g. "calling function" or "re-retrieve: integer overflow patterns" or "none">
"""


def build_gas_explanation_prompt(
    code_snippet: str, finding: dict[str, Any], retrieved_context: list[str] | str
) -> str:
    """Prompt used by the gas agent; kept separate from security reasoning."""
    context = "\n\n".join(retrieved_context) if isinstance(retrieved_context, list) else retrieved_context
    return f"""You are a Solidity gas-optimization auditor. A pattern detector found a possible gas inefficiency.

Optimization type: {finding.get("type", finding.get("check", "unknown"))}
Function: {finding.get("function_name", "contract scope")}
Description: {finding.get("description", "")}

Code:
```solidity
{code_snippet}
```

Relevant gas-optimization guidance:
{context}

Explain whether the pattern is real, its likely gas impact, and a concrete
optimization that preserves behavior and security. Mention any trade-offs or
manual review needed. Respond in structured markdown with:
### Assessment
### Gas impact
### Suggested optimization
"""


def build_gas_critique_prompt(
    code_snippet: str, finding: dict[str, Any], explanation: str
) -> str:
    return f"""You are reviewing a gas-optimization explanation against Solidity code.

Original code:
```solidity
{code_snippet}
```

Detected gas pattern: {finding.get("type", finding.get("check", "unknown"))}
Explanation:
{explanation}

Respond exactly:
VERDICT: CONFIDENT or UNCERTAIN
REASON: <one or two sentences>
MISSING_CONTEXT: <"calling function", "re-retrieve: <topic>", or "none">
"""

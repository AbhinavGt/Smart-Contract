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

Grounding requirements:
This is a standalone, synthetic test contract used only for security analysis
testing. It is not associated with any real-world protocol, project,
organization, or open-source repository.
Only reference libraries, functions, imports, or standards (such as ERC/EIP
numbers) that are literally present in the Solidity code shown below. Do not
invent or assume any external library, framework, or standard that is not
explicitly imported or referenced in the code. Do not include URLs,
documentation links, or GitHub references. If uncertain, state the uncertainty
explicitly rather than filling the gap with a plausible but unverified claim.
Only describe vulnerability patterns actually present in the code. If the
retrieved background does not match, rely on the code and exact detector name.

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

This is a standalone synthetic contract. Do not invent libraries, standards,
protocols, URLs, or repository references. Only cite external names literally
present in the code. If uncertain, say so.

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


def build_fix_prompt(
    code_snippet: str, finding: dict[str, Any], explanation: str
) -> str:
    """Build a constrained prompt that asks the LLM for a single-function Solidity fix."""
    check = str(finding.get("check", "")).lower()
    guidance_by_type = {
        "access-control": """
This is an access-control vulnerability. Add an explicit restriction on who
may call this function, such as `require(msg.sender == owner, "...");` when an
`owner` state variable exists, or an existing `onlyOwner` modifier. Do not use
a comment or a condition that callers can bypass.
""",
        "arbitrary-send-eth": """
This is an access-control vulnerability. Restrict the function to the contract
owner before transferring funds, using `require(msg.sender == owner, "...");`
when the contract exposes an `owner` state variable.
""",
        "missing-zero-check": """
Validate address inputs with a non-zero address check before using them.
""",
    }
    type_guidance = next(
        (text for key, text in guidance_by_type.items() if key in check),
        "",
    )
    return f"""You are fixing a security vulnerability in a Solidity function.

Original function:
```solidity
{code_snippet}
```

Vulnerability: {finding.get("check", "unknown")}
Target function: {finding.get("function_name", "contract scope")}
Explanation of the issue: {explanation}
{type_guidance}

Output ONLY the corrected version of this function. Do not change its name,
parameters, visibility, or return type unless absolutely required to fix the
vulnerability. If a signature change is required, add a short comment directly
above the function stating why.

Output nothing except a single ```solidity code fence containing only the
corrected function. Do not include any sentence before or after the code fence.
"""

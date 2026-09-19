"""Generate and verify single-function Solidity fixes."""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

from ..llm import LLMClient, LLMResult
from ..prompts import build_fix_prompt
from .sandbox import _find_function_bounds, apply_fix_to_temp_copy
from .verify import check_compiles, check_interface_preserved, check_vulnerability_resolved


def generate_diff(original: str, updated: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile="original",
            tofile="fixed",
            lineterm="",
        )
    )

def extract_code_block(llm_response: str, function_name: str | None = None) -> str:
    """Extract only a fenced Solidity function from model output."""
    match = re.search(r"```(?:solidity)?[ \t]*\n(.*?)```", llm_response, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("No Solidity code fence found in LLM fix response.")
    code = match.group(1).strip()
    if not code:
        raise ValueError("The Solidity code fence in the LLM fix response was empty.")
    if function_name and not re.search(
        rf"\bfunction\s+{re.escape(function_name)}\s*\(",
        code,
    ):
        raise ValueError(
            f"The extracted Solidity code does not contain the target function '{function_name}'."
        )
    return code


def check_fix_scope(fixed_code: str, target_function_name: str) -> tuple[bool, str | None]:
    """Reject declarations outside the one function being replaced."""
    stripped = fixed_code.strip()
    if stripped.startswith("SCOPE_EXCEEDED"):
        return False, stripped
    declarations = re.findall(
        r"\b(function\s+\w+|constructor\s*\(|modifier\s+\w+)",
        fixed_code,
    )
    function_declarations = [item for item in declarations if item.startswith("function")]
    other_declarations = [item for item in declarations if not item.startswith("function")]
    if other_declarations:
        return False, (
            f"Fix declares a new constructor or modifier ({other_declarations[0]}), "
            "which exceeds single-function scope."
        )
    if len(function_declarations) > 1:
        return False, (
            f"Fix declares {len(function_declarations)} functions; expected exactly "
            f"one ({target_function_name})."
        )
    if len(function_declarations) == 1 and not re.search(
        rf"\bfunction\s+{re.escape(target_function_name)}\s*\(",
        fixed_code,
    ):
        return False, f"Fix does not contain the target function '{target_function_name}'."
    if len(function_declarations) == 0:
        return False, f"Fix does not contain the target function '{target_function_name}'."
    return True, None


def generate_verified_fix(
    finding: dict[str, Any],
    code_snippet: str,
    explanation: str,
    original_filepath: str | Path,
    *,
    llm: LLMClient,
    original_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a single-function fix and verify it through compiler, ABI, and Slither gates."""
    path = Path(original_filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {original_filepath}")

    function_name = str(finding.get("function_name") or "").split(",")[0].strip()
    if not function_name or function_name == "contract scope":
        return {
            "status": "failed",
            "gate_failed": "scope",
            "detail": (
                "This finding is attached to contract scope and cannot be "
                "auto-fixed by the single-function v4 pipeline."
            ),
        }

    result = llm.generate(build_fix_prompt(code_snippet, finding, explanation))
    is_fallback = result.is_fallback if isinstance(result, LLMResult) else False
    fallback_reason = result.fallback_reason if isinstance(result, LLMResult) else None
    raw_fixed_code = result.text if isinstance(result, LLMResult) else str(result)
    if raw_fixed_code.strip().startswith("SCOPE_EXCEEDED"):
        return {
            "status": "skipped",
            "gate_failed": "scope",
            "detail": raw_fixed_code.strip(),
            "is_fallback": is_fallback,
            "fallback_reason": fallback_reason,
        }
    try:
        fixed_code = extract_code_block(raw_fixed_code, function_name)
    except ValueError as exc:
        return {
            "status": "failed",
            "gate_failed": "extraction",
            "detail": str(exc),
            "is_fallback": is_fallback,
            "fallback_reason": fallback_reason,
        }
    in_scope, scope_reason = check_fix_scope(fixed_code, function_name)
    if not in_scope:
        return {
            "status": "skipped",
            "gate_failed": "scope",
            "detail": scope_reason or "Fix exceeded single-function scope.",
            "is_fallback": is_fallback,
            "fallback_reason": fallback_reason,
        }
    temp_path: str | None = None
    try:
        for attempt in range(2):
            temp_path = apply_fix_to_temp_copy(str(path), function_name, fixed_code)
            compiles, compile_error = check_compiles(temp_path)
            if compiles:
                break
            if attempt == 0:
                retry_prompt = (
                    build_fix_prompt(code_snippet, finding, explanation)
                    + f"\n\nPrevious attempt failed to compile: {compile_error}"
                )
                retry_result = llm.generate(retry_prompt)
                is_fallback = is_fallback or (
                    retry_result.is_fallback if isinstance(retry_result, LLMResult) else False
                )
                fallback_reason = fallback_reason or (
                    retry_result.fallback_reason if isinstance(retry_result, LLMResult) else None
                )
                raw_fixed_code = retry_result.text if isinstance(retry_result, LLMResult) else str(retry_result)
                try:
                    fixed_code = extract_code_block(raw_fixed_code, function_name)
                except ValueError as exc:
                    return {
                        "status": "failed",
                        "gate_failed": "extraction",
                        "detail": str(exc),
                        "is_fallback": is_fallback,
                        "fallback_reason": fallback_reason,
                    }
                in_scope, scope_reason = check_fix_scope(fixed_code, function_name)
                if not in_scope:
                    return {
                        "status": "skipped",
                        "gate_failed": "scope",
                        "detail": scope_reason or "Fix exceeded single-function scope.",
                        "is_fallback": is_fallback,
                        "fallback_reason": fallback_reason,
                    }
                continue
            return {
                "status": "failed",
                "gate_failed": "compilation",
                "detail": compile_error,
                "is_fallback": is_fallback,
                "fallback_reason": fallback_reason,
            }

        if temp_path is None:
            return {
                "status": "failed",
                "gate_failed": "compilation",
                "detail": "No temporary file was created to verify the fix.",
            }

        interface_ok, interface_msg = check_interface_preserved(str(path), temp_path, function_name)
        if not interface_ok:
            return {
                "status": "failed",
                "gate_failed": "interface",
                "detail": interface_msg,
            }

        resolved, new_findings = check_vulnerability_resolved(
            original_findings or [finding],
            temp_path,
            target_findings=[finding],
        )
        if not resolved:
            return {
                "status": "failed",
                "gate_failed": "static_analysis",
                "detail": "The original vulnerability remained present or a new issue was introduced.",
                "new_findings_introduced": new_findings,
            }

        original_source = path.read_text(encoding="utf-8")
        start, end = _find_function_bounds(original_source, function_name)
        return {
            "status": "verified",
            "gates_passed": ["compilation", "interface_preserved", "static_analysis"],
            "fixed_code": fixed_code,
            "diff": generate_diff(original_source[start:end], fixed_code),
            "new_findings_introduced": new_findings,
            "is_fallback": is_fallback,
            "fallback_reason": fallback_reason,
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

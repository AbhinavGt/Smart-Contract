"""Generate and verify single-function Solidity fixes."""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from ..llm import LLMClient
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

    fixed_code = llm.generate(build_fix_prompt(code_snippet, finding, explanation))
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
                fixed_code = llm.generate(retry_prompt)
                continue
            return {
                "status": "failed",
                "gate_failed": "compilation",
                "detail": compile_error,
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
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

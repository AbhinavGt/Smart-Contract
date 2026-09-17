"""Verification gates for generated Solidity fixes."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..static_analysis import run_slither


def _abi_map(filepath: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(filepath)
    compiler = shutil.which("solc")
    if compiler is None:
        raise RuntimeError("solc is not installed or not on PATH.")
    result = subprocess.run(
        [compiler, "--abi", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "solc --abi failed")
    payload = result.stdout.strip()
    if not payload:
        return {}
    try:
        abi = json.loads(payload)
    except json.JSONDecodeError:
        # solc may print warnings before the JSON; keep the response usable.
        first_brace = payload.find("[")
        if first_brace == -1:
            raise
        abi = json.loads(payload[first_brace:])
    if not isinstance(abi, list):
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for entry in abi:
        if isinstance(entry, dict) and entry.get("type") == "function":
            mapping[entry.get("name", "")] = entry
    return mapping


def check_compiles(filepath: str | Path) -> tuple[bool, str]:
    compiler = shutil.which("solc")
    if compiler is None:
        return False, "solc is not installed or not on PATH."
    result = subprocess.run(
        [compiler, "--bin", str(filepath)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, ""
    message = (result.stderr or result.stdout or "Compilation failed").strip()
    return False, message


def _function_signature(entry: dict[str, Any] | None) -> tuple[str, tuple[str, ...], tuple[str, ...], str, str]:
    if not entry:
        return ("", (), (), "", "")
    return (
        str(entry.get("name", "")),
        tuple(str(item.get("type", "")) for item in entry.get("inputs", []) if isinstance(item, dict)),
        tuple(str(item.get("type", "")) for item in entry.get("outputs", []) if isinstance(item, dict)),
        str(entry.get("stateMutability", "")),
        str(entry.get("visibility", "")),
    )


def check_interface_preserved(original_filepath: str | Path, fixed_filepath: str | Path, function_name: str) -> tuple[bool, str]:
    try:
        original_abi = _abi_map(original_filepath)
        fixed_abi = _abi_map(fixed_filepath)
    except RuntimeError as exc:
        return False, str(exc)
    original_entry = original_abi.get(function_name)
    fixed_entry = fixed_abi.get(function_name)
    if original_entry is None:
        return False, f"Original ABI does not contain function '{function_name}'."
    if fixed_entry is None:
        return False, f"Fixed ABI does not contain function '{function_name}'."
    original_sig = _function_signature(original_entry)
    fixed_sig = _function_signature(fixed_entry)
    if original_sig == fixed_sig:
        return True, "Interface preserved."
    return False, (
        f"Interface changed for '{function_name}': "
        f"original={original_sig}, fixed={fixed_sig}"
    )


def check_vulnerability_resolved(
    original_findings: list[dict[str, Any]],
    fixed_filepath: str | Path,
    *,
    target_findings: list[dict[str, Any]] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    try:
        new_findings = run_slither(str(fixed_filepath))
    except Exception as exc:  # pragma: no cover - surfaced to caller
        return False, [{"error": str(exc)}]

    baseline_types = {
        (str(item.get("check") or item.get("type") or "unknown").lower(), str(item.get("function_name") or "contract scope"))
        for item in original_findings
    }
    target_types = {
        (str(item.get("check") or item.get("type") or "unknown").lower(), str(item.get("function_name") or "contract scope"))
        for item in (target_findings or original_findings)
    }
    remaining = []
    for finding in new_findings:
        key = (
            str(finding.get("check") or finding.get("type") or "unknown").lower(),
            str(finding.get("function_name") or "contract scope"),
        )
        if key in target_types:
            remaining.append(finding)
    new_findings_introduced = [
        finding for finding in new_findings
        if (
            str(finding.get("check") or finding.get("type") or "unknown").lower(),
            str(finding.get("function_name") or "contract scope"),
        ) not in baseline_types
    ]
    return not remaining, new_findings_introduced

"""Small, defensive wrapper around Slither's command line interface."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class SlitherError(RuntimeError):
    """Raised when Slither cannot analyse a contract."""


def _json_from_output(output: str) -> dict[str, Any]:
    """Extract a JSON object even when a tool prefixes diagnostic text."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", output):
        try:
            value, _ = decoder.raw_decode(output[match.start() :])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise ValueError("Slither did not return valid JSON")


def _line_numbers(source: dict[str, Any]) -> list[int]:
    lines = source.get("lines") or source.get("lines_mapping") or []
    if isinstance(lines, list):
        return [int(line) for line in lines if str(line).isdigit()]
    return []


def _normalise_finding(detector: dict[str, Any], filename: str) -> dict[str, Any]:
    elements = detector.get("elements") or []
    functions: list[str] = []
    lines: list[int] = []
    files: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        name = element.get("name")
        if element.get("type") in {"function", "modifier"} and name:
            functions.append(str(name))
        source = element.get("source_mapping") or {}
        lines.extend(_line_numbers(source))
        filename_value = source.get("filename_relative") or source.get("filename_absolute")
        if filename_value:
            files.append(str(filename_value))
    return {
        "check": str(detector.get("check") or detector.get("id") or "unknown"),
        "impact": str(detector.get("impact") or detector.get("confidence") or "Unknown"),
        "confidence": str(detector.get("confidence") or ""),
        "description": str(detector.get("description") or detector.get("markdown") or ""),
        "function_name": ", ".join(dict.fromkeys(functions)) or "contract scope",
        "filename": files[0] if files else filename,
        "lines": sorted(set(lines)),
        "raw": detector,
    }


def run_slither(filepath: str, slither_bin: str = "slither", timeout: int = 120) -> list[dict[str, Any]]:
    """Run Slither and return normalised findings.

    Slither may return a non-zero status when detectors find issues, so status is
    only considered an error when no usable JSON was produced.
    """
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Contract file not found: {filepath}")
    executable = shutil.which(slither_bin)
    if executable is None:
        raise SlitherError(
            "Slither is not installed or not on PATH. Install it with "
            "`pip install slither-analyzer` (and a compatible solc compiler)."
        )
    try:
        completed = subprocess.run(
            [executable, str(path), "--json", "-"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SlitherError(f"Slither timed out after {timeout} seconds") from exc
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    try:
        payload = _json_from_output(combined)
    except ValueError as exc:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise SlitherError(f"Slither failed: {detail[-1000:]}") from exc
    detectors = (payload.get("results") or {}).get("detectors") or []
    if payload.get("success") is False and not detectors:
        error = (payload.get("error") or completed.stderr or "analysis failed")
        raise SlitherError(f"Slither failed: {error}")
    security_relevant_impacts = {"high", "medium", "low"}
    return [
        _normalise_finding(detector, str(path))
        for detector in detectors
        if isinstance(detector, dict)
        and str(detector.get("impact", "")).strip().lower() in security_relevant_impacts
    ]

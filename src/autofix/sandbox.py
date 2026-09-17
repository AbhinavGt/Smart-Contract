"""Sandbox helpers for applying a fix to a temp copy of a Solidity file."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def _strip_code_block(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            # Remove a surrounding fenced Solidity block but keep the inner code.
            body = lines[1:]
            if body and body[-1].strip().startswith("```"):
                body = body[:-1]
            text = "\n".join(body).strip()
    return text.strip()


def _find_function_bounds(source: str, function_name: str) -> tuple[int, int]:
    pattern = re.compile(
        rf"function\s+{re.escape(function_name)}\s*\([^)]*\)\s*(?:[a-zA-Z0-9_,\s()\[\]<>:]+)?\{{",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise ValueError(f"Function '{function_name}' not found in source file.")
    start = match.start()
    brace_index = source.find("{", match.start())
    if brace_index == -1:
        raise ValueError(f"Function '{function_name}' has no opening brace.")
    depth = 0
    for index in range(brace_index, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise ValueError(f"Could not locate end of function '{function_name}'.")


def apply_fix_to_temp_copy(original_filepath: str, function_name: str, fixed_code: str) -> str:
    """Return a temp file path containing a patched function body in a copy."""
    source_path = Path(original_filepath)
    source = source_path.read_text(encoding="utf-8")
    cleaned = _strip_code_block(fixed_code)
    if not cleaned:
        raise ValueError("No fixed function code was produced by the model.")
    start, end = _find_function_bounds(source, function_name)
    updated = source[:start] + cleaned + source[end:]

    fd, temp_path = tempfile.mkstemp(prefix="autofix_", suffix=".sol")
    os.close(fd)
    Path(temp_path).write_text(updated, encoding="utf-8")
    return temp_path

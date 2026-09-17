"""Heuristic gas-optimization agent.

The gas agent deliberately does not depend on Slither's security detectors.
It uses small, conservative source-pattern checks and then sends each finding
through the same bounded explanation/critic loop used by the security agent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from ..llm import LLMClient
from ..llm.llm_client import config_value
from ..pipeline import (
    _snippet,
    explain_finding_with_critic,
    load_config,
    make_llm_client,
)
from ..prompts import build_gas_critique_prompt, build_gas_explanation_prompt
from ..rag.retriever import retrieve


_STATE_ARRAY = re.compile(
    r"^\s*[A-Za-z_]\w*\s*\[[^\]]*\]\s+"
    r"(?:(?:public|private|internal|external|memory|calldata|storage)\s+)*"
    r"(?P<name>[A-Za-z_]\w*)\s*(?:;|=)"
)
_FUNCTION = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
_FOR_LOOP = re.compile(r"\bfor\s*\((?P<init>[^;]*);(?P<condition>[^;]*);(?P<step>[^)]*)\)")
_REQUIRE_STRING = re.compile(r"\brequire\s*\([^,\n]+,\s*(['\"])(?P<message>.*?)\1\s*\)")
_STRUCT = re.compile(r"\bstruct\s+[A-Za-z_]\w*\s*\{(?P<body>.*?)\}", re.DOTALL)
_FIELD = re.compile(r"\b(uint(?:8|16|32|64|128|160|192|224|256)?|bytes(?:1|2|4|8|16|32)?|address|bool)\b")


def _function_name(lines: list[str], line_number: int) -> str:
    for index in range(min(line_number - 1, len(lines) - 1), -1, -1):
        match = _FUNCTION.search(lines[index])
        if match:
            return match.group(1)
    return "contract scope"


def _scope_end(lines: list[str], start: int) -> int:
    """Return the next function declaration after a source line."""
    for index in range(start + 1, len(lines)):
        if _FUNCTION.search(lines[index]):
            return index
    return len(lines)


def _state_arrays(lines: list[str]) -> set[str]:
    arrays: set[str] = set()
    for line in lines:
        if line.lstrip().startswith("//"):
            continue
        match = _STATE_ARRAY.match(line)
        if match:
            arrays.add(match.group("name"))
    return arrays


def detect_gas_patterns(source: str) -> list[dict[str, Any]]:
    """Return normalized gas findings without invoking Slither or an LLM."""
    lines = source.splitlines()
    arrays = _state_arrays(lines)
    findings: list[dict[str, Any]] = []

    for number, line in enumerate(lines, 1):
        loop = _FOR_LOOP.search(line)
        if loop and ".length" in loop.group("condition"):
            names = [name for name in arrays if re.search(rf"\b{re.escape(name)}\s*\.length", loop.group("condition"))]
            if names:
                target = ", ".join(names) if names else "storage array"
                findings.append(
                    {
                        "type": "costly-loop",
                        "check": "costly-loop",
                        "impact": "Medium",
                        "confidence": "Medium",
                        "description": f"Loop bound reads {target}.length and can grow with storage state.",
                        "function_name": _function_name(lines, number),
                        "filename": "",
                        "lines": [number],
                        "detector": "gas-pattern",
                    }
                )

    # Look for repeated indexed reads of a known state array/mapping.  Exact
    # expression repetition avoids flagging ordinary one-off state access.
    state_names = set(arrays)
    for line in lines:
        declaration = re.match(
            r"\s*(?:mapping\s*\([^;]+\)|(?:uint|int|address|bytes|bool)[^;]*)\s+"
            r"(?:public|private|internal)?\s*([A-Za-z_]\w*)\s*(?:;|=)",
            line,
        )
        if declaration:
            state_names.add(declaration.group(1))
    for start, line in enumerate(lines):
        function = _function_name(lines, start + 1)
        expressions = re.findall(r"\b([A-Za-z_]\w*)\s*\[([^\]]+)\]", line)
        for name, index in expressions:
            if name not in state_names:
                continue
            expression = f"{name}[{index.strip()}]"
            following = "\n".join(lines[start : _scope_end(lines, start)])
            if len(re.findall(re.escape(expression), following)) >= 2:
                findings.append(
                    {
                        "type": "redundant-storage-read",
                        "check": "redundant-storage-read",
                        "impact": "Low",
                        "confidence": "Medium",
                        "description": f"{expression} is read repeatedly; cache the value in memory.",
                        "function_name": function,
                        "filename": "",
                        "lines": [start + 1],
                        "detector": "gas-pattern",
                    }
                )
                break

    # Repeated assignments to one storage variable in a compact function are
    # a useful, explainable approximation of redundant SSTORE operations.
    for start, line in enumerate(lines):
        function = _function_name(lines, start + 1)
        assignments = re.findall(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*=", line)
        for name in assignments:
            if name not in state_names:
                continue
            block = "\n".join(lines[start : _scope_end(lines, start)])
            if len(re.findall(rf"\b{re.escape(name)}\s*(?:\[[^\]]+\])?\s*=", block)) >= 2:
                findings.append(
                    {
                        "type": "redundant-storage-write",
                        "check": "redundant-storage-write",
                        "impact": "Low",
                        "confidence": "Low",
                        "description": f"Storage variable {name} is assigned more than once in one path.",
                        "function_name": function,
                        "filename": "",
                        "lines": [start + 1],
                        "detector": "gas-pattern",
                    }
                )
                break

    for number, line in enumerate(lines, 1):
        message = _REQUIRE_STRING.search(line)
        if message and len(message.group("message")) > 32:
            findings.append(
                {
                    "type": "inefficient-require-string",
                    "check": "inefficient-require-string",
                    "impact": "Informational",
                    "confidence": "High",
                    "description": "A long require revert string can be replaced with a custom error.",
                    "function_name": _function_name(lines, number),
                    "filename": "",
                    "lines": [number],
                    "detector": "gas-pattern",
                }
            )

    for match in _STRUCT.finditer(source):
        fields = _FIELD.findall(match.group("body"))
        # A larger field between sub-word fields commonly prevents packing.
        if len(fields) >= 3 and any(field in {"uint256", "bytes32"} for field in fields[1:-1]):
            line = source[: match.start()].count("\n") + 1
            findings.append(
                {
                    "type": "poor-struct-packing",
                    "check": "poor-struct-packing",
                    "impact": "Low",
                    "confidence": "Low",
                    "description": "Struct field order may prevent smaller values sharing storage slots.",
                    "function_name": "contract scope",
                    "filename": "",
                    "lines": [line],
                    "detector": "gas-pattern",
                }
            )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        key = (
            str(finding.get("type", "")),
            str(finding.get("function_name", "")),
            str(finding.get("description", "")),
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def analyze_gas(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    allow_offline_fallback: bool = False,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Detect and explain gas findings for one Solidity file."""
    path = Path(filepath)
    source = path.read_text(encoding="utf-8")
    config = load_config(config_path)
    if config_value(config, "gas", "enabled", default=True) is False:
        return []
    raw_findings = detect_gas_patterns(source)
    max_findings = int(config_value(config, "gas", "max_findings", default=50))
    raw_findings = raw_findings[: max(0, max_findings)]
    if not raw_findings:
        return []
    client = llm_client or make_llm_client(config, allow_offline_fallback=allow_offline_fallback)
    top_k = int(config_value(
        config, "gas_rag", "top_k",
        default=config_value(config, "gas", "top_k", default=config_value(config, "rag", "top_k", default=3)),
    ))
    persist = config_value(
        config, "gas_rag", "persist_directory",
        default=config_value(config, "rag", "persist_directory", default="chroma_db"),
    )
    embedding = config_value(
        config, "gas_rag", "embedding_model",
        default=config_value(config, "rag", "embedding_model", default="all-MiniLM-L6-v2"),
    )
    max_loops = int(config_value(config, "agent", "max_loops", default=3))
    explained: list[dict[str, Any]] = []
    source_lines = source.splitlines()
    for finding in raw_findings:
        progress and progress("Retrieving gas optimization context...")
        query = f"{finding['type']} {finding['description']}"
        try:
            context = retriever(
                query, k=top_k, persist_directory=persist,
                embedding_model=embedding, collection="vuln_knowledge_gas",
            )
        except TypeError:
            context = retriever(query, top_k)
        progress and progress("Generating gas optimization explanation...")
        item = dict(finding)
        item["filename"] = str(path)
        explanation, confident, loops_used, is_fallback, fallback_reason = explain_finding_with_critic(
            finding,
            _snippet(source_lines, finding.get("lines", [])),
            context,
            filepath=filepath,
            llm=client,
            max_loops=max_loops,
            retriever=retriever,
            persist_directory=persist,
            embedding_model=embedding,
            collection="vuln_knowledge_gas",
            explanation_prompt_builder=build_gas_explanation_prompt,
            critique_prompt_builder=build_gas_critique_prompt,
        )
        item.update(
            explanation=explanation,
            confident=confident,
            loops_used=loops_used,
            is_fallback=is_fallback,
        )
        if fallback_reason:
            item["fallback_reason"] = fallback_reason
        item.setdefault("function", item.get("function_name", "contract scope"))
        explained.append(item)
    return explained

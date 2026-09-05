"""Markdown and JSON report formatting."""

from __future__ import annotations

import json
from typing import Any


def _location(finding: dict[str, Any]) -> str:
    lines = finding.get("lines") or []
    line_text = ", ".join(str(line) for line in lines) if lines else "unknown"
    return f'{finding.get("function_name", "contract scope")}, lines {line_text}'


def format_report(contract_name: str, findings_with_explanations: list[dict[str, Any]]) -> str:
    title = f"# Security Report: {contract_name}\n\n"
    if not findings_with_explanations:
        return title + "No issues detected by static analysis.\n"
    sections = [title]
    review_findings = [
        (index, finding) for index, finding in enumerate(findings_with_explanations, 1)
        if not finding.get("confident", True)
    ]
    if review_findings:
        sections.append("## Needs manual review\n\n" + "\n".join(
            f"- Finding {index}: {finding.get('check', 'unknown')} "
            f"(loops: {finding.get('loops_used', 'unknown')})"
            for index, finding in review_findings
        ) + "\n")
    for index, finding in enumerate(findings_with_explanations, 1):
        confidence = "✅ Confident" if finding.get("confident", True) else "⚠️ Needs manual review"
        sections.append(
            f"## Finding {index}: {finding.get('check', 'unknown')} — "
            f"Severity: {finding.get('impact', 'Unknown')} — {confidence}\n"
            f"**Location:** {_location(finding)}\n\n"
            f"**Critic loops:** {finding.get('loops_used', 'unknown')}\n\n"
            f"{finding.get('explanation', 'No explanation generated.')}\n\n---\n"
        )
    return "\n".join(sections)


def format_json(contract_name: str, findings_with_explanations: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"contract": contract_name, "findings": findings_with_explanations},
        indent=2,
        ensure_ascii=False,
        default=str,
    )


def format_report_json(contract_name: str, findings_with_explanations: list[dict[str, Any]]) -> str:
    """Backward-friendly descriptive alias for :func:`format_json`."""
    return format_json(contract_name, findings_with_explanations)

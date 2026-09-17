"""Markdown and JSON report formatting."""

from __future__ import annotations

import json
from typing import Any


def _location(finding: dict[str, Any]) -> str:
    lines = finding.get("lines") or []
    line_text = ", ".join(str(line) for line in lines) if lines else "unknown"
    return f'{finding.get("function_name", "contract scope")}, lines {line_text}'


def _render_fix_section(finding: dict[str, Any]) -> str:
    fix = finding.get("fix") or finding.get("generated_fix")
    if not fix:
        return ""
    status = str(fix.get("status", "unknown")).capitalize()
    gate_info = ", ".join(f"{gate}" for gate in fix.get("gates_passed", [])) or "n/a"
    lines = [
        "**Suggested Fix:**",
        f"Status: {status} | Gates passed: {gate_info}",
    ]
    if fix.get("detail"):
        lines.append(f"Detail: {fix['detail']}")
    if fix.get("diff"):
        lines.append("```diff")
        lines.append(str(fix.get("diff", "")))
        lines.append("```")
    if fix.get("new_findings_introduced"):
        lines.append("**New findings introduced:**")
        lines.append(json.dumps(fix.get("new_findings_introduced", []), indent=2, default=str))
    return "\n".join(lines) + "\n\n"


def _format_finding_sections(
    heading: str,
    findings_with_explanations: list[dict[str, Any]],
    *,
    start_index: int = 1,
) -> list[str]:
    sections = [heading]
    if not findings_with_explanations:
        if heading.startswith("## Security"):
            sections.append("No issues detected in this category (no issues detected by static analysis).\n")
        else:
            sections.append("No issues detected in this category.\n")
        return sections
    review_findings = [
        (index, finding) for index, finding in enumerate(findings_with_explanations, start_index)
        if not finding.get("confident", True)
    ]
    if review_findings:
        sections.append("### Needs manual review\n\n" + "\n".join(
            f"- Finding {index}: {finding.get('type', finding.get('check', 'unknown'))} "
            f"(confidence: {finding.get('confidence', 'unknown')}, "
            f"critic loops: {finding.get('loops_used', 'unknown')})"
            for index, finding in review_findings
        ) + "\n")
    for index, finding in enumerate(findings_with_explanations, start_index):
        confidence = "✅ Confident" if finding.get("confident", True) else "⚠️ Needs manual review"
        kind = finding.get("type", finding.get("check", "unknown"))
        sections.append(
            f"### Finding {index}: {kind} — Severity: {finding.get('impact', 'Unknown')} — {confidence}\n"
            f"**Location:** {_location(finding)}\n\n"
            f"**Critic loops:** {finding.get('loops_used', 'unknown')}\n\n"
            f"{finding.get('explanation', 'No explanation generated.')}\n\n"
            f"{_render_fix_section(finding)}"
            f"---\n"
        )
    return sections


def format_report(
    contract_name: str,
    findings_with_explanations: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
) -> str:
    """Render legacy security lists or v3 findings grouped by domain."""
    if isinstance(findings_with_explanations, dict):
        security = findings_with_explanations.get("security", [])
        gas = findings_with_explanations.get("gas", [])
        sections = [
            f"# Security Report: {contract_name}\n",
            "Verified fixes pass compilation, interface-preservation, and static-analysis checks. "
            "They are not behaviorally proven equivalent to the original code; review before applying.\n\n",
        ]
        sections.extend(_format_finding_sections("## Security Findings\n", security))
        sections.extend(_format_finding_sections("## Gas Optimization Findings\n", gas))
        return "\n".join(sections)

    title = f"# Security Report: {contract_name}\n\n"
    if not findings_with_explanations:
        return title + "No issues detected by static analysis.\n"
    sections = [title, "Verified fixes pass compilation, interface-preservation, and static-analysis checks. They are not behaviorally proven equivalent to the original code; review before applying.\n\n"]
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
            f"{finding.get('explanation', 'No explanation generated.')}\n\n"
            f"{_render_fix_section(finding)}"
            f"---\n"
        )
    return "\n".join(sections)


def format_json(
    contract_name: str,
    findings_with_explanations: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
) -> str:
    return json.dumps(
        {"contract": contract_name, "findings": findings_with_explanations},
        indent=2,
        ensure_ascii=False,
        default=str,
    )


def format_report_json(
    contract_name: str,
    findings_with_explanations: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
) -> str:
    """Backward-friendly descriptive alias for :func:`format_json`."""
    return format_json(contract_name, findings_with_explanations)

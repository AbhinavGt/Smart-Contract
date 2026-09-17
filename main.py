"""Command-line entry point for AI Smart Contract Vulnerability Checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.autofix.pipeline import generate_verified_fix
from src.llm import AnthropicClient, LLMBackendError, OllamaClient
from src.pipeline import load_config, make_llm_client, orchestrate
from src.report.formatter import format_json, format_report
from src.static_analysis import SlitherError


def _snippet(source_lines: list[str], lines: list[int], radius: int = 2) -> str:
    if not lines:
        return "\n".join(source_lines[: min(20, len(source_lines))])
    start, end = max(1, min(lines) - radius), min(len(source_lines), max(lines) + radius)
    return "\n".join(f"{number}: {source_lines[number - 1]}" for number in range(start, end + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit one Solidity contract with Slither and an LLM.")
    parser.add_argument("--file", required=True, help="Path to a Solidity source file")
    parser.add_argument("--output", default="report.md", help="Markdown report path")
    parser.add_argument(
        "--json-output",
        help="Optional path for the raw JSON findings report",
    )
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    parser.add_argument("--fix", action="store_true", help="Generate a verified fix for the first security finding")
    parser.add_argument("--fix-index", type=int, default=0, help="Index of the security finding to repair when --fix is set")
    parser.add_argument(
        "--allow-offline-fallback",
        action="store_true",
        help="Allow deterministic rule-based output when the configured LLM is unavailable",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        llm = make_llm_client(config, allow_offline_fallback=args.allow_offline_fallback)
        if isinstance(llm, OllamaClient) and not args.allow_offline_fallback:
            llm.check_available()
        if isinstance(llm, AnthropicClient) and not args.allow_offline_fallback and not llm.api_key:
            raise LLMBackendError(
                "LLM backend 'anthropic' is unavailable because ANTHROPIC_API_KEY is not configured. "
                "Set the key or re-run with --allow-offline-fallback for offline testing."
            )
        findings = orchestrate(
            args.file,
            args.config,
            llm_client=llm,
            allow_offline_fallback=args.allow_offline_fallback,
            progress=lambda message: print(message, flush=True),
        )
        contract_name = Path(args.file).name
        report = format_report(contract_name, findings)
        if args.fix:
            security = findings.get("security", [])
            if not security:
                print("No security findings available to generate a fix.", file=sys.stderr)
                return 1
            if args.fix_index < 0 or args.fix_index >= len(security):
                print(f"Fix index out of range: 0-{len(security) - 1}", file=sys.stderr)
                return 1
            target = security[args.fix_index]
            source_lines = Path(args.file).read_text(encoding="utf-8").splitlines()
            snippet = _snippet(source_lines, target.get("lines", []))
            fix = generate_verified_fix(
                target,
                snippet,
                target.get("explanation", ""),
                args.file,
                llm=llm,
                original_findings=security,
            )
            target["fix"] = fix
            report = format_report(contract_name, findings)
            if fix["status"] == "verified":
                print("Generated verified fix:")
                print(fix["diff"])
            else:
                print(f"Fix failed at gate '{fix.get('gate_failed', 'unknown')}': {fix.get('detail', 'No details provided.')}", file=sys.stderr)
        Path(args.output).write_text(report, encoding="utf-8")
        if args.json_output:
            Path(args.json_output).write_text(
                format_json(contract_name, findings),
                encoding="utf-8",
            )
        print(f"Wrote report to {args.output}")
        if args.json_output:
            print(f"Wrote JSON report to {args.json_output}")
        return 0
    except (OSError, SlitherError, ValueError, RuntimeError, LLMBackendError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point for AI Smart Contract Vulnerability Checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.pipeline import analyze_contract_data
from src.report.formatter import format_json, format_report
from src.static_analysis import SlitherError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit one Solidity contract with Slither and an LLM.")
    parser.add_argument("--file", required=True, help="Path to a Solidity source file")
    parser.add_argument("--output", default="report.md", help="Markdown report path")
    parser.add_argument(
        "--json-output",
        help="Optional path for the raw JSON findings report",
    )
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    args = parser.parse_args(argv)
    try:
        contract_name, findings = analyze_contract_data(
            args.file,
            args.config,
            progress=lambda message: print(message, flush=True),
        )
        Path(args.output).write_text(format_report(contract_name, findings), encoding="utf-8")
        if args.json_output:
            Path(args.json_output).write_text(
                format_json(contract_name, findings),
                encoding="utf-8",
            )
        print(f"Wrote report to {args.output}")
        if args.json_output:
            print(f"Wrote JSON report to {args.json_output}")
        return 0
    except (OSError, SlitherError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

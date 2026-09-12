"""Run the labeled-contract evaluation.

A prediction matches a label when its normalized vulnerability type matches
and its function name matches the labeled function. Each prediction and label
is consumed at most once. This makes duplicate detector output count as a
false positive rather than artificially improving recall.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline import orchestrate, run_gas_agent  # noqa: E402


ALIASES = {
    "reentrancy-eth": "reentrancy",
    "reentrancy-no-eth": "reentrancy",
    "reentrancy-benign": "reentrancy",
    "arbitrary-send-eth": "access-control",
    "tx-origin": "tx-origin",
    "timestamp": "timestamp-dependence",
    "timestamp-dependence": "timestamp-dependence",
    "unchecked-low-level": "unchecked-call",
    "unchecked-low-level-call": "unchecked-call",
    "unchecked-call": "unchecked-call",
    "costly-loop": "costly-loop",
}


def _canonical(value: Any) -> str:
    text = re.sub(r"[_\s]+", "-", str(value).lower().strip())
    for alias, canonical in ALIASES.items():
        if alias in text:
            return canonical
    return text


def _load_labels(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except ImportError:
        # This intentionally handles the small documented subset used by the
        # checked-in labels, keeping evaluation usable in a bare Python env.
        records: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        expected: list[dict[str, Any]] = []
        current_expected: dict[str, Any] | None = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- file:"):
                if current is not None:
                    current["expected_vulnerabilities"] = expected
                    records.append(current)
                current = {"file": line.split(":", 1)[1].strip()}
                expected = []
                current_expected = None
            elif line.startswith("- type:") and current is not None:
                current_expected = {"type": line.split(":", 1)[1].strip()}
                expected.append(current_expected)
            elif line.startswith("type:") and current_expected is not None:
                current_expected["type"] = line.split(":", 1)[1].strip()
            elif line.startswith("function:") and current_expected is not None:
                current_expected["function"] = line.split(":", 1)[1].strip()
            elif line.startswith("expected_vulnerabilities:") and current is not None:
                value = line.split(":", 1)[1].strip()
                if value == "[]":
                    expected = []
        if current is not None:
            current["expected_vulnerabilities"] = expected
            records.append(current)
        return records


def _finding_type(finding: dict[str, Any]) -> str:
    return _canonical(finding.get("type", finding.get("check", "unknown")))


def _function(finding: dict[str, Any]) -> str:
    return str(finding.get("function", finding.get("function_name", "contract scope"))).split(",")[0].strip()


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_type = _canonical(expected.get("type", ""))
    actual_type = _finding_type(actual)
    type_match = actual_type == expected_type or expected_type in actual_type or actual_type in expected_type
    expected_function = str(expected.get("function", "")).strip()
    return type_match and (not expected_function or _function(actual) == expected_function)


def _metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate(labels: list[dict[str, Any]], *, config_path: str | Path = "config.yaml") -> dict[str, tuple[int, int, int]]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for record in labels:
        path = ROOT / str(record.get("file", ""))
        expected = list(record.get("expected_vulnerabilities") or [])
        try:
            sections = orchestrate(str(path), config_path)
            actual = sections["security"] + sections["gas"]
        except Exception as exc:
            print(f"SKIP {path}: {exc}", file=sys.stderr)
            # Gas checks are independent of Slither, so preserve those
            # predictions when the optional security tool is unavailable.
            try:
                actual = run_gas_agent(str(path), config_path)
            except Exception:
                actual = []
        remaining = list(expected)
        for finding in actual:
            match_index = next((index for index, item in enumerate(remaining) if _matches(finding, item)), None)
            if match_index is None:
                counts[_finding_type(finding)][1] += 1
            else:
                label_type = _canonical(remaining[match_index].get("type", "unknown"))
                counts[label_type][0] += 1
                remaining.pop(match_index)
        for item in remaining:
            counts[_canonical(item.get("type", "unknown"))][2] += 1
    return {key: tuple(value) for key, value in counts.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate smart-contract findings.")
    parser.add_argument("--labels", default=str(Path(__file__).with_name("labeled_contracts.yaml")))
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args(argv)
    counts = evaluate(_load_labels(Path(args.labels)), config_path=args.config)
    totals = [0, 0, 0]
    print(f"{'Type':28} {'TP':>4} {'FP':>4} {'FN':>4} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    for kind in sorted(counts):
        tp, fp, fn = counts[kind]
        totals[:] = [totals[0] + tp, totals[1] + fp, totals[2] + fn]
        precision, recall, f1 = _metrics(tp, fp, fn)
        print(f"{kind:28} {tp:4} {fp:4} {fn:4} {precision:10.1%} {recall:8.1%} {f1:8.1%}")
    precision, recall, f1 = _metrics(*totals)
    print(f"{'OVERALL':28} {totals[0]:4} {totals[1]:4} {totals[2]:4} {precision:10.1%} {recall:8.1%} {f1:8.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

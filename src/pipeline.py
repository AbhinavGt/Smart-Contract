"""End-to-end contract analysis orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .llm import AnthropicClient, DeterministicLLMClient, LLMClient, OllamaClient
from .llm.llm_client import config_value
from .prompts import (
    build_critique_prompt,
    build_explanation_prompt,
)
from .rag.retriever import retrieve
from .report.formatter import format_report
from .static_analysis import run_slither


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except ImportError:
        result: dict[str, Any] = {}
        section: dict[str, Any] | None = None
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith(" ") and stripped.endswith(":"):
                section = {}
                result[stripped[:-1]] = section
            elif section is not None and ":" in stripped:
                key, value = (part.strip() for part in stripped.split(":", 1))
                scalar = value.split("#", 1)[0].strip().strip('"\'')
                if scalar.lower() in {"true", "false"}:
                    section[key] = scalar.lower() == "true"
                else:
                    try:
                        section[key] = int(scalar)
                    except ValueError:
                        section[key] = scalar
        return result


def make_llm_client(config: dict[str, Any]) -> LLMClient:
    backend = str(config_value(config, "llm", "backend", default="ollama")).lower()
    model = str(config_value(config, "llm", "model", default="deepseek-coder"))
    timeout = int(config_value(config, "llm", "timeout_seconds", default=60))
    if backend == "anthropic":
        return AnthropicClient(model=model, timeout=timeout, fallback=DeterministicLLMClient())
    if backend == "ollama":
        return OllamaClient(
            model=model,
            base_url=str(config_value(config, "llm", "base_url", default="http://localhost:11434")),
            timeout=timeout,
        )
    raise ValueError(f"Unsupported LLM backend: {backend}")


def _snippet(source_lines: list[str], lines: list[int], radius: int = 2) -> str:
    if not lines:
        return "\n".join(source_lines[: min(20, len(source_lines))])
    start, end = max(1, min(lines) - radius), min(len(source_lines), max(lines) + radius)
    return "\n".join(f"{number}: {source_lines[number - 1]}" for number in range(start, end + 1))


def parse_critique(critique: str) -> tuple[str, str, str | None]:
    """Parse the critic's fixed response; malformed output is conservatively uncertain."""
    values: dict[str, str] = {}
    for line in critique.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().upper() in {"VERDICT", "REASON", "MISSING_CONTEXT"}:
            values[key.strip().upper()] = value.strip()
    verdict = values.get("VERDICT", "").upper()
    if verdict not in {"CONFIDENT", "UNCERTAIN"}:
        verdict = "UNCERTAIN"
    missing = values.get("MISSING_CONTEXT")
    if not missing or missing.lower() == "none":
        missing = None
    return verdict, values.get("REASON", "Critique response was incomplete."), missing


def fetch_additional_context(
    filepath: str,
    request: str,
    *,
    finding: dict[str, Any] | None = None,
    retriever: Callable[..., list[str]] = retrieve,
    top_k: int = 3,
    persist_directory: str | Path = "chroma_db",
    embedding_model: str = "all-MiniLM-L6-v2",
    collection: str = "vuln_knowledge",
) -> str:
    """Fetch read-only context requested by the critic."""
    source = Path(filepath).read_text(encoding="utf-8")
    request = request.strip()
    if request.lower().startswith("re-retrieve:"):
        topic = request.split(":", 1)[1].strip()
        try:
            results = retriever(
                topic, k=top_k, persist_directory=persist_directory,
                embedding_model=embedding_model, collection=collection,
            )
        except TypeError:
            results = retriever(topic, top_k)
        return "\n\n".join(results)
    if request.lower() == "calling function":
        function_name = str((finding or {}).get("function_name", "")).split(",")[0].strip()
        if not function_name or function_name == "contract scope":
            return "No calling function context could be identified."
        lines = source.splitlines()
        matches = [
            number for number, line in enumerate(lines, 1)
            if function_name in line and ("function " in line or f".{function_name}(" in line)
        ]
        return _snippet(lines, matches, radius=4) if matches else "No calling function context could be identified."
    return "No supported additional context request was identified."


def explain_finding_with_critic(
    finding: dict[str, Any],
    code_snippet: str,
    retrieved_context: list[str],
    *,
    filepath: str,
    llm: LLMClient,
    max_loops: int = 3,
    retriever: Callable[..., list[str]] = retrieve,
    persist_directory: str | Path = "chroma_db",
    embedding_model: str = "all-MiniLM-L6-v2",
    collection: str = "vuln_knowledge",
    explanation_prompt_builder: Callable[..., str] = build_explanation_prompt,
    critique_prompt_builder: Callable[..., str] = build_critique_prompt,
) -> tuple[str, bool, int]:
    """Generate and adapt an explanation using a bounded critic loop."""
    if max_loops < 0:
        raise ValueError("max_loops must be non-negative")
    explanation = llm.generate(
        explanation_prompt_builder(code_snippet, finding, retrieved_context)
    )
    for loop_number in range(1, max_loops + 1):
        verdict, _reason, missing = parse_critique(
            llm.generate(critique_prompt_builder(code_snippet, finding, explanation))
        )
        if verdict == "CONFIDENT":
            return explanation, True, loop_number
        if missing is None:
            return explanation, False, loop_number
        extra = fetch_additional_context(
            filepath, missing, finding=finding, retriever=retriever,
            top_k=len(retrieved_context) or 3,
            persist_directory=persist_directory, embedding_model=embedding_model,
            collection=collection,
        )
        context = retrieved_context + ([extra] if extra else [])
        explanation = llm.generate(
            explanation_prompt_builder(code_snippet, finding, context)
        )
    return explanation, False, max_loops


def analyze_contract_data(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    analyzer: Callable[[str], list[dict[str, Any]]] = run_slither,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    path = Path(filepath)
    source_lines = path.read_text(encoding="utf-8").splitlines()
    config = load_config(config_path)
    progress and progress("Running static analysis...")
    findings = analyzer(filepath)
    if not findings:
        return path.name, []
    client = llm_client or make_llm_client(config)
    top_k = int(config_value(config, "rag", "top_k", default=3))
    persist = config_value(config, "rag", "persist_directory", default="chroma_db")
    embedding = config_value(config, "rag", "embedding_model", default="all-MiniLM-L6-v2")
    max_loops = int(config_value(config, "agent", "max_loops", default=3))
    explained: list[dict[str, Any]] = []
    for finding in findings:
        progress and progress("Retrieving context...")
        try:
            context = retriever(
                f"{finding.get('check', '')} {finding.get('description', '')}",
                k=top_k,
                persist_directory=persist,
                embedding_model=embedding,
            )
        except TypeError:
            context = retriever(f"{finding.get('check', '')} {finding.get('description', '')}", top_k)
        progress and progress("Generating explanations...")
        item = dict(finding)
        explanation, confident, loops_used = explain_finding_with_critic(
            finding, _snippet(source_lines, finding.get("lines", [])), context,
            filepath=filepath, llm=client, max_loops=max_loops,
            retriever=retriever, persist_directory=persist, embedding_model=embedding,
        )
        item["explanation"] = explanation
        item["confident"] = confident
        item["loops_used"] = loops_used
        item.setdefault("type", item.get("check", "unknown"))
        item.setdefault("function", item.get("function_name", "contract scope"))
        explained.append(item)
    return path.name, explained


def run_security_agent(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    analyzer: Callable[[str], list[dict[str, Any]]] = run_slither,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Run the existing security agent and return its findings."""
    _contract_name, findings = analyze_contract_data(
        filepath,
        config_path,
        llm_client=llm_client,
        analyzer=analyzer,
        retriever=retriever,
        progress=progress,
    )
    return findings


def run_gas_agent(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Run the independent gas agent."""
    # Lazy import avoids a module cycle: gas_agent reuses critic helpers here.
    from .agents.gas_agent import analyze_gas

    return analyze_gas(
        filepath,
        config_path,
        llm_client=llm_client,
        retriever=retriever,
        progress=progress,
    )


def merge_findings(
    security_findings: list[dict[str, Any]],
    gas_findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Keep the two analysis domains separate for consumers and reports."""
    return {"security": list(security_findings), "gas": list(gas_findings)}


def orchestrate(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    analyzer: Callable[[str], list[dict[str, Any]]] = run_slither,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
    concurrent: bool | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Run security and gas agents and return findings by concern area."""
    config = load_config(config_path)
    if concurrent is None:
        concurrent = bool(config_value(config, "pipeline", "concurrent", default=False))
    if concurrent:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as executor:
            security_future = executor.submit(
                run_security_agent, filepath, config_path, llm_client=llm_client,
                analyzer=analyzer, retriever=retriever, progress=progress,
            )
            gas_future = executor.submit(
                run_gas_agent, filepath, config_path, llm_client=llm_client,
                retriever=retriever, progress=progress,
            )
            return merge_findings(security_future.result(), gas_future.result())
    return merge_findings(
        run_security_agent(
            filepath, config_path, llm_client=llm_client, analyzer=analyzer,
            retriever=retriever, progress=progress,
        ),
        run_gas_agent(
            filepath, config_path, llm_client=llm_client, retriever=retriever,
            progress=progress,
        ),
    )


def analyze_contract(
    filepath: str,
    config_path: str | Path = "config.yaml",
    *,
    llm_client: LLMClient | None = None,
    analyzer: Callable[[str], list[dict[str, Any]]] = run_slither,
    retriever: Callable[..., list[str]] = retrieve,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Analyze one Solidity file and return Markdown (legacy API)."""
    contract_name = Path(filepath).name
    findings = orchestrate(
        filepath,
        config_path,
        llm_client=llm_client,
        analyzer=analyzer,
        retriever=retriever,
        progress=progress,
    )
    return format_report(contract_name, findings)
